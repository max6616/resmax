from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from validators.common import load_json, validate_json_file  # type: ignore
else:
    from .common import load_json, validate_json_file


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
PHASE4_POSITIVE_DIMENSIONS = {
    "publication_upside",
    "novelty_headroom",
    "evidence_confidence",
    "benchmark_leverage",
    "implementation_reuse",
    "story_clarity",
    "information_gap",
}
PHASE4_DIFFICULTY_DIMENSIONS = {
    "sota_pressure",
    "baseline_burden",
    "compute_cost",
    "data_friction",
    "engineering_risk",
    "timeline_risk",
    "review_risk",
}
PHASE4_OBJECTION_TYPES = {
    "novelty",
    "baseline",
    "theory",
    "clarity",
    "ablation",
    "dataset",
    "efficiency",
    "reproducibility",
}
PHASE4_ROLES = {
    "direct_baseline",
    "method_donor",
    "benchmark_opportunity",
    "dataset_source",
    "implementation_reference",
    "negative_evidence",
    "survey_or_taxonomy",
    "theory_or_mechanism",
    "visualization_reference",
    "reviewer_expectation_reference",
}
PHASE4_REQUIRED = {
    "reviewer_pressure_notes.jsonl",
    "paper_roles.json",
    "baseline_matrix.csv",
    "benchmark_matrix.csv",
    "implementation_matrix.csv",
    "gap_roi_table.csv",
    "roi_lens.json",
    "risk_register.md",
    "idea_seed_constraints.md",
}


def _validate_artifact(manifest_dir: Path, artifact: dict, schema_dir: Path) -> list[str]:
    errors: list[str] = []
    rel_path = artifact.get("path", "")
    schema_name = artifact.get("schema", "")
    artifact_path = manifest_dir / rel_path
    if not artifact_path.exists():
        return [f"$.artifacts[{rel_path!r}]: artifact does not exist"]
    expected_hash = artifact.get("sha256", "")
    if expected_hash:
        actual_hash = _sha256_file(artifact_path)
        if actual_hash != expected_hash:
            errors.append(f"$.artifacts[{rel_path!r}].sha256: expected {expected_hash}, got {actual_hash}")
    if not schema_name:
        return errors
    schema_path = schema_dir / schema_name
    if not schema_path.exists():
        errors.append(f"$.artifacts[{rel_path!r}].schema: schema does not exist: {schema_name}")
        return errors
    if artifact_path.suffix == ".jsonl":
        try:
            from validators.validate_jsonl import run as validate_jsonl_run  # type: ignore
        except ImportError:
            from .validate_jsonl import run as validate_jsonl_run
        code = validate_jsonl_run(schema_path, artifact_path)
        if code != 0:
            errors.append(f"$.artifacts[{rel_path!r}]: JSONL validation failed")
        return errors
    validation_errors = validate_json_file(artifact_path, schema_path)
    errors.extend(f"$.artifacts[{rel_path!r}] {err.format()}" for err in validation_errors)
    return errors


def run(manifest_path: Path, schema_dir: Path = SCHEMA_DIR) -> int:
    manifest_schema = schema_dir / "research_pack_manifest.schema.json"
    errors = validate_json_file(manifest_path, manifest_schema)
    try:
        manifest = load_json(manifest_path)
    except Exception as exc:
        print(f"ERROR $: {exc}", file=sys.stderr)
        return 2
    for artifact in manifest.get("artifacts", []):
        if isinstance(artifact, dict):
            errors.extend(_validate_artifact(manifest_path.parent, artifact, schema_dir))
    errors.extend(_validate_pack_references(manifest_path.parent, manifest))
    if errors:
        for error in errors:
            print(f"ERROR {error.format() if hasattr(error, 'format') else error}")
        return 1
    print(f"OK {manifest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Resmax research pack manifest and listed artifacts.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--manifest", type=Path)
    target.add_argument("--pack", type=Path, help="Path to a research_pack directory containing manifest.json.")
    parser.add_argument("--schema-dir", type=Path, default=SCHEMA_DIR)
    args = parser.parse_args(argv)
    manifest_path = args.manifest or args.pack / "manifest.json"
    return run(manifest_path, args.schema_dir)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                rows.append({"__json_error__": f"{path}:{line_no}: {exc}"})
    return rows


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return load_json(path)
    except Exception:
        return {}


