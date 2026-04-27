from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now
from resmax_core.validators.common import load_json, validate_with_schema

from . import FINAL_STATUS_FILES, PRODUCER, REVIEWER_ROLES, REVIEW_ARTIFACTS, SCHEMA_ROOT
from .build_evidence_package import (
    _artifact,
    build_evidence_packages,
    load_idea_context,
    read_json,
    read_jsonl,
    select_review_cards,
    sha256_file,
    sha256_text,
    write_json,
    write_jsonl,
)
from .render import render_blocker_summary, render_disagreement_report
from .tournament import append_tournament_trace, build_tournament_events, rank_decisions


def aggregate_reviews(
    *,
    ideas: Path,
    raw_reviews: Path,
    out: Path,
    pack: Path | None = None,
    required_roles: tuple[str, ...] = REVIEWER_ROLES,
    max_ideas: int = 1,
    all_ideas: bool = False,
) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    idea_ctx = load_idea_context(ideas)
    raw_index = _copy_and_load_raw_reviews(raw_reviews, out / "raw")
    raw_idea_ids = {idea_id for _, idea_id in raw_index}
    aggregate_available_raw = bool(raw_idea_ids) and not all_ideas
    build_evidence_packages(
        ideas=ideas,
        out=out,
        pack=pack,
        max_ideas=max_ideas,
        all_ideas=all_ideas or aggregate_available_raw,
    )
    selected_cards = select_review_cards(
        idea_ctx.cards,
        max_ideas=max_ideas,
        all_ideas=all_ideas or aggregate_available_raw,
    )
    if aggregate_available_raw:
        selected_cards = [card for card in selected_cards if card.get("idea_id") in raw_idea_ids]
    decisions: list[dict[str, Any]] = []
    for card in selected_cards:
        decisions.append(_aggregate_one(card, idea_ctx.closest_checks.get(card["idea_id"], {}), raw_index, out, required_roles))

    ranked = rank_decisions(decisions)
    rank_by_idea = {row["idea_id"]: rank for rank, row in enumerate(ranked, 1)}
    for row in decisions:
        row["tournament_rank"] = rank_by_idea[row["idea_id"]]

    _write_status_outputs(out, decisions)
    _write_review_matrix(out / "review_matrix.csv", decisions)
    render_blocker_summary(out / "blocker_summary.md", decisions)
    render_disagreement_report(out / "disagreement_report.md", decisions)
    run_id = f"phase6-{utc_now()}"
    append_tournament_trace(out / "tournament_trace.jsonl", build_tournament_events(decisions, run_id))
    manifest = _write_manifest(out, idea_ctx, decisions, required_roles)
    return {"out": str(out), "manifest": manifest, "decision_counts": manifest["decision_counts"]}


def _aggregate_one(
    card: dict[str, Any],
    closest_check: dict[str, Any],
    raw_index: dict[tuple[str, str], dict[str, Any]],
    out: Path,
    required_roles: tuple[str, ...],
) -> dict[str, Any]:
    idea_id = card["idea_id"]
    evidence_path = out / "evidence_packages" / f"{idea_id}.json"
    evidence_hash = sha256_file(evidence_path)
    traces: list[dict[str, Any]] = []
    missing_roles: list[str] = []
    validation_errors: list[str] = []
    for role in required_roles:
        trace = raw_index.get((role, idea_id))
        if trace is None:
            missing_roles.append(role)
            continue
        traces.append(trace)
        validation_errors.extend(_trace_errors(trace, idea_id, evidence_hash))

    blockers = _collect_blockers(traces)
    reviewer_statuses = sorted({trace.get("recommended_status", "human_gate") for trace in traces})
    fatal_with_evidence = [blocker for blocker in blockers if _is_fatal_with_evidence(blocker)]
    unsupported_fatal = [
        blocker
        for blocker in blockers
        if blocker.get("severity") == "fatal" and not _is_fatal_with_evidence(blocker)
    ]
    closest_missing = not card.get("closest_work_ids") or closest_check.get("phase6_review_ready") is False
    weak_evidence = _evidence_confidence(card) in {"low", "unknown"} or not card.get("evidence_ids")
    missing_baseline = not card.get("direct_baselines")
    disagreement = len(reviewer_statuses) > 1

    decision_reasons: list[str] = []
    process_blockers: list[dict[str, Any]] = []
    if fatal_with_evidence:
        final_status = "killed"
        aggregation_status = "BLOCKED"
        decision_reasons.append("fatal blocker with cited evidence")
    elif missing_roles or validation_errors or unsupported_fatal:
        final_status = "human_gate"
        aggregation_status = "NEEDS_HUMAN_GATE"
        if missing_roles:
            decision_reasons.append("missing raw review roles: " + ", ".join(missing_roles))
            process_blockers.append(_process_blocker("missing_raw_review", "missing raw review roles: " + ", ".join(missing_roles)))
        if validation_errors:
            decision_reasons.append("raw review validation failed")
            process_blockers.append(_process_blocker("invalid_raw_review", "; ".join(validation_errors[:3])))
        if unsupported_fatal:
            decision_reasons.append("fatal blocker lacks cited evidence and needs human gate")
    elif closest_missing:
        final_status = "revise"
        aggregation_status = "REVISE"
        decision_reasons.append("closest work missing or not Phase 6 ready")
        process_blockers.append(_process_blocker("missing_closest_work", "closest work is required before promotion"))
    elif disagreement:
        final_status = "human_gate"
        aggregation_status = "NEEDS_HUMAN_GATE"
        decision_reasons.append("unresolved reviewer disagreement")
    elif weak_evidence or missing_baseline:
        final_status = "revise"
        aggregation_status = "REVISE"
        if weak_evidence:
            decision_reasons.append("weak or missing evidence confidence")
        if missing_baseline:
            decision_reasons.append("missing direct baseline")
    else:
        final_status = "promoted"
        aggregation_status = "PROMOTE"
        decision_reasons.append("all required reviews crossed blockers")

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "idea_id": idea_id,
        "source_idea_state_id": card.get("state_id", ""),
        "source_idea_card_hash": input_hash(card),
        "final_status": final_status,
        "aggregation_status": aggregation_status,
        "decision_reasons": decision_reasons,
        "review_trace_ids": [trace.get("review_id", "") for trace in traces],
        "reviewer_statuses": reviewer_statuses,
        "missing_review_roles": missing_roles,
        "raw_review_validation_errors": validation_errors,
        "disagreement": disagreement,
        "blockers": blockers + process_blockers,
        "revision_requests": _revision_requests(card, final_status, blockers + process_blockers, decision_reasons),
        "idea_snapshot": _idea_snapshot(card),
    }


