#!/usr/bin/env python3
"""Enrich accepted_index.csv with code repository URLs from multiple sources.

Layer 1 strategy — three-source code URL enrichment:
  1. Papers With Code historical dump (links-between-papers-and-code.json.gz)
  2. Semantic Scholar batch API (externalIds → GitHub URLs)
  3. Regex extraction from abstract_raw (github.com / gitlab.com links)

Usage:
  python3 enrich_code_urls.py --csv paper_database/accepted_index.csv
  python3 enrich_code_urls.py --csv paper_database/accepted_index.csv --filter ICLR_2026
  python3 enrich_code_urls.py --csv paper_database/accepted_index.csv --pwc-dump /tmp/pwc
  python3 enrich_code_urls.py --csv paper_database/accepted_index.csv --dry-run
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Auto-load .secrets/*.env so S2_API_KEY is picked up from .secrets/s2.env.
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
import secrets_loader  # noqa: E402,F401
from data_contracts import normalize_repo_url  # noqa: E402


PWC_PAPERS_URL = "https://paperswithcode.com/media/about/papers-with-abstracts.json.gz"
PWC_LINKS_URL = "https://paperswithcode.com/media/about/links-between-papers-and-code.json.gz"

S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "externalIds,url"
S2_BATCH_SIZE = 500

GITHUB_URL_RE = re.compile(
    r"https?://(?:www\.)?github\.com/([a-zA-Z0-9\-_.]+/[a-zA-Z0-9\-_.]+)",
    re.IGNORECASE,
)
GITLAB_URL_RE = re.compile(
    r"https?://(?:www\.)?gitlab\.com/([a-zA-Z0-9\-_.]+/[a-zA-Z0-9\-_.]+)",
    re.IGNORECASE,
)


def _normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Source 1: Papers With Code dump
# ---------------------------------------------------------------------------

def _download_file(url: str, dest: Path) -> None:
    print(f"  downloading {url} ...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "resmax-enrich/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)
    print(f"  saved to {dest} ({dest.stat().st_size / 1024 / 1024:.1f} MB)", flush=True)


def _load_pwc_links(pwc_dir: Path) -> dict[str, list[str]]:
    """Load PWC links dump. Returns {paper_url: [repo_url, ...]}."""
    json_path = pwc_dir / "links.json"
    gz_path = pwc_dir / "links-between-papers-and-code.json.gz"

    if json_path.exists():
        print("[PWC] loading links.json ...", flush=True)
        with open(json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    elif gz_path.exists():
        print("[PWC] loading links-between-papers-and-code.json.gz ...", flush=True)
        with gzip.open(gz_path, "rt", encoding="utf-8") as f:
            raw = json.load(f)
    else:
        _download_file(PWC_LINKS_URL, gz_path)
        with gzip.open(gz_path, "rt", encoding="utf-8") as f:
            raw = json.load(f)

    result: dict[str, list[str]] = {}
    for entry in raw:
        paper_url = entry.get("paper_url", "").strip()
        repo_url = entry.get("repo_url", "").strip()
        if paper_url and repo_url:
            result.setdefault(paper_url, []).append(repo_url)
    print(f"[PWC] loaded {len(result)} paper→code mappings", flush=True)
    return result


def _load_pwc_papers(pwc_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Build title→paper_url and arxiv_id→paper_url from links or papers dump."""
    json_path = pwc_dir / "links.json"
    gz_path = pwc_dir / "links-between-papers-and-code.json.gz"
    papers_gz = pwc_dir / "papers-with-abstracts.json.gz"

    if json_path.exists():
        print("[PWC] building paper index from links.json ...", flush=True)
        with open(json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    elif gz_path.exists():
        with gzip.open(gz_path, "rt", encoding="utf-8") as f:
            raw = json.load(f)
    elif papers_gz.exists():
        print("[PWC] loading papers-with-abstracts.json.gz ...", flush=True)
        with gzip.open(papers_gz, "rt", encoding="utf-8") as f:
            raw = json.load(f)
    else:
        print("[PWC] no papers dump found, skipping title/arxiv index", flush=True)
        return {}, {}

    title_to_url: dict[str, str] = {}
    arxiv_to_url: dict[str, str] = {}
    for entry in raw:
        title = entry.get("paper_title", "") or entry.get("title", "")
        title = title.strip()
        paper_url = entry.get("paper_url", "").strip()
        arxiv_id = (entry.get("paper_arxiv_id", "") or entry.get("arxiv_id", "")).strip()
        if title and paper_url:
            title_to_url[_normalize_title(title)] = paper_url
        if arxiv_id and paper_url:
            arxiv_to_url[arxiv_id] = paper_url
    print(
        f"[PWC] indexed {len(title_to_url)} titles, "
        f"{len(arxiv_to_url)} arxiv IDs",
        flush=True,
    )
    return title_to_url, arxiv_to_url


def _match_pwc(
    rows: list[dict],
    pwc_links: dict[str, list[str]],
    pwc_title_to_url: dict[str, str],
    pwc_arxiv_to_url: dict[str, str],
) -> int:
    """Match rows against PWC dump. Returns count of newly enriched rows."""
    enriched = 0
    for row in rows:
        if row.get("code_url", "").strip():
            continue

        paper_url = None
        arxiv_id = row.get("arxiv_id", "").strip()
        if arxiv_id and arxiv_id in pwc_arxiv_to_url:
            paper_url = pwc_arxiv_to_url[arxiv_id]
        if not paper_url:
            norm_title = _normalize_title(row.get("title", ""))
            if norm_title in pwc_title_to_url:
                paper_url = pwc_title_to_url[norm_title]

        if paper_url and paper_url in pwc_links:
            repos = pwc_links[paper_url]
            best = repos[0]
            for r in repos:
                if "github.com" in r:
                    best = r
                    break
            row["code_url"] = normalize_repo_url(best)
            enriched += 1

    return enriched


# ---------------------------------------------------------------------------
# Source 2: Semantic Scholar batch API
# ---------------------------------------------------------------------------

def _build_s2_id(row: dict) -> Optional[str]:
    arxiv_id = row.get("arxiv_id", "").strip()
    if arxiv_id:
        return f"ARXIV:{arxiv_id}"
    doi = row.get("doi", "").strip()
    if doi:
        return f"DOI:{doi}"
    return None


def _s2_batch_fetch(ids: list[str]) -> list[Optional[dict]]:
    payload = json.dumps({"ids": ids}).encode()
    url = f"{S2_BATCH_URL}?fields={S2_FIELDS}"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "resmax-enrich/1.0",
        },
    )
    api_key = os.environ.get("S2_API_KEY", "")
    if api_key:
        req.add_header("x-api-key", api_key)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _extract_github_from_s2(paper: dict) -> Optional[str]:
    """Try to extract a GitHub URL from S2 paper data."""
    s2_url = paper.get("url", "")
    ext_ids = paper.get("externalIds", {}) or {}
    github_url = ext_ids.get("GitHub", "")
    if github_url:
        if not github_url.startswith("http"):
            github_url = f"https://github.com/{github_url}"
        return normalize_repo_url(github_url)
    return None


