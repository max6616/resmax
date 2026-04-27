from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from resmax_core.validators.common import load_json, validate_with_schema

from . import ALLOWED_GENERATION_SOURCES, PORTFOLIO_ARTIFACTS, SCHEMA_ROOT


def validate_ideas_dir(ideas: Path) -> list[str]:
    errors: list[str] = []
    if not ideas.exists():
        return [f"{ideas}: ideas directory does not exist"]
    missing = [name for name in PORTFOLIO_ARTIFACTS if not (ideas / name).exists()]
    errors.extend(f"{ideas / name}: required artifact missing" for name in missing)
    if missing:
        return errors

    manifest = _load_json(ideas / "manifest.json", errors)
    source_index = manifest.get("source_index", {}) if isinstance(manifest, dict) else {}
    errors.extend(_validate_manifest_hashes(ideas, manifest))

    schema = load_json(SCHEMA_ROOT / "idea_card.schema.json")
    cards = _read_jsonl(ideas / "idea_cards.jsonl", errors)
    checks = _read_jsonl(ideas / "closest_work_checks.jsonl", errors)
    lineage = _load_json(ideas / "idea_lineage.json", errors)
    check_by_idea = {check.get("idea_id"): check for check in checks if isinstance(check, dict)}
    lineage_ids = {
        node.get("idea_id")
        for node in lineage.get("nodes", [])
        if isinstance(node, dict) and node.get("idea_id")
    } if isinstance(lineage, dict) else set()

    idea_ids: set[str] = set()
    for index, card in enumerate(cards, 1):
        prefix = f"idea_cards.jsonl line {index}"
        schema_errors = validate_with_schema(card, schema)
        errors.extend(f"{prefix} {error.format()}" for error in schema_errors)
        if schema_errors:
            continue
        idea_id = card["idea_id"]
        if idea_id in idea_ids:
            errors.append(f"{prefix}: duplicate idea_id {idea_id}")
        idea_ids.add(idea_id)
        if idea_id not in check_by_idea:
            errors.append(f"{prefix}: missing closest_work_checks row")
        if idea_id not in lineage_ids:
            errors.append(f"{prefix}: missing idea_lineage node")
        errors.extend(_validate_card_contract(card, source_index, prefix))

    report = (ideas / "idea_report.md").read_text(encoding="utf-8")
    if "rendered from structured artifacts" not in report:
        errors.append("idea_report.md must state that it is rendered from structured artifacts")
    return errors


def _validate_card_contract(card: dict[str, Any], source_index: dict[str, Any], prefix: str) -> list[str]:
    errors: list[str] = []
    gap_ids = set(source_index.get("gap_ids", []))
    evidence_ids = set(source_index.get("evidence_ids", []))
    claim_ids = set(source_index.get("claim_ids", []))
    paper_ids = set(source_index.get("paper_ids", []))

    if "topic_direct" in card.get("generation_sources", []):
        errors.append(f"{prefix}: topic_direct generation is forbidden")
    for source in card.get("generation_sources", []):
        if source not in ALLOWED_GENERATION_SOURCES:
            errors.append(f"{prefix}: unsupported generation source {source}")
    for gap_id in card.get("source_gap_ids", []):
        if gap_id not in gap_ids:
            errors.append(f"{prefix}: unknown source_gap_id {gap_id}")
    for evidence_id in card.get("evidence_ids", []):
        if evidence_id not in evidence_ids:
            errors.append(f"{prefix}: unknown evidence_id {evidence_id}")
    for claim_id in card.get("source_claim_ids", []):
        if claim_id not in claim_ids:
            errors.append(f"{prefix}: unknown source_claim_id {claim_id}")
    for paper_id in card.get("closest_work_ids", []):
        if paper_id not in paper_ids:
            errors.append(f"{prefix}: unknown closest_work_id {paper_id}")

    missing_gap_or_evidence = not card.get("source_gap_ids") or not card.get("evidence_ids")
    if missing_gap_or_evidence and card.get("status") not in {"speculative", "insufficient_evidence"}:
        errors.append(f"{prefix}: idea without source gaps/evidence must be speculative or insufficient_evidence")
    if card.get("readiness", {}).get("phase6_review_ready") and not card.get("closest_work_ids"):
        errors.append(f"{prefix}: phase6_review_ready without closest_work_ids")
    if card.get("status") == "phase6_ready" and not card.get("closest_work_ids"):
        errors.append(f"{prefix}: phase6_ready requires closest_work_ids")
    if card.get("readiness", {}).get("experiment_blueprint_ready") and not card.get("direct_baselines"):
        errors.append(f"{prefix}: experiment_blueprint_ready requires direct_baselines")
    if card.get("duplicate_memory_matches") and card.get("status") != "duplicate_risk":
        errors.append(f"{prefix}: duplicate negative-memory match must be marked duplicate_risk")
    if not card.get("strongest_rejection_case"):
        errors.append(f"{prefix}: missing strongest_rejection_case")
    if not card.get("cheapest_falsification", {}).get("minimal_test"):
        errors.append(f"{prefix}: missing cheapest falsification minimal_test")
    if card.get("status") == "recommended":
        errors.append(f"{prefix}: Phase 5 cannot mark ideas recommended")
    return errors


def _validate_manifest_hashes(ideas: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for artifact in manifest.get("artifacts", []) if isinstance(manifest, dict) else []:
        if not isinstance(artifact, dict):
            continue
        rel = artifact.get("path", "")
        expected = artifact.get("sha256", "")
        path = ideas / rel
        if not path.exists():
            errors.append(f"manifest artifact missing: {rel}")
            continue
        actual = _sha256_file(path)
        if expected and actual != expected:
            errors.append(f"manifest sha256 mismatch for {rel}: expected {expected}, got {actual}")
    return errors


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        errors.append(f"{path}: {exc}")
        return {}
    if not isinstance(payload, dict):
        errors.append(f"{path}: expected JSON object")
        return {}
    return payload


def _read_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line_no, raw in enumerate(f, 1):
                if not raw.strip():
                    continue
                row = json.loads(raw)
                if not isinstance(row, dict):
                    errors.append(f"{path}:{line_no}: expected JSON object")
                    continue
                rows.append(row)
    except Exception as exc:
        errors.append(f"{path}: {exc}")
    return rows


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Resmax Phase 5 idea portfolio.")
    parser.add_argument("--ideas", required=True, type=Path)
    args = parser.parse_args(argv)
    errors = validate_ideas_dir(args.ideas)
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(f"OK {args.ideas}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