def _copy_and_load_raw_reviews(raw_reviews: Path, out_raw: Path) -> dict[tuple[str, str], dict[str, Any]]:
    raw_reviews = raw_reviews.resolve()
    out_raw.mkdir(parents=True, exist_ok=True)
    index: dict[tuple[str, str], dict[str, Any]] = {}
    if not raw_reviews.exists():
        return index
    for source in sorted(raw_reviews.glob("*/*.json")):
        role = source.parent.name
        target = out_raw / role / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        trace = read_json(source)
        idea_id = str(trace.get("idea_id", source.stem))
        index[(str(trace.get("reviewer_role", role)), idea_id)] = trace
    return index


def _trace_errors(trace: dict[str, Any], idea_id: str, evidence_hash: str) -> list[str]:
    schema = load_json(SCHEMA_ROOT / "review_trace.schema.json")
    errors = [error.format() for error in validate_with_schema(trace, schema)]
    if trace.get("idea_id") != idea_id:
        errors.append(f"review idea_id mismatch: expected {idea_id}, got {trace.get('idea_id')}")
    if trace.get("evidence_package_hash") != evidence_hash:
        errors.append(f"evidence_package_hash mismatch for {trace.get('review_id', '<unknown>')}")
    if trace.get("prompt") and trace.get("prompt_hash") != sha256_text(str(trace["prompt"])):
        errors.append(f"prompt_hash mismatch for {trace.get('review_id', '<unknown>')}")
    if trace.get("reviewer_model") == trace.get("generator_model"):
        if trace.get("review_independence_confidence") != "low":
            errors.append("same-model fallback must set review_independence_confidence=low")
        if "same model used for generation and review" not in str(trace.get("fallback_reason", "")):
            errors.append("same-model fallback must explain fallback_reason")
    return errors