def _match_s2(rows: list[dict]) -> int:
    """Enrich code_url via S2 batch API. Returns count of newly enriched."""
    targets = []
    for i, row in enumerate(rows):
        if row.get("code_url", "").strip():
            continue
        s2_id = _build_s2_id(row)
        if s2_id:
            targets.append((i, s2_id))

    if not targets:
        print("[S2] no papers to query (all have code_url or no S2 ID)", flush=True)
        return 0

    print(f"[S2] querying {len(targets)} papers...", flush=True)
    enriched = 0
    total_batches = (len(targets) + S2_BATCH_SIZE - 1) // S2_BATCH_SIZE

    for batch_start in range(0, len(targets), S2_BATCH_SIZE):
        batch = targets[batch_start : batch_start + S2_BATCH_SIZE]
        batch_ids = [s2_id for _, s2_id in batch]
        batch_num = batch_start // S2_BATCH_SIZE + 1
        print(f"  [{batch_num}/{total_batches}] {len(batch)} papers...", end="", flush=True)

        for attempt in range(3):
            try:
                results = _s2_batch_fetch(batch_ids)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = 30 * (attempt + 1)
                    print(f" rate-limited, wait {wait}s...", end="", flush=True)
                    time.sleep(wait)
                else:
                    print(f" HTTP {e.code}", flush=True)
                    results = [None] * len(batch)
                    break
            except Exception as exc:
                print(f" error: {exc}", flush=True)
                results = [None] * len(batch)
                break
        else:
            results = [None] * len(batch)

        for (row_idx, _), paper in zip(batch, results):
            if paper is None:
                continue
            github_url = _extract_github_from_s2(paper)
            if github_url:
                rows[row_idx]["code_url"] = github_url
                enriched += 1

        print(f" +{enriched}", flush=True)
        time.sleep(1.0)

    return enriched


