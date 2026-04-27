from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from resmax_core.validators.common import ValidationError, load_json, validate_with_schema

from . import SCHEMA_ROOT


class MacroValidationError(Exception):
    pass


def validate_macro_pack(root_dir: Path) -> list[str]:
    survey_dir = root_dir / "survey_v2"
    spec_dir = survey_dir / "spec"
    macro_dir = survey_dir / "macro"
    checks: list[str] = []

    research_spec_path = _require_file(spec_dir / "research_spec.json")
    source_policy_path = _require_file(spec_dir / "source_policy.json")
    query_family_path = _require_file(spec_dir / "query_families.jsonl")
    trace_path = _require_file(macro_dir / "retrieval_trace.jsonl")
    query_embedding_trace_path = macro_dir / "query_embedding_trace.jsonl"
    broad_candidates_path = _require_file(macro_dir / "broad_candidates.csv")
    subdirection_map_path = _require_file(macro_dir / "subdirection_map.json")
    roi_table_path = _require_file(macro_dir / "subdirection_roi_table.csv")
    _require_file(macro_dir / "macro_survey_report.md")
    manifest_path = _require_file(survey_dir / "manifest.json")

    _validate_json(research_spec_path, SCHEMA_ROOT / "research_spec.schema.json")
    checks.append(f"OK research_spec {research_spec_path}")
    source_policy = _validate_json(source_policy_path, SCHEMA_ROOT / "source_policy.schema.json")
    _validate_source_policy(source_policy)
    checks.append(f"OK source_policy {source_policy_path}")
    _validate_jsonl(query_family_path, SCHEMA_ROOT / "query_family.schema.json")
    _validate_query_family_roles(query_family_path)
    checks.append(f"OK query_families {query_family_path}")
    semantic_modes = _query_family_modes(query_family_path) & {"embedding", "hybrid"}
    manifest = load_json(manifest_path)
    if semantic_modes:
        _require_file(query_embedding_trace_path)
        _validate_query_embedding_trace(query_embedding_trace_path, manifest)
        checks.append(f"OK query_embedding_trace {query_embedding_trace_path}")
    _validate_jsonl(trace_path, SCHEMA_ROOT / "retrieval_trace.schema.json")
    checks.append(f"OK retrieval_trace {trace_path}")

    candidate_rows = _read_csv(broad_candidates_path)
    _validate_candidates(candidate_rows)
    checks.append(f"OK broad_candidates {broad_candidates_path}")
    subdirection_map = load_json(subdirection_map_path)
    _validate_subdirection_map(subdirection_map)
    checks.append(f"OK subdirection_map {subdirection_map_path}")
    roi_rows = _read_csv(roi_table_path)
    _validate_roi_rows(roi_rows)
    checks.append(f"OK rough_roi {roi_table_path}")
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Survey V2 macro pack.")
    parser.add_argument("--dir", required=True, type=Path, help="Root directory containing survey_v2/.")
    args = parser.parse_args(argv)
    try:
        checks = validate_macro_pack(args.dir)
    except (MacroValidationError, ValidationError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}")
        return 1
    for check in checks:
        print(check)
    return 0


def _require_file(path: Path) -> Path:
    if not path.exists() or not path.is_file():
        raise MacroValidationError(f"required artifact missing: {path}")
    if path.stat().st_size == 0:
        raise MacroValidationError(f"required artifact is empty: {path}")
    return path


def _validate_json(path: Path, schema_path: Path) -> dict[str, Any]:
    payload = load_json(path)
    errors = validate_with_schema(payload, load_json(schema_path))
    if errors:
        detail = "; ".join(error.format() for error in errors)
        raise MacroValidationError(f"{path} failed schema validation: {detail}")
    return payload


def _validate_jsonl(path: Path, schema_path: Path) -> None:
    schema = load_json(schema_path)
    line_count = 0
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            line_count += 1
            payload = json.loads(raw)
            errors = validate_with_schema(payload, schema)
            if errors:
                detail = "; ".join(error.format() for error in errors)
                raise MacroValidationError(f"{path}:{line_no} failed schema validation: {detail}")
    if line_count == 0:
        raise MacroValidationError(f"jsonl artifact has no records: {path}")


