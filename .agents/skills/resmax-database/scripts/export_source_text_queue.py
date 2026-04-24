#!/usr/bin/env python3
"""Export rows whose source-text anchor should be upgraded by web search."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


NEEDS_SEARCH_STATUSES = {
    "publisher_landing_only",
    "official_landing_only",
    "source_listing_only",
    "missing_anchor_needs_search",
    "unresolved_after_search",
}

FIELDNAMES = [
    "paper_id",
    "title",
    "venue",
    "year",
    "conf_year",
    "source_type",
    "doi",
    "pdf_status",
    "pdf_url",
    "source_text_status",
    "source_text_url",
    "source_text_source",
    "source_text_search_query",
    "source_text_evidence",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="paper_database/accepted_index.csv")
    parser.add_argument("--out", default="/tmp/resmax_source_text_search_queue.csv")
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows to export; 0 means all")
    parser.add_argument(
        "--statuses",
        default="",
        help="Comma-separated source_text_status values; default exports all upgrade-needed statuses",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    statuses = {
        item.strip()
        for item in args.statuses.split(",")
        if item.strip()
    } or NEEDS_SEARCH_STATUSES

    with Path(args.csv).open(newline="", encoding="utf-8") as f:
        rows = [
            row
            for row in csv.DictReader(f)
            if (row.get("source_text_status", "") or "").strip() in statuses
        ]

    rows.sort(key=lambda row: (
        row.get("source_text_status", ""),
        row.get("venue", ""),
        row.get("conf_year", ""),
        row.get("title", ""),
    ))
    if args.limit:
        rows = rows[: args.limit]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"[queue] wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