def _collect_blockers(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for trace in traces:
        for blocker in trace.get("blockers", []):
            if not isinstance(blocker, dict):
                continue
            blockers.append({**blocker, "review_id": trace.get("review_id", ""), "reviewer_role": trace.get("reviewer_role", "")})
    return blockers


def _is_fatal_with_evidence(blocker: dict[str, Any]) -> bool:
    return (
        blocker.get("severity") == "fatal"
        and blocker.get("evidence_status") == "supported"
        and bool(blocker.get("evidence_ids"))
    )


def _process_blocker(blocker_type: str, explanation: str) -> dict[str, Any]:
    return {
        "blocker_type": blocker_type,
        "severity": "fatal",
        "evidence_status": "not_applicable",
        "evidence_ids": [],
        "explanation": explanation,
        "reviewer_role": "aggregation",
        "review_id": "aggregation",
    }


def _evidence_confidence(card: dict[str, Any]) -> str:
    payload = card.get("roi", {}).get("positive_signals", {}).get("evidence_confidence", {})
    if isinstance(payload, dict):
        return str(payload.get("value", "unknown"))
    return "unknown"


def _revision_requests(
    card: dict[str, Any],
    final_status: str,
    blockers: list[dict[str, Any]],
    reasons: list[str],
) -> list[dict[str, Any]]:
    if final_status not in {"revise", "human_gate"}:
        return []
    requests = [
        {
            "request_type": blocker.get("blocker_type", "review_follow_up"),
            "reason": blocker.get("explanation", ""),
            "source": blocker.get("reviewer_role", "aggregation"),
        }
        for blocker in blockers
    ]
    if not card.get("direct_baselines") and final_status == "revise":
        requests.append(
            {
                "request_type": "direct_baseline",
                "reason": "Add or justify direct baselines before Phase 7 experiment blueprint.",
                "source": "aggregation",
            }
        )
    if not requests:
        requests.append({"request_type": "human_decision", "reason": "; ".join(reasons), "source": "aggregation"})
    return requests


def _idea_snapshot(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "idea_id": card.get("idea_id", ""),
        "title": card.get("title", ""),
        "source_gap_ids": card.get("source_gap_ids", []),
        "evidence_ids": card.get("evidence_ids", []),
        "closest_work_ids": card.get("closest_work_ids", []),
        "direct_baselines": card.get("direct_baselines", []),
        "readiness": card.get("readiness", {}),
        "status": card.get("status", ""),
    }


def _write_status_outputs(out: Path, decisions: list[dict[str, Any]]) -> None:
    for status, filename in FINAL_STATUS_FILES.items():
        write_jsonl(out / filename, [row for row in decisions if row["final_status"] == status])


def _write_review_matrix(path: Path, decisions: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "idea_id",
                "final_status",
                "aggregation_status",
                "review_trace_count",
                "missing_review_roles",
                "fatal_blocker_count",
                "major_blocker_count",
                "reviewer_statuses",
                "tournament_rank",
            ],
        )
        writer.writeheader()
        for row in decisions:
            writer.writerow(
                {
                    "idea_id": row["idea_id"],
                    "final_status": row["final_status"],
                    "aggregation_status": row["aggregation_status"],
                    "review_trace_count": len(row.get("review_trace_ids", [])),
                    "missing_review_roles": ";".join(row.get("missing_review_roles", [])),
                    "fatal_blocker_count": sum(1 for blocker in row.get("blockers", []) if blocker.get("severity") == "fatal"),
                    "major_blocker_count": sum(1 for blocker in row.get("blockers", []) if blocker.get("severity") == "major"),
                    "reviewer_statuses": ";".join(row.get("reviewer_statuses", [])),
                    "tournament_rank": row.get("tournament_rank", ""),
                }
            )


def _write_manifest(
    out: Path,
    idea_ctx: Any,
    decisions: list[dict[str, Any]],
    required_roles: tuple[str, ...],
) -> dict[str, Any]:
    artifacts = [
        _artifact(out, "review_artifact", rel)
        for rel in REVIEW_ARTIFACTS
        if rel != "manifest.json" and (out / rel).exists()
    ]
    artifacts.extend(
        _artifact(out, f"evidence_package:{path.stem}", path.relative_to(out))
        for path in sorted((out / "evidence_packages").glob("*.json"))
    )
    artifacts.extend(
        _artifact(out, f"raw_review:{path.parent.name}:{path.stem}", path.relative_to(out), "review_trace.schema.json")
        for path in sorted((out / "raw").glob("*/*.json"))
    )
    counts = {status: sum(1 for row in decisions if row["final_status"] == status) for status in FINAL_STATUS_FILES}
    manifest_input = {
        "idea_ids": [row["idea_id"] for row in decisions],
        "decision_counts": counts,
        "artifact_hashes": [artifact["sha256"] for artifact in artifacts],
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("review_manifest", manifest_input),
        "created_at": utc_now(),
        "input_hash": input_hash(manifest_input),
        "parent_state_ids": [value for value in [idea_ctx.manifest.get("state_id")] if value],
        "producer": PRODUCER,
        "ideas_path": str(idea_ctx.ideas_dir),
        "required_reviewer_roles": list(required_roles),
        "idea_ids": [row["idea_id"] for row in decisions],
        "decision_counts": counts,
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "aggregation_rule": "fatal_with_evidence -> killed; missing_raw -> human_gate; missing_closest_work -> revise; disagreement -> human_gate; weak_evidence_or_missing_baseline -> revise; else promoted",
        "single_average_score_allowed": False,
        "raw_reviews_preserved": True,
        "tournament_policy": "pairwise_blocker_first_append_only_jsonl",
    }
    write_json(out / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate Phase 6 raw reviews with blocker-first rules.")
    parser.add_argument("--ideas", required=True, type=Path)
    parser.add_argument("--raw-reviews", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--max-ideas", type=int, default=1)
    parser.add_argument("--all-ideas", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = aggregate_reviews(
            ideas=args.ideas,
            raw_reviews=args.raw_reviews,
            out=args.out,
            pack=args.pack,
            max_ideas=args.max_ideas,
            all_ideas=args.all_ideas,
        )
    except Exception as exc:
        print(f"ERROR {exc}")
        return 1
    print(f"[review] aggregated out={result['out']} counts={result['decision_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
