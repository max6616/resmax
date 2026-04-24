#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR / "accepted_index_builder"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# Auto-load .secrets/*.env so OPENALEX_API_KEY etc. are available to fetchers.
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
import secrets_loader  # noqa: E402,F401

from accepted_index_builder.fetchers import (
    fetch_aaai_ojs_all_issues,
    fetch_acmmm_vue_accepted_chunk,
    fetch_anthropic_research,
    fetch_hf_daily_papers,
    fetch_json,
    fetch_openalex_works,
    fetch_openreview_api_v2,
    fetch_s2_bulk_search,
    fetch_text,
)
from accepted_index_builder.merge import dedup_against_peer_reviewed, load_existing_records, merge_records, write_csv
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


def _parse_kv_args(raw: str | None) -> dict[str, str]:
    """Parse 'key=val,key2=val2' from source.parser_args."""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def fetch_and_parse(source: SourceConfig, conf: ConferenceYearConfig, fixtures_dir: Path) -> list[AcceptedPaperRecord]:
    if source.kind == "s2_bulk_search":
        kv = _parse_kv_args(source.parser_args)
        year = int(kv.get("year", str(conf.year)))
        raw_cite = kv.get("minCitationCount", "auto")
        if raw_cite == "auto":
            from datetime import date as _date
            months_elapsed = (_date.today().year - year) * 12 + _date.today().month
            min_cite = max(10, int(100 * months_elapsed / 24))
            print(f"  [S2-bulk] auto threshold: year={year}, months={months_elapsed}, minCite={min_cite}")
        else:
            min_cite = int(raw_cite)
        papers = fetch_s2_bulk_search(year=year, min_citation_count=min_cite)
        return parse_payload(papers, conf, source)
    if source.kind == "hf_daily_papers_api":
        kv = _parse_kv_args(source.parser_args)
        year = int(kv.get("year", str(conf.year)))
        min_upvotes = int(kv.get("minUpvotes", "30"))
        papers = fetch_hf_daily_papers(year=year, min_upvotes=min_upvotes)
        return parse_payload(papers, conf, source)
    if source.kind == "anthropic_sitemap":
        year = conf.year
        articles = fetch_anthropic_research(year=year)
        return parse_payload(articles, conf, source)
    if source.kind == "anthropic_sitemap_cached":
        year = conf.year
        cache_key = "_anthropic_cache"
        if not hasattr(fetch_and_parse, cache_key):
            all_articles = fetch_anthropic_research(year=None)
            setattr(fetch_and_parse, cache_key, all_articles)
        cached = getattr(fetch_and_parse, cache_key)
        year_articles = [a for a in cached if a.get("year") == year]
        print(f"  [anthropic-cached] {len(year_articles)} articles for year={year} (from {len(cached)} total)")
        return parse_payload(year_articles, conf, source)
    if source.kind == "openalex_api":
        source_id = source.url
        year = int(source.parser_args) if source.parser_args else conf.year
        works = fetch_openalex_works(source_id, year)
        return parse_payload(works, conf, source)
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
    if source.kind == "acmmm_vue_accepted":
        chunk_name = (source.parser_args or "chunk-240a60f6").strip()
        chunk_js = fetch_acmmm_vue_accepted_chunk(source.url.rstrip("/"), chunk_name)
        return parse_payload(chunk_js, conf, source)
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

    import time
    print(f"[build] loading existing CSV ...", flush=True)
    t0 = time.time()
    existing_records = load_existing_records(out_path)
    print(f"[build] loaded {len(existing_records)} existing records in {time.time()-t0:.1f}s", flush=True)
    print(f"[build] {len(selected)} conf-years to process", flush=True)

    final_records: list[AcceptedPaperRecord] = []
    report_sections: list[dict] = []

    for idx, conf in enumerate(selected, 1):
        if conf.status == "skip":
            print(f"[{idx}/{len(selected)}] {conf.conf_year}: SKIP ({conf.skip_reason})", flush=True)
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
        print(f"[{idx}/{len(selected)}] {conf.conf_year}: fetching primary ({conf.primary_source.kind}) ...", flush=True)
        t1 = time.time()
        try:
            primary_records = fetch_and_parse(conf.primary_source, conf, fixtures_dir)
            print(f"  primary: {len(primary_records)} records in {time.time()-t1:.1f}s", flush=True)
        except Exception as exc:
            primary_records = []
            errors.append(f"primary source failed: {exc}")
            print(f"  primary FAILED in {time.time()-t1:.1f}s: {exc}", flush=True)

        auxiliary_records: list[AcceptedPaperRecord] = []
        for si, source in enumerate(conf.auxiliary_sources):
            print(f"  auxiliary[{si}] ({source.kind}) ...", flush=True)
            t2 = time.time()
            try:
                recs = fetch_and_parse(source, conf, fixtures_dir)
                auxiliary_records.extend(recs)
                print(f"  auxiliary[{si}]: {len(recs)} records in {time.time()-t2:.1f}s", flush=True)
            except Exception as exc:
                errors.append(f"auxiliary source failed ({source.url}): {exc}")
                print(f"  auxiliary[{si}] FAILED in {time.time()-t2:.1f}s: {exc}", flush=True)

        merged_records = merge_records(primary_records, auxiliary_records, existing_records)

        # Safety: if fetch failed and returned 0 records, preserve existing data
        if not merged_records and errors:
            fallback = [r for r in existing_records if r.conf_year == conf.conf_year]
            if fallback:
                merged_records = fallback
                print(f"  ⚠ fetch failed, preserving {len(fallback)} existing records for {conf.conf_year}", flush=True)

        final_records.extend(merged_records)
        print(f"  merged: {len(merged_records)} records", flush=True)
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
    print(f"[build] preserving {len(preserved)} records from {len(set(r.conf_year for r in preserved))} unselected conf-years", flush=True)
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

    final_records = dedup_against_peer_reviewed(final_records)

    write_csv(out_path, final_records)
    write_report(report_path, report_sections)
    print(f"[OK] wrote CSV: {out_path}")
    print(f"[OK] wrote report: {report_path}")
    print(f"[OK] total records: {len(final_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
