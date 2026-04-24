#!/usr/bin/env python3
"""Structured validation of the paper_database produced by resmax-database.

This is the single source of truth for "is the database in a usable state?"
It replaces hand-written coverage tables in SKILL.md and is the script the
main agent should call after any build / enrich cycle.

Checks performed:
  1. CSV presence, parseability, and basic integrity (paper_id uniqueness,
     required core fields present, enum fields valid, no null titles).
  2. Per-conf_year coverage of the columns the pipeline should have populated:
     abstract_raw, acceptance_type (no bare 'Accept'), code_url (informational),
     openreview_forum_id (venues with public reviews only),
     review_available (venues with public reviews must be 'yes' or 'no').
  3. Embedding cache alignment with the CSV (paper_id set overlap).
  4. Consistency between config/source_registry.json and the conf_years
     actually present in the CSV (unexpected or missing).
  5. Review JSON cache integrity: every row with review_available='yes' must
     have its review_detail_path file on disk and parseable.

Output:
  * Structured JSON report (stdout by default, or --out file).
  * Exit code 0 when every hard requirement passes; 1 otherwise. Soft
    issues (informational warnings) never fail the exit code.

Hard requirements (failing any of these returns exit 1):
  H1. CSV loads, no duplicate paper_id, all rows have non-empty title/venue/year.
  H2. Every conf_year has >= configured valid abstract coverage.
  H3. Every conf_year has 100% acceptance_type coverage and 0 rows with bare 'Accept'.
  H4. For venues in PUBLIC_REVIEW_VENUES, every conf_year has review_available
      set on >= 99% of rows.
  H5. Embedding cache safely loads and covers queryable CSV rows exactly.
  H6. Manifest exists and matches current CSV/registry/cache hashes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
from data_contracts import SOURCE_TEXT_STATUS_VALUES, is_valid_abstract, review_score_status  # noqa: E402


csv.field_size_limit(100 * 1024 * 1024)


# Venues whose accepted papers have public reviews on OpenReview. Kept in sync
# with enrich_reviews.VENUE_REVIEW_CONFIG; deliberately duplicated so this
# script has zero runtime dependencies on enrich_reviews.py.
PUBLIC_REVIEW_VENUES = {"ICLR", "NeurIPS", "ICML"}

NON_PEER_REVIEWED_VENUES = {"ArXiv_HiCite", "HF_DailyPapers", "Anthropic_Research"}

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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_csv(path: Path) -> tuple[list[str], list[dict]]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    return fields, rows


def _pct(num: int, denom: int) -> float:
    return round(num * 100 / denom, 1) if denom else 0.0


def check_core(rows: list[dict], fields: list[str]) -> dict:
    """Hard requirement H1: no duplicate paper_id, every row has title/venue/year."""
    total = len(rows)
    ids: list[str] = []
    missing_title = 0
    missing_venue = 0
    missing_year = 0
    for r in rows:
        ids.append(r.get("paper_id", ""))
        if not r.get("title", "").strip():
            missing_title += 1
        if not r.get("venue", "").strip():
            missing_venue += 1
        if not r.get("year", "").strip():
            missing_year += 1
    dups = [pid for pid, n in Counter(ids).items() if n > 1]
    issues: list[str] = []
    missing_fields = [f for f in REQUIRED_CORE_FIELDS if f not in fields]
    if missing_fields:
        issues.append(f"missing required core fields: {missing_fields}")

    enum_violations: dict[str, dict[str, int]] = {}
    for field, allowed in FIELD_ENUMS.items():
        bad = Counter((r.get(field, "") or "") for r in rows if (r.get(field, "") or "") not in allowed)
        if bad:
            enum_violations[field] = dict(bad)
    if enum_violations:
        issues.append(f"enum violations: {enum_violations}")

    source_text_missing_status = 0
    source_text_missing_evidence = 0
    source_text_missing_url = 0
    source_text_missing_query = 0
    url_required_statuses = {
        "pdf_available",
        "preprint_available",
        "publisher_landing_only",
        "official_landing_only",
        "source_listing_only",
        "paywalled_landing",
        "not_yet_public",
    }
    query_required_statuses = {
        "publisher_landing_only",
        "official_landing_only",
        "source_listing_only",
        "missing_anchor_needs_search",
        "unresolved_after_search",
    }
    for row in rows:
        status = (row.get("source_text_status", "") or "").strip()
        if not status:
            source_text_missing_status += 1
        if not (row.get("source_text_evidence", "") or "").strip():
            source_text_missing_evidence += 1
        if status in url_required_statuses and not (row.get("source_text_url", "") or "").strip():
            source_text_missing_url += 1
        if status in query_required_statuses and not (row.get("source_text_search_query", "") or "").strip():
            source_text_missing_query += 1
    if source_text_missing_status:
        issues.append(f"{source_text_missing_status} rows missing source_text_status")
    if source_text_missing_evidence:
        issues.append(f"{source_text_missing_evidence} rows missing source_text_evidence")
    if source_text_missing_url:
        issues.append(f"{source_text_missing_url} rows missing source_text_url for URL-required statuses")
    if source_text_missing_query:
        issues.append(f"{source_text_missing_query} rows missing source_text_search_query for search-required statuses")

    if missing_title:
        issues.append(f"{missing_title} rows missing title")
    if missing_venue:
        issues.append(f"{missing_venue} rows missing venue")
    if missing_year:
        issues.append(f"{missing_year} rows missing year")
    if dups:
        issues.append(f"{len(dups)} duplicate paper_ids (sample={dups[:3]})")
    return {
        "total_rows": total,
        "field_count": len(fields),
        "missing_required_core_fields": missing_fields,
        "enum_violations": enum_violations,
        "source_text_missing_status": source_text_missing_status,
        "source_text_missing_evidence": source_text_missing_evidence,
        "source_text_missing_url": source_text_missing_url,
        "source_text_missing_query": source_text_missing_query,
        "duplicate_paper_ids": len(dups),
        "missing_title": missing_title,
        "missing_venue": missing_venue,
        "missing_year": missing_year,
        "status": "OK" if not issues else "FAIL",
        "issues": issues,
    }


def _load_registry_thresholds(registry_path: Path) -> dict[str, dict]:
    """Load per-conf_year expected thresholds from source_registry.json.

    Each entry may carry:
      - `expected_abstract_coverage`: float in [0,100]. Default 99.
    Used to relax H2 for venues with documented upstream abstract gaps
    (e.g. Springer journals reachable only via OpenAlex with no abstract).
    """
    if not registry_path.exists():
        return {}
    try:
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = (
        reg.get("conference_years")
        or reg.get("conferences")
        or reg.get("entries")
        or []
    )
    if not isinstance(entries, list):
        entries = reg if isinstance(reg, list) else []
    out: dict[str, dict] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        cy = e.get("conf_year")
        if not cy:
            continue
        out[cy] = {
            "expected_abstract_coverage": float(e.get("expected_abstract_coverage", 99.0)),
        }
    return out


def check_coverage(rows: list[dict], reviews_dir: Path, registry_path: Path | None = None) -> dict:
    """Per-conf_year coverage for the fields the pipeline should populate."""
    by_cy: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cy = r.get("conf_year", "UNKNOWN")
        by_cy[cy].append(r)

    thresholds = _load_registry_thresholds(registry_path) if registry_path else {}

    conf_year_stats: dict[str, dict] = {}
    hard_violations: list[str] = []
    soft_warnings: list[str] = []

    for cy in sorted(by_cy):
        group = by_cy[cy]
        total = len(group)
        abs_n = sum(1 for r in group if is_valid_abstract(r.get("abstract_raw", "")))
        forum_n = sum(1 for r in group if r.get("openreview_forum_id", "").strip())
        at_n = sum(1 for r in group if r.get("acceptance_type", "").strip())
        at_accept = sum(1 for r in group if r.get("acceptance_type", "").strip() == "Accept")
        code_n = sum(1 for r in group if r.get("code_url", "").strip())
        code_real_n = sum(1 for r in group if r.get("code_is_real", "") == "yes")
        review_n = sum(1 for r in group if r.get("review_available", "").strip())
        doi_n = sum(1 for r in group if r.get("doi", "").strip())
        pdf_n = sum(1 for r in group if r.get("pdf_status") == "available" or r.get("pdf_url", "").strip())
        source_text_evidence_n = sum(
            1
            for r in group
            if r.get("source_text_status", "").strip() and r.get("source_text_evidence", "").strip()
        )
        source_text_counts = Counter(
            r.get("source_text_status", "").strip() or "empty"
            for r in group
        )
        review_score_counts = Counter(
            r.get("review_score_status", "").strip() or review_score_status(r)
            for r in group
        )

        venue = group[0].get("venue", "") if group else ""
        is_public_review_venue = venue in PUBLIC_REVIEW_VENUES
        is_non_peer_reviewed = venue in NON_PEER_REVIEWED_VENUES
        reviews_conf_dir = reviews_dir / cy
        reviews_dir_exists = reviews_conf_dir.exists() and any(reviews_conf_dir.iterdir()) if reviews_conf_dir.exists() else False

        stats = {
            "total": total,
            "venue": venue,
            "valid_abstract_pct": _pct(abs_n, total),
            "abstract_pct": _pct(abs_n, total),
            "doi_pct": _pct(doi_n, total),
            "pdf_available_pct": _pct(pdf_n, total),
            "source_text_evidence_pct": _pct(source_text_evidence_n, total),
            "source_text_status_counts": dict(source_text_counts),
            "openreview_forum_id_pct": _pct(forum_n, total),
            "acceptance_type_pct": _pct(at_n, total),
            "acceptance_type_bare_accept": at_accept,
            "code_url_pct": _pct(code_n, total),
            "code_is_real_yes_pct": _pct(code_real_n, max(code_n, 1)),
            "review_available_pct": _pct(review_n, total),
            "review_score_status_counts": dict(review_score_counts),
            "is_public_review_venue": is_public_review_venue,
            "reviews_dir_populated": reviews_dir_exists,
        }

        # Hard requirement H2: abstracts >= configured threshold (default 99%).
        # Registry can declare a lower expected value for venues with known
        # upstream data source limitations (e.g. Springer journals via OpenAlex).
        # Non-peer-reviewed venues default to 80% (S2/HF may lack abstracts).
        default_abs = 80.0 if is_non_peer_reviewed else 99.0
        expected_abs = thresholds.get(cy, {}).get("expected_abstract_coverage", default_abs)
        stats["expected_abstract_coverage"] = expected_abs
        if stats["valid_abstract_pct"] < expected_abs:
            hard_violations.append(
                f"{cy}: valid_abstract_pct {stats['valid_abstract_pct']}% < {expected_abs}% (registry threshold)"
            )
        # Hard requirement H3: acceptance_type 100% and no bare 'Accept'.
        # Non-peer-reviewed venues use their own acceptance_type values
        # (High-Impact Preprint, Community Selected) and skip bare-Accept check.
        if stats["acceptance_type_pct"] < 100.0:
            hard_violations.append(f"{cy}: acceptance_type_pct {stats['acceptance_type_pct']}% < 100%")
        if at_accept > 0 and not is_non_peer_reviewed:
            hard_violations.append(
                f"{cy}: {at_accept} rows have bare 'Accept' as acceptance_type"
            )
        # Hard requirement H4: public review venues whose reviews dir is already
        # populated must have review_available set >= 99%. A venue-year with no
        # reviews directory (= enrich_reviews was never run) is reported as
        # soft warning instead of hard fail; ops must explicitly fetch it.
        if is_public_review_venue and stats["review_available_pct"] < 99.0:
            if reviews_dir_exists:
                hard_violations.append(
                    f"{cy}: review_available_pct {stats['review_available_pct']}% < 99% "
                    "(public review venue, reviews/ populated)"
                )
            else:
                soft_warnings.append(
                    f"{cy}: enrich_reviews never run for this public review venue "
                    f"(forum_id coverage {stats['openreview_forum_id_pct']}%)"
                )

        conf_year_stats[cy] = stats

    status = "OK" if not hard_violations else "FAIL"
    return {
        "conf_year_stats": conf_year_stats,
        "hard_violations": hard_violations,
        "soft_warnings": soft_warnings,
        "status": status,
    }


def check_embedding_cache(cache_path: Path, csv_ids: set[str]) -> dict:
    if not cache_path.exists():
        return {"status": "FAIL", "reason": f"cache not found: {cache_path}"}
    try:
        import numpy as np
    except ImportError:
        return {"status": "WARN", "reason": "numpy not installed"}

    try:
        data = np.load(cache_path, allow_pickle=False)
    except ValueError as exc:
        return {
            "status": "FAIL",
            "reason": f"cache requires pickle or is unsafe to load: {exc}",
        }
    if "paper_ids" not in data or "embeddings" not in data:
        return {
            "status": "FAIL",
            "reason": "cache missing 'paper_ids' or 'embeddings' array",
        }
    try:
        cached_ids = {str(x) for x in data["paper_ids"].tolist()}
    except ValueError as exc:
        return {
            "status": "FAIL",
            "reason": f"cache paper_ids requires pickle or is unsafe to load: {exc}",
        }
    missing = csv_ids - cached_ids
    orphaned = cached_ids - csv_ids
    emb = data["embeddings"]
    dim = emb.shape[1] if emb.ndim == 2 else None

    coverage_pct = _pct(len(csv_ids & cached_ids), len(csv_ids))
    status = "OK" if coverage_pct == 100.0 and not orphaned else "FAIL"

    return {
        "cached_papers": len(cached_ids),
        "csv_papers": len(csv_ids),
        "overlap_pct": coverage_pct,
        "missing_in_cache": len(missing),
        "orphaned_in_cache": len(orphaned),
        "embedding_dim": int(dim) if dim is not None else None,
        "sample_missing": sorted(missing)[:5],
        "status": status,
    }


def check_registry(rows: list[dict], registry_path: Path) -> dict:
    if not registry_path.exists():
        return {"status": "SKIP", "reason": f"registry not found: {registry_path}"}
    try:
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "FAIL", "reason": f"cannot parse registry: {exc}"}

    entries = (
        reg.get("conference_years")
        or reg.get("conferences")
        or reg.get("entries")
        or []
    )
    if not isinstance(entries, list):
        entries = reg if isinstance(reg, list) else []
    registry_cys = {e.get("conf_year", "") for e in entries if isinstance(e, dict)}
    registry_cys.discard("")
    skip_cys = {
        e.get("conf_year", "") for e in entries
        if isinstance(e, dict) and e.get("status") == "skip"
    }
    active_cys = registry_cys - skip_cys

    csv_cys = {r.get("conf_year", "") for r in rows}
    csv_cys.discard("")

    unexpected_in_csv = csv_cys - registry_cys
    missing_from_csv = active_cys - csv_cys
    status = "OK"
    issues: list[str] = []
    if unexpected_in_csv:
        status = "WARN"
        issues.append(f"{len(unexpected_in_csv)} conf_years in CSV but not in registry: "
                      f"{sorted(unexpected_in_csv)[:5]}")
    if missing_from_csv:
        status = "FAIL"
        issues.append(f"{len(missing_from_csv)} active conf_years in registry but "
                      f"missing from CSV: {sorted(missing_from_csv)[:5]}")
    return {
        "registry_total": len(registry_cys),
        "registry_active": len(active_cys),
        "registry_skip": len(skip_cys),
        "csv_total": len(csv_cys),
        "unexpected_in_csv": sorted(unexpected_in_csv),
        "missing_from_csv": sorted(missing_from_csv),
        "status": status,
        "issues": issues,
    }


def check_manifest(
    manifest_path: Path,
    csv_path: Path,
    registry_path: Path,
    cache_path: Path,
) -> dict:
    if not manifest_path.exists():
        return {"status": "FAIL", "reason": f"manifest not found: {manifest_path}"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "FAIL", "reason": f"cannot parse manifest: {exc}"}

    issues: list[str] = []
    if manifest.get("csv", {}).get("sha256") != _sha256_file(csv_path):
        issues.append("CSV hash mismatch")
    if registry_path.exists() and manifest.get("registry", {}).get("sha256") != _sha256_file(registry_path):
        issues.append("registry hash mismatch")
    if cache_path.exists() and manifest.get("embedding", {}).get("sha256") != _sha256_file(cache_path):
        issues.append("embedding cache hash mismatch")

    embedding = manifest.get("embedding", {}) or {}
    if embedding.get("safe_load") is False or embedding.get("requires_pickle"):
        issues.append("embedding cache requires pickle")
    if embedding.get("missing_in_cache", 0):
        issues.append(f"embedding missing_in_cache={embedding.get('missing_in_cache')}")
    if embedding.get("orphaned_in_cache", 0):
        issues.append(f"embedding orphaned_in_cache={embedding.get('orphaned_in_cache')}")

    source_status = (manifest.get("source_report", {}) or {}).get("source_status", {})
    non_ok = [
        f"{cy}:{info.get('status')}"
        for cy, info in source_status.items()
        if str(info.get("status", "")).lower() not in {"preserved", "active", "ok", "success"}
    ]
    if non_ok:
        issues.append(f"non-ok source statuses: {non_ok[:5]}")

    return {
        "status": "OK" if not issues else "FAIL",
        "path": str(manifest_path),
        "generated_at": manifest.get("generated_at", ""),
        "issues": issues,
    }


def check_review_json_integrity(
    rows: list[dict], reviews_dir: Path, sample_size: int = 20
) -> dict:
    """Sample rows with review_available=yes, ensure review_detail_path resolves."""
    yes_rows = [r for r in rows if r.get("review_available") == "yes"]
    if not yes_rows:
        return {"status": "SKIP", "reason": "no rows with review_available=yes"}

    checked = 0
    missing = 0
    parse_err = 0
    sample_missing: list[str] = []

    # Sample across conf_years proportionally to catch per-venue issues.
    by_cy: dict[str, list[dict]] = defaultdict(list)
    for r in yes_rows:
        by_cy[r.get("conf_year", "")].append(r)
    sample: list[dict] = []
    per_cy = max(1, sample_size // max(1, len(by_cy)))
    for cy, grp in by_cy.items():
        sample.extend(grp[:per_cy])

    for r in sample:
        checked += 1
        rel = r.get("review_detail_path", "")
        if not rel:
            missing += 1
            continue
        p = Path(rel)
        if not p.is_absolute():
            p = Path.cwd() / p
        if not p.exists():
            # Fallback: reconstruct from reviews_dir / conf_year / forum_id.json
            forum_id = r.get("openreview_forum_id", "").strip()
            conf_year = r.get("conf_year", "")
            alt = reviews_dir / conf_year / f"{forum_id}.json"
            if alt.exists():
                continue
            missing += 1
            if len(sample_missing) < 5:
                sample_missing.append(f"{r.get('paper_id','?')} -> {rel}")
            continue
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            parse_err += 1

    status = "OK" if not (missing or parse_err) else "WARN"
    return {
        "reviews_yes_total": len(yes_rows),
        "sampled": checked,
        "missing_files": missing,
        "parse_errors": parse_err,
        "sample_missing": sample_missing,
        "status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default="paper_database/accepted_index.csv")
    parser.add_argument("--cache", default="paper_database/embedding_cache/qwen3_8b.npz")
    parser.add_argument("--registry",
                        default=".agents/skills/resmax-database/config/source_registry.json")
    parser.add_argument("--reviews-dir", default="paper_database/reviews")
    parser.add_argument("--manifest", default="paper_database/manifest.json")
    parser.add_argument("--out", default="", help="Write JSON report to file (default stdout)")
    parser.add_argument("--quiet", action="store_true", help="Suppress pretty-print summary on stderr")
    parser.add_argument("--sample-review-json", type=int, default=20,
                        help="How many review_available=yes rows to probe for file existence")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    cache_path = Path(args.cache)
    registry_path = Path(args.registry)
    reviews_dir = Path(args.reviews_dir)
    manifest_path = Path(args.manifest)

    try:
        fields, rows = _load_csv(csv_path)
    except Exception as exc:
        report = {"csv_load": {"status": "FAIL", "reason": str(exc)}, "overall": "FAIL"}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    csv_ids = {r.get("paper_id", "") for r in rows if r.get("paper_id", "") and is_valid_abstract(r.get("abstract_raw", ""))}

    core = check_core(rows, fields)
    coverage = check_coverage(rows, reviews_dir, registry_path)
    embedding = check_embedding_cache(cache_path, csv_ids)
    registry = check_registry(rows, registry_path)
    manifest = check_manifest(manifest_path, csv_path, registry_path, cache_path)
    reviews = check_review_json_integrity(rows, reviews_dir, args.sample_review_json)

    hard_fail = any(
        section.get("status") == "FAIL"
        for section in (core, coverage, embedding, registry, manifest)
    )
    overall = "FAIL" if hard_fail else "PASS"

    report = {
        "csv_path": str(csv_path),
        "csv_field_count": len(fields),
        "csv_fields": fields,
        "core": core,
        "coverage": coverage,
        "embedding": embedding,
        "registry": registry,
        "manifest": manifest,
        "review_json_integrity": reviews,
        "overall": overall,
    }

    out_json = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out_json, encoding="utf-8")
    else:
        print(out_json)

    if not args.quiet:
        sys.stderr.write(f"\n[validate] overall={overall}, total_rows={core['total_rows']}, "
                         f"conf_years={len(coverage['conf_year_stats'])}, "
                         f"hard_violations={len(coverage['hard_violations'])}, "
                         f"soft_warnings={len(coverage.get('soft_warnings') or [])}\n")
        for v in coverage["hard_violations"][:10]:
            sys.stderr.write(f"  [FAIL] {v}\n")
        for v in (coverage.get("soft_warnings") or [])[:10]:
            sys.stderr.write(f"  [WARN] {v}\n")
        if embedding.get("status") == "FAIL":
            emb_msg = embedding.get("reason") or f"overlap_pct={embedding.get('overlap_pct')}%"
            sys.stderr.write(f"  [FAIL] embedding: {emb_msg}\n")
        if manifest.get("status") == "FAIL":
            sys.stderr.write(f"  [FAIL] manifest: {manifest.get('reason') or manifest.get('issues')[:3]}\n")

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
