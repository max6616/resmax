#!/usr/bin/env python3
"""Batch-enrich accepted_index.csv with abstracts via Semantic Scholar batch API
and arXiv batch API.

Layer 2 strategy — high-throughput batch enrichment:
  1. Build S2 paper IDs from available identifiers (arxiv_id > DOI > title-derived)
  2. S2 batch API: POST /graph/v1/paper/batch (500 papers/request)
  3. arXiv batch API fallback: GET /api/query?id_list=... (100 IDs/request)

Usage:
  python3 enrich_abstracts.py --csv paper_database/accepted_index.csv
  python3 enrich_abstracts.py --csv paper_database/accepted_index.csv --filter CVPR
  python3 enrich_abstracts.py --csv paper_database/accepted_index.csv --dry-run
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_FIELDS = "title,abstract,externalIds,openAccessPdf"
S2_BATCH_SIZE = 500
ARXIV_BATCH_SIZE = 80
ARXIV_API_URL = "http://export.arxiv.org/api/query"


def _extract_doi_from_link(paper_link: str) -> str:
    m = re.match(r"https?://doi\.org/(10\.\d{4,}/[^\s,]+)", paper_link)
    return m.group(1) if m else ""


def _extract_aaai_article_id(paper_link: str) -> str:
    m = re.search(r"ojs\.aaai\.org/index\.php/AAAI/article/view/(\d+)", paper_link)
    return m.group(1) if m else ""


def _build_s2_id(row: dict) -> str:
    """Build the best S2 paper identifier from available fields."""
    arxiv_id = row.get("arxiv_id", "").strip()
    if arxiv_id:
        return f"ARXIV:{arxiv_id}"

    doi = row.get("doi", "").strip()
    if doi:
        return f"DOI:{doi}"

    doi_from_link = _extract_doi_from_link(row.get("paper_link", ""))
    if doi_from_link:
        return f"DOI:{doi_from_link}"

    forum_id = row.get("openreview_forum_id", "").strip()
    if forum_id:
        return f"URL:https://openreview.net/forum?id={forum_id}"

    return ""


def _s2_batch_fetch(ids: list[str], timeout: int = 60) -> list[dict | None]:
    url = f"{S2_BATCH_URL}?fields={S2_FIELDS}"
    payload = json.dumps({"ids": ids}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"User-Agent": "resmax/1.0", "Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())


def _arxiv_batch_fetch(arxiv_ids: list[str], timeout: int = 30) -> dict[str, dict]:
    """Fetch metadata for multiple arXiv IDs in one request.
    Returns {arxiv_id: {title, abstract}} for found papers.
    """
    id_list = ",".join(arxiv_ids)
    url = f"{ARXIV_API_URL}?id_list={id_list}&max_results={len(arxiv_ids)}"
    req = urllib.request.Request(url, headers={"User-Agent": "resmax/1.0"})
    body = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")

    results: dict[str, dict] = {}
    for entry in re.findall(r"<entry>(.*?)</entry>", body, re.S):
        aid_m = re.search(r"<id>http://arxiv\.org/abs/(\d{4}\.\d{4,5})", entry)
        abs_m = re.search(r"<summary>(.*?)</summary>", entry, re.S)
        title_m = re.search(r"<title>(.*?)</title>", entry, re.S)
        if aid_m and abs_m:
            aid = aid_m.group(1)
            abstract = re.sub(r"\s+", " ", abs_m.group(1)).strip()
            title = re.sub(r"\s+", " ", title_m.group(1)).strip() if title_m else ""
            if abstract:
                results[aid] = {"abstract": abstract, "title": title}
    return results


def _apply_s2_result(row: dict, result: dict) -> list[str]:
    """Apply S2 batch result to a CSV row. Returns list of actions taken."""
    actions = []
    abstract = (result.get("abstract") or "").strip()
    if abstract:
        row["abstract_raw"] = abstract
        actions.append("abstract")

    ext = result.get("externalIds", {})
    if ext.get("ArXiv") and not row.get("arxiv_id", "").strip():
        row["arxiv_id"] = ext["ArXiv"]
        row["arxiv_url"] = f"https://arxiv.org/abs/{ext['ArXiv']}"
        actions.append("arxiv_id")

    doi = ext.get("DOI", "")
    if doi and not row.get("doi", "").strip():
        row["doi"] = doi
        actions.append("doi")

    return actions


def main():
    import argparse
    p = argparse.ArgumentParser(description="Batch-enrich abstracts (Layer 2)")
    p.add_argument("--csv", required=True, help="Path to accepted_index.csv")
    p.add_argument("--filter", default="", help="Only process rows where conf_year contains this string")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        print(f"[ERROR] CSV not found: {csv_path}", file=sys.stderr)
        return 1

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    print(f"[enrich] loaded {len(rows)} rows", flush=True)

    # Phase 1: Find rows needing enrichment and build S2 IDs
    targets: list[tuple[int, str]] = []  # (row_idx, s2_id)
    for i, row in enumerate(rows):
        if args.filter and args.filter not in row.get("conf_year", ""):
            continue
        if row.get("abstract_raw", "").strip():
            continue
        s2_id = _build_s2_id(row)
        if s2_id:
            targets.append((i, s2_id))

    id_type_counts = {}
    for _, s2_id in targets:
        prefix = s2_id.split(":")[0]
        id_type_counts[prefix] = id_type_counts.get(prefix, 0) + 1

    print(f"[enrich] {len(targets)} papers need abstract (have S2 ID)", flush=True)
    for prefix, count in sorted(id_type_counts.items()):
        print(f"  {prefix}: {count}", flush=True)

    if not targets:
        print("[enrich] nothing to do", flush=True)
        return 0

    # Phase 2: S2 batch API
    enriched = 0
    not_found = 0
    no_abstract = 0
    errors = 0
    total_batches = (len(targets) + S2_BATCH_SIZE - 1) // S2_BATCH_SIZE

    print(f"\n[S2 batch] starting {total_batches} batches...", flush=True)

    for batch_start in range(0, len(targets), S2_BATCH_SIZE):
        batch = targets[batch_start:batch_start + S2_BATCH_SIZE]
        batch_ids = [s2_id for _, s2_id in batch]
        batch_num = batch_start // S2_BATCH_SIZE + 1

        print(f"  [{batch_num}/{total_batches}] fetching {len(batch)} papers...",
              end="", flush=True)

        for attempt in range(3):
            try:
                results = _s2_batch_fetch(batch_ids)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = 30 * (attempt + 1)
                    print(f" rate-limited, waiting {wait}s...", end="", flush=True)
                    time.sleep(wait)
                else:
                    print(f" HTTP {e.code}", flush=True)
                    errors += len(batch)
                    results = None
                    break
            except Exception as e:
                print(f" error: {e}", flush=True)
                errors += len(batch)
                results = None
                break
        else:
            print(f" failed after 3 retries", flush=True)
            errors += len(batch)
            continue

        if results is None:
            continue

        batch_enriched = 0
        for (row_idx, s2_id), result in zip(batch, results):
            if result is None:
                not_found += 1
                continue
            actions = _apply_s2_result(rows[row_idx], result) if not args.dry_run else []
            if (result.get("abstract") or "").strip():
                batch_enriched += 1
                enriched += 1
            else:
                no_abstract += 1

        print(f" +{batch_enriched} abstracts", flush=True)

        if batch_start + S2_BATCH_SIZE < len(targets):
            time.sleep(1.0)

    print(f"\n[S2 batch] done: enriched={enriched}, not_found={not_found}, "
          f"no_abstract={no_abstract}, errors={errors}", flush=True)

    # Phase 3: arXiv batch fallback for papers with arxiv_id but still no abstract
    arxiv_fallback: list[tuple[int, str]] = []
    for i, row in enumerate(rows):
        if args.filter and args.filter not in row.get("conf_year", ""):
            continue
        if row.get("abstract_raw", "").strip():
            continue
        arxiv_id = row.get("arxiv_id", "").strip()
        if arxiv_id:
            arxiv_fallback.append((i, arxiv_id))

    if arxiv_fallback:
        total_arxiv_batches = (len(arxiv_fallback) + ARXIV_BATCH_SIZE - 1) // ARXIV_BATCH_SIZE
        print(f"\n[arXiv batch] {len(arxiv_fallback)} papers still missing abstract, "
              f"{total_arxiv_batches} batches...", flush=True)

        arxiv_enriched = 0
        for batch_start in range(0, len(arxiv_fallback), ARXIV_BATCH_SIZE):
            batch = arxiv_fallback[batch_start:batch_start + ARXIV_BATCH_SIZE]
            batch_num = batch_start // ARXIV_BATCH_SIZE + 1
            ids = [aid for _, aid in batch]

            print(f"  [{batch_num}/{total_arxiv_batches}] fetching {len(batch)} papers...",
                  end="", flush=True)

            try:
                results = _arxiv_batch_fetch(ids)
                for row_idx, aid in batch:
                    if aid in results and not args.dry_run:
                        rows[row_idx]["abstract_raw"] = results[aid]["abstract"]
                        arxiv_enriched += 1
                print(f" +{sum(1 for _, aid in batch if aid in results)}", flush=True)
            except Exception as e:
                print(f" error: {e}", flush=True)

            time.sleep(3.0)

        print(f"[arXiv batch] enriched {arxiv_enriched} more papers", flush=True)
        enriched += arxiv_enriched

    # Summary
    still_missing = sum(
        1 for row in rows
        if (not args.filter or args.filter in row.get("conf_year", ""))
        and not row.get("abstract_raw", "").strip()
    )
    print(f"\n[enrich] final: enriched={enriched}, still_missing={still_missing}", flush=True)

    if not args.dry_run and enriched > 0:
        backup = csv_path.with_suffix(".csv.bak")
        shutil.copy2(csv_path, backup)
        print(f"[enrich] backup: {backup}", flush=True)

        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"[enrich] wrote updated CSV: {csv_path}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