def _validate_pack_references(pack_dir: Path, manifest: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    manifest = manifest or {}
    is_phase3_pack = (pack_dir / "selected_subdirection.json").exists() or (pack_dir / "evidence_spans.jsonl").exists()
    spans = _read_json_records(pack_dir / "evidence_spans.jsonl", pack_dir / "evidence_span.json")
    cards = _read_json_records(pack_dir / "evidence_cards.jsonl", pack_dir / "evidence_card.json")
    claim_graph = _load_optional_json(pack_dir / "claim_graph.json")
    gap_map = _load_optional_json(pack_dir / "gap_map.json")

    span_ids = {row.get("state_id") for row in spans if isinstance(row, dict)}
    card_ids = {row.get("state_id") for row in cards if isinstance(row, dict)}
    extracted_span_ids = {row.get("state_id") for row in spans if row.get("extraction_status") == "extracted"}
    coverage = manifest.get("evidence_coverage", {}) if isinstance(manifest, dict) else {}
    if is_phase3_pack and int(coverage.get("selected_candidate_count") or 0) > 0 and int(coverage.get("evidence_card_count") or 0) == 0:
        errors.append("phase3 evidence quality gate failed: selected candidates produced zero EvidenceCards")
    materialization = manifest.get("source_materialization", {}) if isinstance(manifest, dict) else {}
    selected_count = int(materialization.get("selected_candidate_count") or coverage.get("selected_candidate_count") or 0)
    full_text_span_count = int(coverage.get("full_text_evidence_count") or 0)
    if full_text_span_count == 0:
        full_text_span_count = len(
            [
                row
                for row in spans
                if row.get("extraction_status") == "extracted" and row.get("source_type") != "accepted_index"
            ]
        )
    readable_count = int(materialization.get("readable_source_count") or 0)
    if readable_count == 0:
        readable_count = len(
            {
                row.get("paper_id")
                for row in spans
                if row.get("extraction_status") == "extracted"
                and row.get("source_type") != "accepted_index"
                and row.get("paper_id")
            }
        )
    if is_phase3_pack and selected_count > 0:
        if full_text_span_count == 0:
            errors.append("phase3 evidence quality gate failed: selected candidates produced zero full-text EvidenceSpans")
        if selected_count >= 10 and readable_count / selected_count < 0.95:
            errors.append(
                "phase3 source materialization quality gate failed: "
                f"readable_source_count={readable_count}/{selected_count} below 95%"
            )

    for row in spans:
        if "__json_error__" in row:
            errors.append(row["__json_error__"])
            continue
        if is_phase3_pack and row.get("extraction_status") == "extracted":
            for field in ("source_type", "section", "locator", "quote_hash", "parser"):
                if not row.get(field):
                    errors.append(f"evidence_span {row.get('state_id', '<unknown>')}: missing Phase 3 field {field}")

    for row in cards:
        if "__json_error__" in row:
            errors.append(row["__json_error__"])
            continue
        if is_phase3_pack:
            for field in ("relation", "scope", "strength"):
                if not row.get(field):
                    errors.append(f"evidence_card {row.get('state_id', '<unknown>')}: missing Phase 3 field {field}")
        for span_id in row.get("evidence_span_ids", []):
            if span_id not in span_ids:
                errors.append(f"evidence_card {row.get('state_id', '<unknown>')}: unknown evidence_span_id {span_id}")
            if extracted_span_ids and span_id not in extracted_span_ids:
                errors.append(f"evidence_card {row.get('state_id', '<unknown>')}: references non-extracted span {span_id}")

    claims = claim_graph.get("claims", []) if isinstance(claim_graph, dict) else []
    claim_ids = {claim.get("claim_id") for claim in claims if isinstance(claim, dict)}
    claim_by_id = {claim.get("claim_id"): claim for claim in claims if isinstance(claim, dict)}
    for claim in claims:
        if is_phase3_pack and not claim.get("scope"):
            errors.append(f"claim {claim.get('claim_id', '<unknown>')}: missing scope")
        for card_id in claim.get("evidence_card_ids", []):
            if card_id not in card_ids:
                errors.append(f"claim {claim.get('claim_id', '<unknown>')}: unknown evidence_card_id {card_id}")

    for edge in claim_graph.get("edges", []) if isinstance(claim_graph, dict) else []:
        left = claim_by_id.get(edge.get("source_claim_id"))
        right = claim_by_id.get(edge.get("target_claim_id"))
        if not left or not right:
            errors.append(f"claim edge references unknown claim: {edge}")
            continue
        if (
            edge.get("relation") == "contradicts"
            and left.get("scope") != right.get("scope")
            and left.get("strength") == "strong"
            and right.get("strength") == "strong"
        ):
            errors.append("strong contradiction cannot connect claims with different scopes")

    for gap in gap_map.get("gaps", []) if isinstance(gap_map, dict) else []:
        gap_id = gap.get("gap_id", "<unknown>")
        supporting_claim_ids = gap.get("supporting_claim_ids", [])
        evidence_card_ids = gap.get("evidence_card_ids", [])
        if gap.get("gap_type") != "missing_evidence" and not supporting_claim_ids and not evidence_card_ids:
            errors.append(f"gap {gap_id}: must reference claim/evidence or use gap_type='missing_evidence'")
        for claim_id in supporting_claim_ids:
            if claim_id not in claim_ids:
                errors.append(f"gap {gap_id}: unknown supporting_claim_id {claim_id}")
        for card_id in evidence_card_ids:
            if card_id not in card_ids:
                errors.append(f"gap {gap_id}: unknown evidence_card_id {card_id}")
        if gap.get("confidence") == "high":
            linked_cards = set(evidence_card_ids)
            for claim_id in supporting_claim_ids:
                claim = claim_by_id.get(claim_id, {})
                linked_cards.update(claim.get("evidence_card_ids", []))
            if len(linked_cards) < 2:
                errors.append(f"gap {gap_id}: high-confidence gap needs at least two EvidenceCard references")
    errors.extend(_validate_phase4_pack(pack_dir, manifest, gap_map, card_ids))
    return errors


def _read_json_records(jsonl_path: Path, json_path: Path) -> list[dict[str, Any]]:
    if jsonl_path.exists():
        return _read_jsonl(jsonl_path)
    if json_path.exists():
        try:
            payload = load_json(json_path)
        except Exception as exc:
            return [{"__json_error__": f"{json_path}: {exc}"}]
        return [payload] if isinstance(payload, dict) else []
    return []


def _validate_phase4_pack(
    pack_dir: Path,
    manifest: dict[str, Any],
    gap_map: dict[str, Any],
    card_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    phase4_present = any((pack_dir / rel).exists() for rel in PHASE4_REQUIRED)
    if not phase4_present:
        return errors

    artifact_paths = {
        artifact.get("path", "")
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
    }
    missing_artifacts = sorted(rel for rel in PHASE4_REQUIRED if rel not in artifact_paths or not (pack_dir / rel).exists())
    for rel in missing_artifacts:
        errors.append(f"phase4 artifact missing from manifest or filesystem: {rel}")
    if not isinstance(manifest.get("source_counts"), dict):
        errors.append("phase4 manifest missing source_counts")
    if not isinstance(manifest.get("mechanical_checks"), dict):
        errors.append("phase4 manifest missing mechanical_checks")

    gaps = gap_map.get("gaps", []) if isinstance(gap_map, dict) else []
    gap_ids = {gap.get("gap_id") for gap in gaps if isinstance(gap, dict)}
    notes = _read_jsonl(pack_dir / "reviewer_pressure_notes.jsonl")
    note_ids: set[str] = set()
    for note in notes:
        note_id = note.get("note_id", "")
        if not note_id:
            errors.append("reviewer_pressure_note missing note_id")
        note_ids.add(note_id)
        for field in (
            "paper_id",
            "gap_id",
            "objection_type",
            "objection_text",
            "severity",
            "resolved_by_authors",
            "source_review_id",
            "evidence_ids",
            "implication_for_new_idea",
        ):
            if field not in note:
                errors.append(f"reviewer_pressure_note {note_id or '<unknown>'}: missing {field}")
        if note.get("gap_id") not in gap_ids:
            errors.append(f"reviewer_pressure_note {note_id or '<unknown>'}: unknown gap_id {note.get('gap_id')}")
        if note.get("objection_type") not in PHASE4_OBJECTION_TYPES:
            errors.append(f"reviewer_pressure_note {note_id or '<unknown>'}: unsupported objection_type {note.get('objection_type')}")
        if note.get("severity") not in {"low", "medium", "high"}:
            errors.append(f"reviewer_pressure_note {note_id or '<unknown>'}: unsupported severity {note.get('severity')}")
        if not note.get("inferred") and not note.get("source_path"):
            errors.append(f"reviewer_pressure_note {note_id or '<unknown>'}: real review note missing source_path")
        for card_id in note.get("evidence_ids", []):
            if card_id not in card_ids:
                errors.append(f"reviewer_pressure_note {note_id or '<unknown>'}: unknown evidence_id {card_id}")

    roles = _load_optional_json(pack_dir / "paper_roles.json")
    taxonomy = set(roles.get("role_taxonomy", [])) if isinstance(roles, dict) else set()
    if not PHASE4_ROLES.issubset(taxonomy):
        errors.append("paper_roles role_taxonomy does not cover required Phase 4 roles")
    for assignment in roles.get("assignments", []) if isinstance(roles, dict) else []:
        if not assignment.get("paper_id"):
            errors.append("paper_roles assignment missing paper_id")
        for role in assignment.get("roles", []):
            if role.get("role") not in PHASE4_ROLES:
                errors.append(f"paper_roles {assignment.get('paper_id', '<unknown>')}: unsupported role {role.get('role')}")

    roi_lens = _load_optional_json(pack_dir / "roi_lens.json")
    gap_roi = roi_lens.get("gap_roi", []) if isinstance(roi_lens, dict) else []
    roi_by_gap = {entry.get("gap_id"): entry for entry in gap_roi if isinstance(entry, dict)}
    if set(roi_lens.get("positive_dimensions", [])) != PHASE4_POSITIVE_DIMENSIONS:
        errors.append("roi_lens positive_dimensions mismatch")
    if set(roi_lens.get("difficulty_dimensions", [])) != PHASE4_DIFFICULTY_DIMENSIONS:
        errors.append("roi_lens difficulty_dimensions mismatch")
    if roi_lens.get("decision_policy", {}).get("single_roi_score_allowed") is not False:
        errors.append("roi_lens must explicitly disallow single ROI score")
    for gap in gaps:
        gap_id = gap.get("gap_id")
        entry = roi_by_gap.get(gap_id)
        if not entry:
            errors.append(f"gap {gap_id}: missing ROI lens entry")
            continue
        positive = entry.get("positive_signals", {})
        difficulty = entry.get("difficulty_signals", {})
        unknowns = entry.get("unknowns", [])
        if set(positive) != PHASE4_POSITIVE_DIMENSIONS:
            errors.append(f"gap {gap_id}: positive ROI dimensions incomplete")
        if set(difficulty) != PHASE4_DIFFICULTY_DIMENSIONS:
            errors.append(f"gap {gap_id}: difficulty ROI dimensions incomplete")
        if not unknowns and any(payload.get("value") == "unknown" for payload in [*positive.values(), *difficulty.values()] if isinstance(payload, dict)):
            errors.append(f"gap {gap_id}: unknown dimension lacks explicit unknown follow-up")
        for unknown in unknowns:
            if not unknown.get("follow_up_retrieval_target"):
                errors.append(f"gap {gap_id}: unknown {unknown.get('field', '<unknown>')} missing follow_up_retrieval_target")
        if entry.get("decision_support", {}).get("single_roi_score") not in {None, ""}:
            errors.append(f"gap {gap_id}: single ROI score is not allowed")
        for blocker in entry.get("reviewer_blockers", []):
            if blocker.get("note_id") not in note_ids:
                errors.append(f"gap {gap_id}: reviewer blocker references unknown note {blocker.get('note_id')}")

    table_rows = _read_csv(pack_dir / "gap_roi_table.csv")
    for row in table_rows:
        if row.get("single_roi_score"):
            errors.append(f"gap_roi_table row {row.get('gap_id', '<unknown>')}: single_roi_score must be empty")
        if row.get("unknowns") and not row.get("follow_up_retrieval_targets"):
            errors.append(f"gap_roi_table row {row.get('gap_id', '<unknown>')}: unknowns lack follow_up_retrieval_targets")

    risk_register = (pack_dir / "risk_register.md").read_text(encoding="utf-8") if (pack_dir / "risk_register.md").exists() else ""
    if "roi_lens.json" not in risk_register or "gap_roi_table.csv" not in risk_register:
        errors.append("risk_register.md must reference structured ROI artifacts")
    constraints = (pack_dir / "idea_seed_constraints.md").read_text(encoding="utf-8") if (pack_dir / "idea_seed_constraints.md").exists() else ""
    if "not ideas" not in constraints.lower() and "not idea" not in constraints.lower():
        errors.append("idea_seed_constraints.md must state that constraints are not ideas")
    return errors


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


if __name__ == "__main__":
    raise SystemExit(main())
