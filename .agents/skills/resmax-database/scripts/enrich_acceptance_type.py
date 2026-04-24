#!/usr/bin/env python3
"""Fill in the `acceptance_type` column for rows that the builder left blank.

`build_accepted_index.py` infers `acceptance_type` from virtual-conference
JSON fields (decision / event_type / eventtype) whenever those are present.
Many data sources do not expose those fields, leaving the column empty.
This script applies the deterministic venue-specific mapping rules documented
in SKILL.md ("录用等级映射规则 A-E") so new conferences can reach 100%
coverage without a manual pass.

Rules (in order):
  A. VC-JSON venues (ICLR/NeurIPS/ICML/CVPR/ECCV/ICCV): rows with still-empty
     acceptance_type default to `Poster`. (Usually only CVF-only auxiliary
     rows fall here.)
  B. ACL/EMNLP (ACL Anthology): decision is already one of
     Main/Findings/Main Short/SRW/Industry/Demo → copy directly.
  C. SIGGRAPH / SIGGRAPH_Asia (Ke-Sen Huang): keywords_raw carries
     `SIG` / `TOG` / `SIG/TOG` → `Conference Paper` / `Journal Paper` /
     `Conference+Journal`. Empty keywords_raw → `Conference Paper`.
  D. AAAI / ACMMM / KDD: no oral/poster distinction in data source → `Poster`.
  E. Journals (TPAMI / IJCV / JMLR / AIJ / TNNLS): `Journal Article`.

The script is idempotent: rows with a non-empty acceptance_type are skipped
unless `--refresh` is passed.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

csv.field_size_limit(100 * 1024 * 1024)


VC_JSON_VENUES = {"ICLR", "NeurIPS", "ICML", "CVPR", "ECCV", "ICCV"}
ACL_VENUES = {"ACL", "EMNLP", "NAACL"}
SIGGRAPH_VENUES = {"SIGGRAPH", "SIGGRAPH_Asia"}
NO_DISTINCTION_CONFS = {"AAAI", "ACMMM", "KDD"}
JOURNAL_VENUES = {"TPAMI", "IJCV", "JMLR", "AIJ", "TNNLS"}


ACL_DECISION_CANON = {
    "main": "Main",
    "findings": "Findings",
    "main short": "Main Short",
    "short": "Main Short",
    "srw": "SRW",
    "industry": "Industry",
    "demo": "Demo",
    "system demonstration": "Demo",
}


def _map_acl(decision: str) -> str:
    d = decision.strip().lower()
    # Try direct matches first; fall back to substring match.
    if d in ACL_DECISION_CANON:
        return ACL_DECISION_CANON[d]
    for key, val in ACL_DECISION_CANON.items():
        if key in d:
            return val
    # Unknown ACL bucket: fall back to Main (default track).
    return "Main"


def _map_siggraph(keywords_raw: str) -> str:
    kw = keywords_raw.strip().upper()
    if "SIG/TOG" in kw or "SIG+TOG" in kw or ("SIG" in kw and "TOG" in kw):
        return "Conference+Journal"
    if kw == "TOG":
        return "Journal Paper"
    if kw == "SIG":
        return "Conference Paper"
    return "Conference Paper"  # empty keyword default


def infer_acceptance_type(row: dict) -> str:
    """Return the inferred acceptance_type for a row. Empty string = unknown."""
    venue = row.get("venue", "").strip()
    decision = row.get("decision", "").strip()

    if venue in VC_JSON_VENUES:
        # Builder already set most; anything still empty is an auxiliary-only
        # row on venues like CVPR → default Poster.
        return "Poster"

    if venue in ACL_VENUES:
        return _map_acl(decision)

    if venue in SIGGRAPH_VENUES:
        return _map_siggraph(row.get("keywords_raw", ""))

    if venue in NO_DISTINCTION_CONFS:
        return "Poster"

    if venue in JOURNAL_VENUES:
        return "Journal Article"

    # Unknown venue: leave unchanged.
    return ""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--csv", required=True)
    p.add_argument("--filter", default="", help="Only process rows whose conf_year contains this string")
    p.add_argument(
        "--refresh",
        action="store_true",
        help="Overwrite even non-empty acceptance_type values (e.g. the generic 'Accept').",
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[acceptance_type] ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 1

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    conf_filter = args.filter.strip()
    scope = [r for r in rows if not conf_filter or conf_filter in r.get("conf_year", "")]
    print(f"[acceptance_type] scope: {len(scope)}/{len(rows)} rows (filter={conf_filter or 'all'})")

    before_empty = sum(1 for r in scope if not r.get("acceptance_type", "").strip())
    before_accept = sum(1 for r in scope if r.get("acceptance_type", "").strip() == "Accept")
    print(f"[acceptance_type] before: empty={before_empty}, bare 'Accept'={before_accept}")

    changes = 0
    unknown_venues: set[str] = set()
    for r in scope:
        current = r.get("acceptance_type", "").strip()
        # Skip rows that already have a specific label unless --refresh was given.
        # We always rewrite a bare "Accept" because it carries no oral/poster info.
        if current and current != "Accept" and not args.refresh:
            continue
        inferred = infer_acceptance_type(r)
        if not inferred:
            unknown_venues.add(r.get("venue", ""))
            continue
        if inferred != current:
            r["acceptance_type"] = inferred
            changes += 1

    after_empty = sum(1 for r in scope if not r.get("acceptance_type", "").strip())
    after_accept = sum(1 for r in scope if r.get("acceptance_type", "").strip() == "Accept")
    print(f"[acceptance_type] after:  empty={after_empty}, bare 'Accept'={after_accept}, changes={changes}")
    if unknown_venues:
        print(f"[acceptance_type] venues with no mapping rule: {sorted(unknown_venues)}")

    if args.dry_run:
        print("[acceptance_type] dry-run, no CSV written")
        return 0

    # Write back to CSV preserving all other columns.
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[acceptance_type] wrote updated CSV: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
