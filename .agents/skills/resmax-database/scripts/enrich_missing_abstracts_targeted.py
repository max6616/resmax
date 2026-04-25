#!/usr/bin/env python3
"""Targeted abstract fixes for known source-specific gaps.

This script only fills abstracts from authoritative paper pages/APIs:
- TMLR rows embedded in EventHosts virtual-conference JSON via OpenReview.
- Project pages with explicit Abstract sections.
- Direct PDF pages via pdftotext extraction.

It deliberately does not delete rows. Rows that remain unresolved should be
sent to a per-paper web-search queue before any deletion decision.
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
import secrets_loader  # noqa: E402,F401


INVALID_ABSTRACTS = {"", "none", "null", "nan", "n/a", "international audience", "tba"}


def is_valid_abstract(raw: str) -> bool:
    text = (raw or "").strip()
    return bool(text) and text.lower() not in INVALID_ABSTRACTS and len(text) >= 10


def normalize_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_tmlr_abstracts() -> dict[str, str]:
    try:
        from openreview.api import OpenReviewClient
    except ImportError:
        print("[targeted] openreview-py unavailable; skipping TMLR")
        return {}

    username = os.environ.get("OPENREVIEW_USERNAME", "")
    password = os.environ.get("OPENREVIEW_PASSWORD", "")
    if not username or not password:
        print("[targeted] OpenReview credentials unavailable; skipping TMLR")
        return {}

    client = OpenReviewClient(
        baseurl="https://api2.openreview.net",
        username=username,
        password=password,
    )
    notes = client.get_all_notes(invitation="TMLR/-/Submission")
    out: dict[str, str] = {}
    for note in notes:
        content = note.content or {}
        title = content.get("title", "")
        abstract = content.get("abstract", "")
        if isinstance(title, dict):
            title = title.get("value", "")
        if isinstance(abstract, dict):
            abstract = abstract.get("value", "")
        abstract = clean_text(str(abstract))
        if title and is_valid_abstract(abstract):
            out[normalize_title(str(title))] = abstract
    print(f"[targeted] loaded {len(out)} TMLR abstracts")
    return out


def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "ignore")


def fetch_project_page_abstract(url: str) -> str:
    if not url:
        return ""
    try:
        body = fetch_html(url)
    except Exception:
        return ""
    patterns = [
        r"<h2[^>]*>\s*Abstract\s*</h2>(.*?)(?:<h2|</section>|</div>\s*</div>)",
        r"Abstract</[^>]+>\s*<[^>]+>(.*?)</",
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, body, re.I | re.S)
        if m:
            text = clean_text(m.group(1))
            if is_valid_abstract(text) and text.lower() != clean_text(url).lower():
                return text
    return ""


def fetch_pdf_abstract(url: str) -> str:
    if not url or not shutil.which("pdftotext"):
        return ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "paper.pdf"
            txt_path = Path(tmp) / "paper.txt"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                pdf_path.write_bytes(resp.read())
            subprocess.run(
                ["pdftotext", "-f", "1", "-l", "2", str(pdf_path), str(txt_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            text = txt_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"\bAbstract\b\s*(.*?)(?:\b1\s+Introduction\b|\bIntroduction\b|\bKeywords\b)", text, re.I)
    if not m:
        return ""
    abstract = clean_text(m.group(1))
    return abstract if is_valid_abstract(abstract) else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--unresolved-out", default="/tmp/resmax_abstract_web_search_queue.csv")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    targets = [r for r in rows if not is_valid_abstract(r.get("abstract_raw", ""))]
    print(f"[targeted] unresolved before: {len(targets)}")
    tmlr_map: dict[str, str] = {}
    changed = 0
    source_counts: dict[str, int] = {}

    for row in targets:
        source = ""
        abstract = ""
        sourceurl = row.get("sourceurl", "")
        title_key = normalize_title(row.get("title", ""))
        if "TMLR" in sourceurl:
            if not tmlr_map:
                tmlr_map = load_tmlr_abstracts()
            abstract = tmlr_map.get(title_key, "")
            source = "openreview_tmlr"
        if not abstract and row.get("pdf_url", "").lower().endswith(".pdf"):
            abstract = fetch_pdf_abstract(row.get("pdf_url", ""))
            source = "pdf_pdftotext" if abstract else source
        if not abstract and row.get("landing_url", "").startswith("http"):
            abstract = fetch_project_page_abstract(row.get("landing_url", ""))
            source = "project_page" if abstract else source

        if abstract:
            changed += 1
            source_counts[source] = source_counts.get(source, 0) + 1
            if not args.dry_run:
                row["abstract_raw"] = abstract
                row["abstract_status"] = "ok"

    unresolved = [r for r in rows if not is_valid_abstract(r.get("abstract_raw", ""))]
    print(f"[targeted] changed={changed}, sources={source_counts}")
    print(f"[targeted] unresolved after: {len(unresolved)}")

    unresolved_fields = [
        "paper_id", "conf_year", "venue", "year", "title", "authors", "doi",
        "landing_url", "pdf_url", "source_type", "sourceurl", "abstract_status",
    ]
    with Path(args.unresolved_out).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=unresolved_fields)
        writer.writeheader()
        for row in unresolved:
            writer.writerow({k: row.get(k, "") for k in unresolved_fields})
    print(f"[targeted] unresolved queue: {args.unresolved_out}")

    if changed and not args.dry_run:
        backup = csv_path.with_suffix(csv_path.suffix + ".bak")
        shutil.copy2(csv_path, backup)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"[targeted] backup: {backup}")
        print(f"[targeted] wrote: {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
