from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "0.1.0"
REQUIRED_DIRS = ("inputs", "normalized", "audit", "retrieval", "sources", "assets", "downstream", "validation")
REQUIRED_FILES = (
    "survey_report.md",
    "manifest.json",
    "inputs/input_manifest.json",
    "inputs/external_report.md",
    "inputs/seed_papers.csv",
    "inputs/seed_claims.jsonl",
    "inputs/seed_gaps.jsonl",
    "inputs/seed_ideas.jsonl",
    "normalized/normalized_inputs.json",
    "normalized/provenance_spans.jsonl",
    "normalized/seed_papers.normalized.jsonl",
    "normalized/seed_claims.normalized.jsonl",
    "normalized/seed_gaps.normalized.jsonl",
    "normalized/seed_ideas.normalized.jsonl",
    "normalized/parse_errors.jsonl",
    "audit/paper_audit.csv",
    "audit/paper_identity_map.jsonl",
    "audit/verified_paper_set.jsonl",
    "audit/external_only_papers.jsonl",
    "audit/uncertain_papers.jsonl",
    "audit/dropped_papers.jsonl",
    "audit/audit_summary.json",
    "retrieval/retrieval_requests.jsonl",
    "retrieval/retrieval_trace.jsonl",
    "retrieval/closest_work_candidates.jsonl",
    "retrieval/falsification_checks.jsonl",
    "retrieval/infra_search_results.jsonl",
    "retrieval/followup_queries.jsonl",
    "sources/source_manifest.jsonl",
    "sources/source_materialization_report.json",
    "sources/missing_sources.jsonl",
    "assets/paper_assets.jsonl",
    "assets/asset_mentions.jsonl",
    "assets/evidence_cards.jsonl",
    "assets/claim_graph.json",
    "assets/gap_map.jsonl",
    "assets/asset_stats.csv",
    "assets/falsification_summary.csv",
    "assets/missing_evidence.jsonl",
    "downstream/survey_contract.json",
    "downstream/research_pack_compat/manifest.json",
    "downstream/research_pack_compat/evidence_cards.jsonl",
    "downstream/research_pack_compat/claim_graph.json",
    "downstream/research_pack_compat/gap_map.json",
    "downstream/research_pack_compat/closest_work_candidates.jsonl",
    "downstream/research_pack_compat/missing_evidence.jsonl",
)
RETRIEVAL_MODES = {
    "seed-list verifier",
    "local omission checker",
    "closest-work search",
    "claim falsifier",
    "gap falsifier",
    "infra search",
    "follow-up query suggester",
}
BOUNDED_REQUEST_MODES = {
    "seed-list verifier",
    "local omission checker",
    "closest-work search",
    "infra search",
}
HARDCODE_PATTERNS = (
    r"\b4dgs\b",
    r"\b3dgs\b",
    r"gaussian\s+splatting",
    r"dynamic\s+gaussian",
    r"temporal\s+action",
)
GENERIC_CODE_FILES = (
    ".agents/skills/resmax-survey/scripts/survey_normalizer.py",
    ".agents/skills/resmax-survey/scripts/resmax_survey_v2/compile_spec.py",
    ".agents/skills/resmax-survey/scripts/resmax_survey_v2/retrieve_macro.py",
    ".agents/skills/resmax-survey/scripts/resmax_survey_v2/phase3_pack.py",
    ".agents/skills/resmax-survey/scripts/resmax_survey_v2/plan_queries.py",
    ".agents/skills/resmax-survey/scripts/resmax_survey_v2/cluster_subdirections.py",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a normalized Resmax survey run.")
    subparsers = parser.add_subparsers(dest="command")
    validate = subparsers.add_parser("validate", help="Validate a normalized survey directory.")
    validate.add_argument("--dir", required=True, type=Path, help="literature_research/<topic> directory.")
    parser.add_argument("--dir", type=Path, default=None, help="Back-compat shortcut for validate --dir.")
    args = parser.parse_args(argv)
    target = args.dir if args.dir else getattr(args, "dir", None)
    if args.command in {None, "validate"} and target:
        report = validate_survey(target, write_reports=True)
        print(f"[normalized-survey-validator] status={report['status']} errors={len(report['errors'])} warnings={len(report['warnings'])}")
        return 0 if report["status"] == "PASS" else 1
    parser.print_help()
    return 2


def validate_survey(out_dir: Path, *, write_reports: bool = True) -> dict[str, Any]:
    out_dir = out_dir.resolve()
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}

    _check_layout(out_dir, errors)
    manifest = _load_json(out_dir / "manifest.json", errors, required=True)
    _check_single_main_report(out_dir, errors)
    _check_manifest(out_dir, manifest, errors, warnings)
    _check_jsonl_schema(out_dir, errors, warnings)
    _check_audit(out_dir, errors, warnings, metrics)
    _check_retrieval(out_dir, errors, warnings, metrics)
    _check_evidence_links(out_dir, errors, warnings)
    _check_missing_evidence(out_dir, errors, warnings, metrics)
    _check_downstream_contract(out_dir, errors, warnings)
    _check_report_links(out_dir, errors, warnings)
    _check_no_direction_hardcode(out_dir, errors, warnings)
    _check_no_unbounded_discovery(out_dir, errors, warnings)

    status = "PASS" if not errors else "FAIL"
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "checks": {
            "artifact_existence": not any(error["check"] == "artifact_existence" for error in errors),
            "schema_validity": not any(error["check"] == "schema_validity" for error in errors),
            "manifest_hash": not any(error["check"] == "manifest_hash" for error in errors),
            "provenance": not any(error["check"] == "provenance" for error in errors),
            "paper_audit_consistency": not any(error["check"] == "paper_audit_consistency" for error in errors),
            "retrieval_trace_coverage": not any(error["check"] == "retrieval_trace_coverage" for error in errors),
            "evidence_pointer_consistency": not any(error["check"] == "evidence_pointer_consistency" for error in errors),
            "missing_evidence_consistency": not any(error["check"] == "missing_evidence_consistency" for error in errors),
            "critical_claim_coverage": not any(error["check"] == "critical_claim_coverage" for error in errors),
            "gap_falsification_status": not any(error["check"] == "gap_falsification_status" for error in errors),
            "downstream_contract_completeness": not any(error["check"] == "downstream_contract_completeness" for error in errors),
            "survey_report_links": not any(error["check"] == "survey_report_links" for error in errors),
            "single_main_report": not any(error["check"] == "single_main_report" for error in errors),
            "absence_direction_hardcode": not any(error["check"] == "absence_direction_hardcode" for error in errors),
            "absence_unbounded_discovery": not any(error["check"] == "absence_unbounded_discovery" for error in errors),
        },
    }
    if write_reports:
        validation_dir = out_dir / "validation"
        validation_dir.mkdir(parents=True, exist_ok=True)
        _write_json(validation_dir / "validation_report.json", report)
        _write_text(validation_dir / "validation_report.md", _render_markdown(report))
    return report


