#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR / "accepted_index_builder"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from accepted_index_builder.fetchers import fetch_json, fetch_openreview_api_v2, fetch_text, fetch_aaai_ojs_all_issues
from accepted_index_builder.merge import load_existing_records, merge_records, write_csv
from accepted_index_builder.models import AcceptedPaperRecord, ConferenceYearConfig, SourceConfig
from accepted_index_builder.parsers import parse_payload
from accepted_index_builder.registry import load_registry
from accepted_index_builder.report import write_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build accepted index from conference-year source registry.")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--venues", default="")
    parser.add_argument("--years", default="")
    parser.add_argument("--conf-years", dest="conf_years", default="")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def split_csv_arg(raw: str) -> set[str]:
    return {x.strip() for x in (raw or "").split(",") if x.strip()}


def should_include(conf: ConferenceYearConfig, venues: set[str], years: set[str], conf_years: set[str]) -> bool:
    if venues and conf.venue not in venues:
        return False
    if years and str(conf.year) not in years:
        return False
    if conf_years and conf.conf_year not in conf_years:
        return False
    return True


def fetch_and_parse(source: SourceConfig, conf: ConferenceYearConfig, fixtures_dir: Path) -> list[AcceptedPaperRecord]:
    if source.kind == "openreview_api_v2":
        group = source.url
        prefixes = [p.strip() for p in (source.parser_args or "").split(",") if p.strip()]
        if not prefixes:
            prefixes = [f"{conf.venue} {conf.year}"]
        payload = fetch_openreview_api_v2(group, prefixes)
        return parse_payload(payload, conf, source)
    if source.kind == "aaai_ojs_multi_issue":
        year_tag = source.parser_args or f"AAAI-{conf.year % 100}"
        combined_html = fetch_aaai_ojs_all_issues(source.url, year_tag)
        return parse_payload(combined_html, conf, source)
    if source.kind in ("openreview_api", "virtual_conference_json"):
        payload = fetch_json(source, fixtures_dir)
    else:
        payload = fetch_text(source, fixtures_dir)
    return parse_payload(payload, conf, source)


def main() -> int:
    args = parse_args()
    registry_path = Path(args.registry).resolve()
    out_path = Path(args.out).resolve()
    report_path = Path(args.report).resolve()
    skill_root = registry_path.parent.parent
    fixtures_dir = skill_root / "fixtures"

    venues = split_csv_arg(args.venues)
    years = split_csv_arg(args.years)
    conf_years = split_csv_arg(args.conf_years)

    configs = load_registry(registry_path)
    selected = [c for c in configs if should_include(c, venues, years, conf_years)]

    existing_records = load_existing_records(out_path)
    final_records: list[AcceptedPaperRecord] = []
    report_sections: list[dict] = []

    for conf in selected:
        if conf.status == "skip":
            report_sections.append({
                "conf_year": conf.conf_year,
                "status": "skip",
                "skip_reason": conf.skip_reason,
                "primary_records": 0,
                "auxiliary_records": 0,
                "merged_records": 0,
                "errors": [],
            })
            continue

        errors: list[str] = []
        try:
            primary_records = fetch_and_parse(conf.primary_source, conf, fixtures_dir)
        except Exception as exc:
            primary_records = []
            errors.append(f"primary source failed: {exc}")

        auxiliary_records: list[AcceptedPaperRecord] = []
        for source in conf.auxiliary_sources:
            try:
                auxiliary_records.extend(fetch_and_parse(source, conf, fixtures_dir))
            except Exception as exc:
                errors.append(f"auxiliary source failed ({source.url}): {exc}")

        merged_records = merge_records(primary_records, auxiliary_records, existing_records)
        final_records.extend(merged_records)
        report_sections.append({
            "conf_year": conf.conf_year,
            "status": "active" if not errors else "active_with_errors",
            "skip_reason": conf.skip_reason,
            "primary_url": conf.primary_source.url,
            "expected_count": conf.primary_source.expected_count,
            "primary_records": len(primary_records),
            "auxiliary_records": len(auxiliary_records),
            "merged_records": len(merged_records),
            "coverage_gap": (conf.primary_source.expected_count - len(primary_records)) if conf.primary_source.expected_count is not None else None,
            "errors": errors,
        })

    # Preserve records from conf_years not selected in this run
    selected_conf_years = {c.conf_year for c in selected}
    preserved = [r for r in existing_records if r.conf_year not in selected_conf_years]
    final_records = merge_records(final_records + preserved, [], existing_records)

    # Add preserved conf_years to report so it reflects the full CSV
    from collections import Counter
    preserved_counts = Counter(r.conf_year for r in preserved)
    for cy, count in sorted(preserved_counts.items()):
        report_sections.append({
            "conf_year": cy,
            "status": "preserved",
            "skip_reason": "",
            "primary_url": "",
            "expected_count": None,
            "primary_records": count,
            "auxiliary_records": 0,
            "merged_records": count,
            "errors": [],
        })
    report_sections.sort(key=lambda s: s["conf_year"])

    write_csv(out_path, final_records)
    write_report(report_path, report_sections)
    print(f"[OK] wrote CSV: {out_path}")
    print(f"[OK] wrote report: {report_path}")
    print(f"[OK] total records: {len(final_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