def _validate_source_policy(source_policy: dict[str, Any]) -> None:
    disabled = set(source_policy.get("disabled_capabilities", []))
    required_disabled = {"full_text_extraction", "mineru", "sci_hub", "final_idea_generation", "experiment_plan"}
    missing = required_disabled - disabled
    if missing:
        raise MacroValidationError(f"source_policy missing disabled capabilities: {sorted(missing)}")
    claim_policy = source_policy.get("claim_support_policy", {})
    if claim_policy.get("allow_strong_recommendation") is not False:
        raise MacroValidationError("source_policy must disallow strong recommendations in Phase 2")
    if claim_policy.get("rough_roi_only") is not True:
        raise MacroValidationError("source_policy must mark rough_roi_only=true")


def _validate_query_family_roles(path: Path) -> None:
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            payload = json.loads(raw)
            if not payload.get("family_role"):
                raise MacroValidationError(f"{path}:{line_no} missing family_role")
            if not payload.get("information_need"):
                raise MacroValidationError(f"{path}:{line_no} missing information_need")


def _query_family_modes(path: Path) -> set[str]:
    modes: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                modes.add(str(json.loads(raw).get("retrieval_mode", "keyword")))
    return modes


def _validate_query_embedding_trace(path: Path, manifest: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            rows.append(row)
            if not row.get("query_id"):
                raise MacroValidationError(f"{path}:{line_no} missing query_id")
            if row.get("provider") not in {"none", "ssh", "hash"}:
                raise MacroValidationError(f"{path}:{line_no} invalid embedding provider")
            if row.get("ok") is True and int(row.get("dimension") or 0) <= 0:
                raise MacroValidationError(f"{path}:{line_no} encoded query has invalid dimension")
    if not rows:
        raise MacroValidationError(f"query embedding trace has no records: {path}")
    query_embedding = manifest.get("query_embedding", {})
    if query_embedding.get("required") is True:
        failed = [row for row in rows if row.get("ok") is not True]
        if failed:
            raise MacroValidationError(f"required query embedding failed for {len(failed)} queries")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _validate_candidates(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise MacroValidationError("broad_candidates.csv has no candidate rows")
    for row in rows:
        if row.get("rough_roi_confidence") != "low":
            raise MacroValidationError(f"{row.get('paper_id', '<unknown>')} has non-low rough ROI confidence")
        if row.get("rough_roi_evidence_status") not in {"weak", "unknown", "insufficient_evidence"}:
            raise MacroValidationError(f"{row.get('paper_id', '<unknown>')} has invalid rough ROI evidence status")
        if not row.get("query_roles"):
            raise MacroValidationError(f"{row.get('paper_id', '<unknown>')} has no query role trace")


def _validate_subdirection_map(payload: dict[str, Any]) -> None:
    subdirections = payload.get("subdirections")
    if not isinstance(subdirections, list) or not subdirections:
        raise MacroValidationError("subdirection_map.json must contain at least one subdirection")
    for entry in subdirections:
        if not entry.get("subdirection_id") or not entry.get("label"):
            raise MacroValidationError("subdirection entries must include subdirection_id and label")


def _validate_roi_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise MacroValidationError("subdirection_roi_table.csv has no rows")
    for row in rows:
        if row.get("rough_roi_confidence") != "low":
            raise MacroValidationError(f"{row.get('subdirection_id', '<unknown>')} has non-low rough ROI confidence")
        for field in ("benchmark_burden", "compute_burden", "baseline_burden", "reviewer_risk", "evidence_status"):
            if row.get(field) not in {"weak", "unknown", "insufficient_evidence"}:
                raise MacroValidationError(f"{row.get('subdirection_id', '<unknown>')} has invalid {field}")


if __name__ == "__main__":
    raise SystemExit(main())
