#!/usr/bin/env python3
"""Audit accepted_index field completeness and DOI/PDF gap causes."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import sys

_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
from data_contracts import SOURCE_TEXT_STATUS_VALUES, derive_pdf_contract, is_pdf_like_url, normalize_http_url  # noqa: E402


REQUIRED_CORE_FIELDS = [
    "paper_id",
    "short_id",
    "venue",
    "year",
    "conf_year",
    "title",
    "authors",
    "source_type",
    "source_url",
    "paper_link",
    "landing_url",
    "pdf_url",
    "pdf_status",
    "pdf_source",
    "source_text_status",
    "source_text_url",
    "source_text_source",
    "source_text_evidence",
    "source_text_search_query",
    "source_text_checked_at",
    "abstract_raw",
    "abstract_status",
    "doi",
    "openreview_forum_id",
    "has_pdf_camera_ready",
    "acceptance_type",
    "review_available",
    "review_score_status",
    "code_url",
]

FIELD_ENUMS = {
    "pdf_status": {"available", "missing_unresolved", ""},
    "pdf_source": {
        "pdf_url",
        "arxiv_id",
        "openreview_forum_id",
        "cvf_html",
        "acl_anthology",
        "paper_link",
        "none",
        "",
    },
    "has_pdf_camera_ready": {"yes", "no", ""},
    "abstract_status": {"ok", "missing", "short", "placeholder", ""},
    "review_score_status": {
        "complete",
        "no_scores",
        "no_reviews",
        "unavailable",
        "partial",
        "unknown",
        "",
    },
    "source_text_status": SOURCE_TEXT_STATUS_VALUES,
}

NON_PEER_REVIEWED_VENUES = {"ArXiv_HiCite", "HF_DailyPapers", "Anthropic_Research"}
URL_FIELDS = ["paper_link", "landing_url", "paper_url", "full_paper_url", "arxiv_url", "sourceurl", "source_url"]


def _filled(raw: str | None) -> bool:
    return bool((raw or "").strip())


def _pct(num: int, denom: int) -> float:
    return round(num * 100 / denom, 2) if denom else 0.0


def _venue_key(row: dict[str, str]) -> str:
    return row.get("conf_year") or f"{row.get('venue', '')}_{row.get('year', '')}"


def _load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    csv.field_size_limit(100 * 1024 * 1024)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _first_pdf_candidate(row: dict[str, str]) -> tuple[str, str]:
    contract = derive_pdf_contract(row)
    if _filled(contract.pdf_url):
        return "shared_contract", contract.pdf_url
    for field in URL_FIELDS:
        url = (row.get(field, "") or "").strip()
        if url and is_pdf_like_url(url):
            return field, normalize_http_url(url) or url
    return "", ""


def _doi_cause(row: dict[str, str]) -> str:
    source_type = row.get("source_type", "")
    if source_type == "virtual_conference_json":
        return "source_lacks_doi_virtual_conference_json"
    if source_type == "acl_anthology_html":
        return "acl_anthology_doi_not_extracted_or_verified"
    if source_type in {"cvpr_openaccess_html", "kesen_siggraph_html"}:
        return "publisher_site_source_has_pdf_but_no_doi_extraction"
    if source_type in {"aaai_ojs_multi_issue", "kdd_html", "jmlr_html", "acmmm_html", "acmmm_vue_accepted"}:
        return "venue_parser_doi_not_extracted_or_listing_lacks_doi"
    if source_type in {"s2_bulk_search", "hf_daily_papers_api", "anthropic_sitemap", "anthropic_sitemap_cached"}:
        return "non_proceedings_or_api_source_without_doi_contract"
    if source_type == "openalex_api":
        return "openalex_record_without_doi"
    return "unknown_local_evidence"


def _pdf_cause(row: dict[str, str]) -> str:
    source_type = row.get("source_type", "")
    candidate_kind, _ = _first_pdf_candidate(row)
    if candidate_kind:
        return "recoverable_from_existing_fields"
    if source_type == "virtual_conference_json":
        return "source_lacks_pdf_virtual_conference_json_no_publication_join"
    if source_type in {"openalex_api", "s2_bulk_search", "hf_daily_papers_api", "anthropic_sitemap", "anthropic_sitemap_cached"}:
        return "metadata_api_or_curated_source_without_direct_pdf"
    if source_type in {"acmmm_html", "acmmm_vue_accepted", "aaai_ojs_multi_issue", "kdd_html", "kesen_siggraph_html", "jmlr_html"}:
        return "parser_did_not_extract_pdf_or_source_listing_lacks_pdf"
    return "unknown_local_evidence"


def _field_stats(rows: list[dict[str, str]], fields: list[str]) -> list[dict]:
    total = len(rows)
    stats = []
    for field in fields:
        non_empty = sum(1 for row in rows if _filled(row.get(field, "")))
        stats.append({
            "field": field,
            "non_empty": non_empty,
            "empty": total - non_empty,
            "non_empty_pct": _pct(non_empty, total),
        })
    return stats


def _enum_violations(rows: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    out = {}
    for field, allowed in FIELD_ENUMS.items():
        bad = Counter((row.get(field, "") or "") for row in rows if (row.get(field, "") or "") not in allowed)
        if bad:
            out[field] = dict(bad)
    return out


def _coverage(rows: list[dict[str, str]]) -> dict[str, float | int]:
    total = len(rows)
    doi = sum(1 for row in rows if _filled(row.get("doi", "")))
    pdf = sum(
        1
        for row in rows
        if _filled(row.get("pdf_url", "")) and row.get("pdf_status") == "available"
    )
    source_text_evidence = sum(
        1
        for row in rows
        if _filled(row.get("source_text_status", "")) and _filled(row.get("source_text_evidence", ""))
    )
    return {
        "rows": total,
        "doi": doi,
        "doi_pct": _pct(doi, total),
        "pdf": pdf,
        "pdf_pct": _pct(pdf, total),
        "source_text_evidence": source_text_evidence,
        "source_text_evidence_pct": _pct(source_text_evidence, total),
    }


def _per_conf(rows: list[dict[str, str]]) -> list[dict]:
    by_conf: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_conf[_venue_key(row)].append(row)
    out = []
    for conf_year, group in sorted(by_conf.items()):
        total = len(group)
        doi = sum(1 for row in group if _filled(row.get("doi", "")))
        pdf = sum(1 for row in group if _filled(row.get("pdf_url", "")) and row.get("pdf_status") == "available")
        out.append({
            "conf_year": conf_year,
            "venue": group[0].get("venue", ""),
            "year": group[0].get("year", ""),
            "total": total,
            "doi_missing": total - doi,
            "doi_pct": _pct(doi, total),
            "pdf_missing": total - pdf,
            "pdf_pct": _pct(pdf, total),
            "source_types": dict(Counter(row.get("source_type", "") for row in group).most_common()),
        })
    return out


def build_report(rows: list[dict[str, str]], fields: list[str]) -> dict:
    doi_missing = [row for row in rows if not _filled(row.get("doi", ""))]
    pdf_missing = [
        row
        for row in rows
        if not _filled(row.get("pdf_url", "")) or row.get("pdf_status") != "available"
    ]
    peer_reviewed = [row for row in rows if row.get("venue", "") not in NON_PEER_REVIEWED_VENUES]

    latent_pdf = Counter()
    latent_pdf_by_source = Counter()
    for row in pdf_missing:
        kind, _ = _first_pdf_candidate(row)
        if kind:
            latent_pdf[kind] += 1
            latent_pdf_by_source[(row.get("source_type", ""), kind)] += 1

    per_conf = _per_conf(rows)
    return {
        "csv": {
            "rows": len(rows),
            "field_count": len(fields),
            "fields": fields,
            "missing_required_core_fields": [field for field in REQUIRED_CORE_FIELDS if field not in fields],
        },
        "field_stats": _field_stats(rows, fields),
        "enum_violations": _enum_violations(rows),
        "coverage": {
            "all": _coverage(rows),
            "peer_reviewed_only": _coverage(peer_reviewed),
        },
        "doi": {
            "missing": len(doi_missing),
            "missing_by_venue": dict(Counter(row.get("venue", "") for row in doi_missing).most_common()),
            "missing_by_source_type": dict(Counter(row.get("source_type", "") for row in doi_missing).most_common()),
            "cause_counts": dict(Counter(_doi_cause(row) for row in doi_missing).most_common()),
        },
        "pdf_url": {
            "missing": len(pdf_missing),
            "missing_by_venue": dict(Counter(row.get("venue", "") for row in pdf_missing).most_common()),
            "missing_by_source_type": dict(Counter(row.get("source_type", "") for row in pdf_missing).most_common()),
            "cause_counts": dict(Counter(_pdf_cause(row) for row in pdf_missing).most_common()),
            "latent_recoverable_counts": dict(latent_pdf.most_common()),
            "latent_recoverable_by_source_type": {
                f"{key[0]}::{key[1]}": value for key, value in latent_pdf_by_source.most_common()
            },
        },
        "source_text": {
            "status_counts": dict(Counter(row.get("source_text_status", "") or "empty" for row in rows).most_common()),
            "needs_web_search": sum(
                1
                for row in rows
                if row.get("source_text_status", "") in {
                    "publisher_landing_only",
                    "official_landing_only",
                    "source_listing_only",
                    "missing_anchor_needs_search",
                    "unresolved_after_search",
                }
            ),
        },
        "per_conf_year": per_conf,
        "worst_doi_conf_years": sorted(per_conf, key=lambda item: (-item["doi_missing"], item["doi_pct"]))[:25],
        "worst_pdf_conf_years": sorted(per_conf, key=lambda item: (-item["pdf_missing"], item["pdf_pct"]))[:25],
    }


def write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# Resmax Field / DOI / PDF Coverage Audit",
        "",
        f"- Rows: {report['csv']['rows']}",
        f"- Fields: {report['csv']['field_count']}",
        f"- Missing required core fields: {report['csv']['missing_required_core_fields'] or 'none'}",
        f"- Enum violations: {report['enum_violations'] or 'none'}",
        "",
        "## Coverage",
    ]
    for name, stats in report["coverage"].items():
        lines.append(
            f"- {name}: DOI {stats['doi']}/{stats['rows']} ({stats['doi_pct']}%), "
            f"PDF {stats['pdf']}/{stats['rows']} ({stats['pdf_pct']}%), "
            f"source-text evidence {stats['source_text_evidence']}/{stats['rows']} "
            f"({stats['source_text_evidence_pct']}%)"
        )

    lines.extend(["", "## Source Text Status"])
    for status, count in report["source_text"]["status_counts"].items():
        lines.append(f"- {status}: {count}")
    lines.append(f"- needs web search / upgrade: {report['source_text']['needs_web_search']}")

    lines.extend(["", "## Field Completeness: Lowest 25"])
    for item in sorted(report["field_stats"], key=lambda row: row["non_empty_pct"])[:25]:
        lines.append(f"- {item['field']}: {item['non_empty']}/{report['csv']['rows']} ({item['non_empty_pct']}%)")

    lines.extend(["", "## DOI Gap Causes"])
    for cause, count in report["doi"]["cause_counts"].items():
        lines.append(f"- {cause}: {count}")

    lines.extend(["", "## PDF Gap Causes"])
    for cause, count in report["pdf_url"]["cause_counts"].items():
        lines.append(f"- {cause}: {count}")
    lines.append("- locally recoverable candidates:")
    for kind, count in report["pdf_url"]["latent_recoverable_counts"].items():
        lines.append(f"  - {kind}: {count}")

    lines.extend(["", "## Worst DOI conf_years"])
    for item in report["worst_doi_conf_years"][:20]:
        lines.append(
            f"- {item['conf_year']}: missing {item['doi_missing']}/{item['total']} "
            f"(coverage {item['doi_pct']}%), source={item['source_types']}"
        )

    lines.extend(["", "## Worst PDF conf_years"])
    for item in report["worst_pdf_conf_years"][:20]:
        lines.append(
            f"- {item['conf_year']}: missing {item['pdf_missing']}/{item['total']} "
            f"(coverage {item['pdf_pct']}%), source={item['source_types']}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="paper_database/accepted_index.csv")
    parser.add_argument("--json-out", default="/tmp/resmax_field_coverage_audit.json")
    parser.add_argument("--md-out", default="/tmp/resmax_doi_pdf_gap_report.md")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fields, rows = _load_csv(Path(args.csv))
    report = build_report(rows, fields)
    Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, Path(args.md_out))
    print(json.dumps({
        "rows": report["csv"]["rows"],
        "fields": report["csv"]["field_count"],
        "missing_required_core_fields": report["csv"]["missing_required_core_fields"],
        "enum_violations": report["enum_violations"],
        "coverage": report["coverage"],
        "json_out": args.json_out,
        "md_out": args.md_out,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