def _check_layout(out_dir: Path, errors: list[dict[str, Any]]) -> None:
    for dirname in REQUIRED_DIRS:
        if not (out_dir / dirname).is_dir():
            _error(errors, "artifact_existence", f"missing required directory: {dirname}")
    for rel in REQUIRED_FILES:
        if not (out_dir / rel).is_file():
            _error(errors, "artifact_existence", f"missing required file: {rel}")


def _check_single_main_report(out_dir: Path, errors: list[dict[str, Any]]) -> None:
    top_markdown = sorted(path.name for path in out_dir.glob("*.md"))
    if top_markdown != ["survey_report.md"]:
        _error(errors, "single_main_report", f"top-level markdown files must be only survey_report.md, got {top_markdown}")


def _check_manifest(out_dir: Path, manifest: dict[str, Any], errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    required = {
        "schema_version",
        "run_id",
        "created_at",
        "topic",
        "producer",
        "inputs",
        "artifacts",
        "hashes",
        "database_snapshot",
        "embedding_cache_status",
        "review_cache_status",
        "source_cache_status",
        "coverage_summary",
        "retrieval_modes_run",
        "source_coverage",
        "provenance_summary",
        "degradation_summary",
        "validation_status",
        "downstream_contract_path",
    }
    missing = sorted(required - set(manifest))
    if missing:
        _error(errors, "schema_validity", f"manifest missing fields: {missing}")
    for rel, expected in (manifest.get("hashes") or {}).items():
        path = out_dir / rel
        if not path.exists():
            _error(errors, "manifest_hash", f"manifest hash references missing file: {rel}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            _error(errors, "manifest_hash", f"hash mismatch for {rel}: expected {expected}, got {actual}")
    if not (manifest.get("hashes") or {}):
        _error(errors, "manifest_hash", "manifest contains no artifact hashes")
    if manifest.get("validation_status") not in {"PASS", "FAIL", "NOT_RUN"}:
        _warning(warnings, "schema_validity", f"unexpected manifest validation_status={manifest.get('validation_status')}")


def _check_jsonl_schema(out_dir: Path, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    specs = {
        "assets/paper_assets.jsonl": {
            "paper_id",
            "canonical_title",
            "audit_status",
            "venue",
            "year",
            "source_status",
            "tasks",
            "problem_settings",
            "method_types",
            "base_models",
            "backbones",
            "datasets",
            "benchmarks",
            "metrics",
            "baselines",
            "experimental_protocols",
            "ablations",
            "compute_cost",
            "data_cost",
            "annotation_cost",
            "code_availability",
            "data_availability",
            "claimed_contributions",
            "limitations",
            "failure_cases",
            "reviewer_signals",
            "reuse_opportunities",
            "implementation_barriers",
            "missing_fields",
            "evidence_card_ids",
            "confidence",
            "provenance",
        },
        "assets/asset_mentions.jsonl": {
            "mention_id",
            "paper_id",
            "asset_type",
            "normalized_name",
            "surface_form",
            "role",
            "evidence_card_id",
            "confidence",
            "source_span",
            "provenance",
        },
        "assets/evidence_cards.jsonl": {
            "evidence_id",
            "paper_id",
            "source_id",
            "source_type",
            "locator",
            "quote_hash",
            "target_id",
            "target_type",
            "evidence_kind",
            "support_relation",
            "content_summary",
            "confidence",
            "extraction_method",
            "provenance",
        },
        "assets/gap_map.jsonl": {
            "gap_id",
            "text",
            "origin",
            "related_claim_ids",
            "supporting_evidence_ids",
            "falsification_status",
            "closest_work_ids",
            "infra_dependencies",
            "implementation_constraints",
            "reviewer_blockers",
            "confidence",
            "missing_evidence_ids",
            "downstream_ready",
        },
        "retrieval/closest_work_candidates.jsonl": {
            "candidate_id",
            "query_id",
            "target_type",
            "target_id",
            "paper_id",
            "rank",
            "retrieval_mode",
            "score",
            "match_reasons",
            "overlap_dimensions",
            "novelty_risk",
            "relation_to_target",
            "drop_reason",
            "evidence_ids",
            "trace_id",
            "confidence",
        },
        "assets/missing_evidence.jsonl": {
            "missing_id",
            "scope",
            "target_id",
            "field",
            "reason",
            "required_for",
            "severity",
            "allowed_degradation",
            "suggested_action",
            "status",
        },
    }
    for rel, required in specs.items():
        rows = _load_jsonl(out_dir / rel, errors, required=True)
        for idx, row in enumerate(rows, start=1):
            missing = sorted(required - set(row))
            if missing:
                _error(errors, "schema_validity", f"{rel}:{idx} missing fields: {missing}")
    claim_graph = _load_json(out_dir / "assets/claim_graph.json", errors, required=True)
    if not {"schema_version", "claims", "edges"}.issubset(claim_graph):
        _error(errors, "schema_validity", "claim_graph.json must contain schema_version, claims, edges")
    for idx, claim in enumerate(claim_graph.get("claims", []), start=1):
        required = {"claim_id", "text", "claim_type", "origin", "status", "paper_ids", "evidence_ids", "counter_evidence_ids", "confidence"}
        missing = sorted(required - set(claim))
        if missing:
            _error(errors, "schema_validity", f"claim_graph.claims[{idx}] missing fields: {missing}")
    _check_asset_stats(out_dir, errors)


def _check_asset_stats(out_dir: Path, errors: list[dict[str, Any]]) -> None:
    required = {
        "asset_type",
        "normalized_name",
        "count_papers",
        "verified_count",
        "venues",
        "years",
        "representative_papers",
        "evidence_count",
        "confidence",
        "notes",
    }
    path = out_dir / "assets/asset_stats.csv"
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            _error(errors, "schema_validity", f"asset_stats.csv missing fields: {missing}")


def _check_audit(out_dir: Path, errors: list[dict[str, Any]], warnings: list[dict[str, Any]], metrics: dict[str, Any]) -> None:
    with (out_dir / "audit/paper_audit.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    statuses = Counter(row.get("audit_status", "") for row in rows)
    summary = _load_json(out_dir / "audit/audit_summary.json", errors, required=True)
    expected = {
        "verified_local": summary.get("verified_local_count", 0),
        "external_only": summary.get("external_only_count", 0),
        "uncertain": summary.get("uncertain_count", 0),
        "dropped": summary.get("dropped_count", 0),
    }
    for status, count in expected.items():
        if statuses.get(status, 0) != int(count):
            _error(errors, "paper_audit_consistency", f"audit status count mismatch for {status}: csv={statuses.get(status, 0)} summary={count}")
    for idx, row in enumerate(rows, start=2):
        if row.get("audit_status") not in expected:
            _error(errors, "paper_audit_consistency", f"paper_audit.csv:{idx} invalid audit_status={row.get('audit_status')}")
        if row.get("audit_status") in {"verified_local", "external_only", "uncertain", "dropped"} and not row.get("reason"):
            _error(errors, "paper_audit_consistency", f"paper_audit.csv:{idx} missing keep/add/drop/uncertain reason")
        if row.get("audit_status") == "verified_local" and not row.get("local_paper_id"):
            _error(errors, "paper_audit_consistency", f"paper_audit.csv:{idx} verified row lacks local_paper_id")
    metrics["paper_audit_statuses"] = dict(statuses)


def _check_retrieval(out_dir: Path, errors: list[dict[str, Any]], warnings: list[dict[str, Any]], metrics: dict[str, Any]) -> None:
    requests = _load_jsonl(out_dir / "retrieval/retrieval_requests.jsonl", errors, required=True)
    traces = _load_jsonl(out_dir / "retrieval/retrieval_trace.jsonl", errors, required=True)
    candidates = _load_jsonl(out_dir / "retrieval/closest_work_candidates.jsonl", errors, required=True)
    trace_ids = {row.get("trace_id") for row in traces}
    for idx, request in enumerate(requests, start=1):
        for field in ("target_type", "target_id", "purpose", "query", "retrieval_mode", "candidate_list", "trace_id"):
            if field not in request:
                _error(errors, "retrieval_trace_coverage", f"retrieval_requests.jsonl:{idx} missing {field}")
        if request.get("trace_id") not in trace_ids:
            _error(errors, "retrieval_trace_coverage", f"request {request.get('request_id')} has no matching trace")
        if int(request.get("top_k", 0)) > 10:
            _error(errors, "absence_unbounded_discovery", f"request {request.get('request_id')} top_k exceeds bounded cap")
    for idx, trace in enumerate(traces, start=1):
        if trace.get("bounded") is not True:
            _error(errors, "absence_unbounded_discovery", f"retrieval_trace.jsonl:{idx} is not marked bounded")
        for candidate in trace.get("candidate_list", []):
            if "ranking_reason" not in candidate or "drop_reason" not in candidate:
                _error(errors, "retrieval_trace_coverage", f"trace {trace.get('trace_id')} candidate lacks ranking/drop reason")
    if not candidates:
        _warning(warnings, "retrieval_trace_coverage", "no closest_work_candidates emitted")
    modes = Counter(row.get("retrieval_mode", "") for row in requests)
    metrics["retrieval_modes"] = dict(modes)


def _check_evidence_links(out_dir: Path, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    evidence = _load_jsonl(out_dir / "assets/evidence_cards.jsonl", errors, required=True)
    evidence_ids = {row.get("evidence_id") for row in evidence}
    claim_graph = _load_json(out_dir / "assets/claim_graph.json", errors, required=True)
    gaps = _load_jsonl(out_dir / "assets/gap_map.jsonl", errors, required=True)
    paper_assets = _load_jsonl(out_dir / "assets/paper_assets.jsonl", errors, required=True)
    for claim in claim_graph.get("claims", []):
        for evidence_id in claim.get("evidence_ids", []):
            if evidence_id not in evidence_ids:
                _error(errors, "evidence_pointer_consistency", f"claim {claim.get('claim_id')} references missing evidence {evidence_id}")
        if claim.get("status") == "verified_fact" and not claim.get("evidence_ids"):
            _error(errors, "critical_claim_coverage", f"verified claim lacks evidence: {claim.get('claim_id')}")
        if claim.get("origin", "").startswith("external") and claim.get("status") == "verified_fact":
            _error(errors, "critical_claim_coverage", f"external claim marked verified_fact: {claim.get('claim_id')}")
    for gap in gaps:
        for evidence_id in gap.get("supporting_evidence_ids", []):
            if evidence_id not in evidence_ids:
                _error(errors, "evidence_pointer_consistency", f"gap {gap.get('gap_id')} references missing evidence {evidence_id}")
        if gap.get("falsification_status") in {"", "not_checked"}:
            _error(errors, "gap_falsification_status", f"gap lacks falsification status: {gap.get('gap_id')}")
    for asset in paper_assets:
        for evidence_id in asset.get("evidence_card_ids", []):
            if evidence_id not in evidence_ids:
                _error(errors, "evidence_pointer_consistency", f"paper asset {asset.get('paper_id')} references missing evidence {evidence_id}")


def _check_missing_evidence(out_dir: Path, errors: list[dict[str, Any]], warnings: list[dict[str, Any]], metrics: dict[str, Any]) -> None:
    missing = _load_jsonl(out_dir / "assets/missing_evidence.jsonl", errors, required=True)
    gaps = _load_jsonl(out_dir / "assets/gap_map.jsonl", errors, required=True)
    missing_ids = {row.get("missing_id") for row in missing}
    for gap in gaps:
        for missing_id in gap.get("missing_evidence_ids", []):
            if missing_id not in missing_ids:
                _error(errors, "missing_evidence_consistency", f"gap {gap.get('gap_id')} references missing missing_evidence {missing_id}")
        if not gap.get("closest_work_ids") and gap.get("downstream_ready"):
            _error(errors, "missing_evidence_consistency", f"gap without closest_work marked downstream_ready: {gap.get('gap_id')}")
    metrics["missing_evidence_count"] = len(missing)
    metrics["blocking_missing_evidence_count"] = sum(1 for row in missing if str(row.get("severity", "")).startswith("blocking"))


def _check_downstream_contract(out_dir: Path, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    contract = _load_json(out_dir / "downstream/survey_contract.json", errors, required=True)
    required = {
        "schema_version",
        "topic",
        "verified_paper_set_path",
        "claim_graph_path",
        "gap_map_path",
        "closest_work_candidates_path",
        "paper_assets_path",
        "asset_stats_path",
        "evidence_cards_path",
        "missing_evidence_path",
        "implementation_constraints",
        "reviewer_blocker_hints",
        "seed_opportunities",
        "warnings",
        "provenance_summary",
        "validation_status",
    }
    missing = sorted(required - set(contract))
    if missing:
        _error(errors, "downstream_contract_completeness", f"survey_contract.json missing fields: {missing}")
    for field in (
        "verified_paper_set_path",
        "claim_graph_path",
        "gap_map_path",
        "closest_work_candidates_path",
        "paper_assets_path",
        "asset_stats_path",
        "evidence_cards_path",
        "missing_evidence_path",
    ):
        rel = contract.get(field, "")
        if rel and not (out_dir / rel).exists():
            _error(errors, "downstream_contract_completeness", f"contract path missing for {field}: {rel}")
    for opportunity in contract.get("seed_opportunities", []):
        if not opportunity.get("closest_work_ids") and opportunity.get("downstream_ready"):
            _error(errors, "downstream_contract_completeness", f"opportunity without closest work is downstream_ready: {opportunity.get('gap_id')}")


def _check_report_links(out_dir: Path, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    report = (out_dir / "survey_report.md").read_text(encoding="utf-8", errors="ignore")
    required_links = (
        "audit/paper_audit.csv",
        "assets/paper_assets.jsonl",
        "assets/evidence_cards.jsonl",
        "assets/claim_graph.json",
        "assets/gap_map.jsonl",
        "retrieval/closest_work_candidates.jsonl",
        "assets/missing_evidence.jsonl",
        "downstream/survey_contract.json",
    )
    for rel in required_links:
        if rel not in report:
            _error(errors, "survey_report_links", f"survey_report.md does not link {rel}")


def _check_no_direction_hardcode(out_dir: Path, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    repo = _repo_root(out_dir)
    if not repo:
        _warning(warnings, "absence_direction_hardcode", "could not locate repo root for generic code hard-code scan")
        return
    for rel in GENERIC_CODE_FILES:
        path = repo / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for pattern in HARDCODE_PATTERNS:
            if re.search(pattern, text):
                _error(errors, "absence_direction_hardcode", f"generic code contains direction-specific hard-code pattern {pattern}: {rel}")


def _check_no_unbounded_discovery(out_dir: Path, errors: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
    requests = _load_jsonl(out_dir / "retrieval/retrieval_requests.jsonl", errors, required=True)
    for request in requests:
        mode = request.get("retrieval_mode", "")
        if mode not in BOUNDED_REQUEST_MODES:
            _error(errors, "absence_unbounded_discovery", f"unexpected retrieval mode in request: {mode}")
        purpose = str(request.get("purpose", "")).lower()
        if "open-domain" in purpose or "discovery" in purpose:
            _error(errors, "absence_unbounded_discovery", f"request purpose suggests unbounded discovery: {request.get('request_id')}")


def _repo_root(out_dir: Path) -> Path | None:
    for path in [out_dir, *out_dir.parents]:
        if (path / ".agents" / "skills" / "resmax-survey").exists():
            return path
    cwd = Path.cwd()
    if (cwd / ".agents" / "skills" / "resmax-survey").exists():
        return cwd
    return None


def _load_json(path: Path, errors: list[dict[str, Any]], *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            _error(errors, "artifact_existence", f"missing JSON file: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _error(errors, "schema_validity", f"invalid JSON {path}: {exc}")
        return {}


def _load_jsonl(path: Path, errors: list[dict[str, Any]], *, required: bool) -> list[dict[str, Any]]:
    if not path.exists():
        if required:
            _error(errors, "artifact_existence", f"missing JSONL file: {path}")
        return []
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            _error(errors, "schema_validity", f"invalid JSONL {path}:{line_no}: {exc}")
            continue
        if not isinstance(payload, dict):
            _error(errors, "schema_validity", f"JSONL row is not object {path}:{line_no}")
            continue
        rows.append(payload)
    return rows


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Normalized Survey Validation",
        "",
        f"- Status: `{report['status']}`",
        f"- Errors: {len(report['errors'])}",
        f"- Warnings: {len(report['warnings'])}",
        "",
        "## Checks",
        "",
    ]
    for name, ok in sorted(report["checks"].items()):
        lines.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    if report["errors"]:
        lines.extend(["", "## Errors", ""])
        for error in report["errors"]:
            lines.append(f"- `{error['check']}` {error['message']}")
    if report["warnings"]:
        lines.extend(["", "## Warnings", ""])
        for warning in report["warnings"]:
            lines.append(f"- `{warning['check']}` {warning['message']}")
    return "\n".join(lines) + "\n"


def _error(errors: list[dict[str, Any]], check: str, message: str) -> None:
    errors.append({"check": check, "message": message})


def _warning(warnings: list[dict[str, Any]], check: str, message: str) -> None:
    warnings.append({"check": check, "message": message})


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