# ---------------------------------------------------------------------------
# Source 3: Regex extraction from abstract
# ---------------------------------------------------------------------------

def _match_regex(rows: list[dict]) -> int:
    """Extract GitHub/GitLab URLs from abstract_raw. Returns enriched count."""
    enriched = 0
    for row in rows:
        if row.get("code_url", "").strip():
            continue
        abstract = row.get("abstract_raw", "")
        if not abstract:
            continue

        for pattern in (GITHUB_URL_RE, GITLAB_URL_RE):
            m = pattern.search(abstract)
            if m:
                full_url = m.group(0)
                normalized = normalize_repo_url(full_url)
                owner_repo = normalized.split("/")[-2:]
                if len(owner_repo) == 2:
                    owner, repo = owner_repo
                    skip_owners = {
                        "features", "issues", "pulls", "blob", "tree",
                        "wiki", "settings", "actions", "releases",
                    }
                    if repo.lower() not in skip_owners:
                        row["code_url"] = normalized
                        enriched += 1
                        break
    return enriched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Enrich code_url from PWC + S2 + regex")
    parser.add_argument("--csv", required=True, help="Path to accepted_index.csv")
    parser.add_argument("--filter", default="", help="Only process rows whose conf_year contains this string")
    parser.add_argument("--pwc-dump", default="", help="Directory for PWC dump files (default: /tmp/pwc_dump)")
    parser.add_argument("--skip-pwc", action="store_true", help="Skip PWC dump matching")
    parser.add_argument("--skip-s2", action="store_true", help="Skip S2 API matching")
    parser.add_argument("--skip-regex", action="store_true", help="Skip regex extraction")
    parser.add_argument("--dry-run", action="store_true", help="Only count, don't write")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[ERROR] CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    csv.field_size_limit(10 * 1024 * 1024)
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    conf_filter = args.filter.strip()
    if conf_filter:
        target_rows = [r for r in rows if conf_filter in r.get("conf_year", "")]
    else:
        target_rows = rows

    total = len(target_rows)
    already_has = sum(1 for r in target_rows if r.get("code_url", "").strip())
    missing = total - already_has
    print(f"[enrich_code_urls] loaded {total} rows (filter={conf_filter or 'all'})", flush=True)
    print(f"[enrich_code_urls] {already_has} already have code_url, {missing} missing", flush=True)

    if missing == 0:
        print("[enrich_code_urls] nothing to do", flush=True)
        return 0

    pwc_enriched = 0
    s2_enriched = 0
    regex_enriched = 0

    # Source 1: PWC dump
    if not args.skip_pwc:
        pwc_dir = Path(args.pwc_dump) if args.pwc_dump else Path("/tmp/pwc_dump")
        pwc_dir.mkdir(parents=True, exist_ok=True)
        try:
            pwc_links = _load_pwc_links(pwc_dir)
            pwc_title_to_url, pwc_arxiv_to_url = _load_pwc_papers(pwc_dir)
            pwc_enriched = _match_pwc(target_rows, pwc_links, pwc_title_to_url, pwc_arxiv_to_url)
            print(f"[PWC] enriched {pwc_enriched} papers", flush=True)
        except Exception as exc:
            print(f"[PWC] failed: {exc}", file=sys.stderr, flush=True)

    # Source 2: S2 API
    if not args.skip_s2:
        try:
            s2_enriched = _match_s2(target_rows)
            print(f"[S2] enriched {s2_enriched} papers", flush=True)
        except Exception as exc:
            print(f"[S2] failed: {exc}", file=sys.stderr, flush=True)

    # Source 3: Regex
    if not args.skip_regex:
        regex_enriched = _match_regex(target_rows)
        print(f"[Regex] enriched {regex_enriched} papers", flush=True)

    total_enriched = pwc_enriched + s2_enriched + regex_enriched
    final_has = sum(1 for r in target_rows if r.get("code_url", "").strip())
    still_missing = total - final_has

    print(f"\n[enrich_code_urls] done: enriched={total_enriched} "
          f"(PWC={pwc_enriched}, S2={s2_enriched}, regex={regex_enriched})", flush=True)
    print(f"[enrich_code_urls] final: {final_has}/{total} "
          f"({final_has / total * 100:.1f}%), still_missing={still_missing}", flush=True)

    if args.dry_run:
        print("[enrich_code_urls] dry-run mode, not writing", flush=True)
        return 0

    backup = csv_path.with_suffix(".csv.bak")
    shutil.copy2(csv_path, backup)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[enrich_code_urls] wrote updated CSV: {csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
