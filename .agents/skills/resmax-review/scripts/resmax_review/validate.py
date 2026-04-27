from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from resmax_core.validators.common import load_json, validate_with_schema

from . import FINAL_STATUS_FILES, REVIEW_ARTIFACTS, SCHEMA_ROOT
from .build_evidence_package import read_json, read_jsonl, sha256_file, sha256_text


def validate_reviews_dir(reviews: Path) -> list[str]:
    errors: list[str] = []
    if not reviews.exists():
        return [f"{reviews}: reviews directory does not exist"]
    missing = [name for name in REVIEW_ARTIFACTS if not (reviews / name).exists()]
    errors.extend(f"{reviews / name}: required artifact missing" for name in missing)
    if not (reviews / "evidence_packages").exists():
        errors.append(f"{reviews / 'evidence_packages'}: required directory missing")
    if not (reviews / "raw").exists():
        errors.append(f"{reviews / 'raw'}: required directory missing")
    if missing:
        return errors

    manifest = read_json(reviews / "manifest.json")
    errors.extend(_validate_manifest_hashes(reviews, manifest))
    evidence_hashes = {
        path.stem: sha256_file(path)
        for path in sorted((reviews / "evidence_packages").glob("*.json"))
    }
    raw_index: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_path in sorted((reviews / "raw").glob("*/*.json")):
        trace = read_json(raw_path)
        errors.extend(_validate_trace(trace, raw_path, evidence_hashes))
        raw_index[(trace.get("reviewer_role", raw_path.parent.name), trace.get("idea_id", raw_path.stem))] = trace

    decisions = _load_decisions(reviews)
    errors.extend(_validate_decisions(manifest, decisions, raw_index, reviews))
    errors.extend(_validate_tournament_trace(reviews / "tournament_trace.jsonl"))
    return errors


def _validate_trace(trace: dict[str, Any], raw_path: Path, evidence_hashes: dict[str, str]) -> list[str]:
    schema = load_json(SCHEMA_ROOT / "review_trace.schema.json")
    errors = [f"{raw_path} {error.format()}" for error in validate_with_schema(trace, schema)]
    idea_id = trace.get("idea_id", raw_path.stem)
    expected_hash = evidence_hashes.get(str(idea_id))
    if expected_hash and trace.get("evidence_package_hash") != expected_hash:
        errors.append(f"{raw_path}: evidence_package_hash mismatch")
    if trace.get("prompt") and trace.get("prompt_hash") != sha256_text(str(trace["prompt"])):
        errors.append(f"{raw_path}: prompt_hash mismatch")
    if not trace.get("raw_response"):
        errors.append(f"{raw_path}: raw_response is required")
    if trace.get("reviewer_model") == trace.get("generator_model"):
        if trace.get("review_independence_confidence") != "low":
            errors.append(f"{raw_path}: same-model fallback must set review_independence_confidence=low")
        if "same model used for generation and review" not in str(trace.get("fallback_reason", "")):
            errors.append(f"{raw_path}: same-model fallback must explain fallback_reason")
    return errors


def _validate_manifest_hashes(reviews: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for artifact in manifest.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        rel = artifact.get("path", "")
        expected = artifact.get("sha256", "")
        path = reviews / rel
        if not path.exists():
            errors.append(f"manifest artifact missing: {rel}")
            continue
        actual = sha256_file(path)
        if expected and actual != expected:
            errors.append(f"manifest sha256 mismatch for {rel}: expected {expected}, got {actual}")
    return errors


def _load_decisions(reviews: Path) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for filename in FINAL_STATUS_FILES.values():
        decisions.extend(read_jsonl(reviews / filename))
    return decisions


def _validate_decisions(
    manifest: dict[str, Any],
    decisions: list[dict[str, Any]],
    raw_index: dict[tuple[str, str], dict[str, Any]],
    reviews: Path,
) -> list[str]:
    errors: list[str] = []
    required_roles = tuple(manifest.get("required_reviewer_roles", []))
    for row in decisions:
        idea_id = row.get("idea_id", "")
        if row.get("final_status") == "promoted":
            for role in required_roles:
                if (role, idea_id) not in raw_index:
                    errors.append(f"{idea_id}: promoted idea missing raw review role {role}")
            if _has_fatal_with_evidence(row):
                errors.append(f"{idea_id}: promoted idea has fatal blocker with evidence")
            evidence_path = reviews / "evidence_packages" / f"{idea_id}.json"
            if evidence_path.exists():
                package = read_json(evidence_path)
                card = package.get("idea_card", {})
                check = package.get("closest_work_check", {})
                if not card.get("closest_work_ids") or check.get("phase6_review_ready") is False:
                    errors.append(f"{idea_id}: promoted idea missing closest work")
        if row.get("final_status") == "promoted" and row.get("missing_review_roles"):
            errors.append(f"{idea_id}: promoted idea has missing raw reviews")
    return errors


def _has_fatal_with_evidence(row: dict[str, Any]) -> bool:
    return any(
        blocker.get("severity") == "fatal"
        and blocker.get("evidence_status") == "supported"
        and blocker.get("evidence_ids")
        for blocker in row.get("blockers", [])
    )


def _validate_tournament_trace(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line_no, raw in enumerate(f, 1):
                if not raw.strip():
                    continue
                row = json.loads(raw)
                if not isinstance(row, dict):
                    errors.append(f"{path}:{line_no}: expected JSON object")
                if row.get("event_index") != line_no:
                    errors.append(f"{path}:{line_no}: event_index must match append order")
    except Exception as exc:
        errors.append(f"{path}: {exc}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 6 review outputs.")
    parser.add_argument("--reviews", required=True, type=Path)
    args = parser.parse_args(argv)
    errors = validate_reviews_dir(args.reviews)
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(f"OK {args.reviews}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
