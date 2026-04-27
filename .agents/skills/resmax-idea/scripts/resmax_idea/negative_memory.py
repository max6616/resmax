from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id, stable_hash
from resmax_core.state import SCHEMA_VERSION, utc_now

from . import PRODUCER


MEMORY_PRODUCER = {**PRODUCER, "run_id": "phase7"}

MEMORY_FILES = (
    "negative_memory.jsonl",
    "reviewer_blockers.jsonl",
    "failed_gap_paths.jsonl",
    "infeasible_experiments.jsonl",
)


def write_negative_memory(*, reviews: Path, experiment_plan: Path, memory: Path) -> dict[str, Any]:
    reviews_ctx = _load_reviews(reviews)
    blueprint = _load_blueprint(experiment_plan)
    memory.mkdir(parents=True, exist_ok=True)

    rows = _memory_rows(reviews_ctx, blueprint)
    append_summary = {
        name: _append_unique(memory / name, rows.get(name, []))
        for name in MEMORY_FILES
    }
    total_appended = sum(item["appended"] for item in append_summary.values())
    total_skipped = sum(item["skipped_duplicates"] for item in append_summary.values())
    return {
        "memory_dir": str(memory),
        "appended": total_appended,
        "skipped_duplicates": total_skipped,
        "files": append_summary,
    }


def _memory_rows(reviews_ctx: dict[str, Any], blueprint: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    negative: list[dict[str, Any]] = []
    reviewer_blockers: list[dict[str, Any]] = []
    failed_gap_paths: list[dict[str, Any]] = []
    infeasible_experiments: list[dict[str, Any]] = []

    for decision in reviews_ctx["killed"]:
        idea_id = str(decision.get("idea_id", ""))
        snapshot = decision.get("idea_snapshot", {}) if isinstance(decision.get("idea_snapshot"), dict) else {}
        blockers = [blocker for blocker in decision.get("blockers", []) if isinstance(blocker, dict)]
        reason = _reason_from_decision(decision, "fatal blocker killed the idea")
        evidence_ids = _evidence_ids(blockers, snapshot)
        negative.append(
            _negative_memory_record(
                subject_id=idea_id,
                subject_type="idea",
                reason_type="fatal_blocker_kill",
                reason=reason,
                evidence_status=_best_evidence_status(blockers, default="supported"),
                evidence_card_ids=evidence_ids,
                decision_status="killed",
                parent_state_ids=_parent_state_ids(decision),
                source_review_ids=decision.get("review_trace_ids", []),
                source_gap_ids=snapshot.get("source_gap_ids", []),
            )
        )
        for blocker in blockers:
            reviewer_blockers.append(_reviewer_blocker_record(idea_id, blocker, decision, snapshot))
        for gap_id in snapshot.get("source_gap_ids", []):
            failed_gap_paths.append(_failed_gap_record(gap_id, idea_id, "fatal_blocker_kill", reason, evidence_ids, decision))

    for decision in reviews_ctx["revise"] + reviews_ctx["human_gate"]:
        idea_id = str(decision.get("idea_id", ""))
        snapshot = decision.get("idea_snapshot", {}) if isinstance(decision.get("idea_snapshot"), dict) else {}
        blockers = [blocker for blocker in decision.get("blockers", []) if isinstance(blocker, dict)]
        reason = _reason_from_decision(decision, "blocked before experiment blueprint")
        if _is_memory_worthy_blocked_path(decision, blockers):
            negative.append(
                _negative_memory_record(
                    subject_id=idea_id,
                    subject_type="idea",
                    reason_type="blocked_before_phase7",
                    reason=reason,
                    evidence_status=_best_evidence_status(blockers, default="insufficient_evidence"),
                    evidence_card_ids=_evidence_ids(blockers, snapshot),
                    decision_status="needs_revision",
                    parent_state_ids=_parent_state_ids(decision),
                    source_review_ids=decision.get("review_trace_ids", []),
                    source_gap_ids=snapshot.get("source_gap_ids", []),
                )
            )
        for blocker in blockers:
            reviewer_blockers.append(_reviewer_blocker_record(idea_id, blocker, decision, snapshot))

    for block in blueprint.get("experiment_blocks", []):
        if not isinstance(block, dict):
            continue
        status = block.get("execution_status", "")
        budget_status = block.get("estimated_cost", {}).get("budget_status", "")
        if status in {"insufficient_evidence", "human_gate_required"} or budget_status == "over_budget":
            reason_type = "over_budget_experiment" if budget_status == "over_budget" else str(status or "blocked_experiment")
            reason = _experiment_reason(block)
            evidence_ids = block.get("negative_memory_if_rejected", {}).get("evidence_card_ids", [])
            negative.append(
                _negative_memory_record(
                    subject_id=str(block.get("experiment_id", "")),
                    subject_type="experiment",
                    reason_type=reason_type,
                    reason=reason,
                    evidence_status="insufficient_evidence" if status == "insufficient_evidence" else "unknown",
                    evidence_card_ids=[str(item) for item in evidence_ids if item],
                    decision_status="needs_revision",
                    parent_state_ids=[str(block.get("source_idea_state_id", ""))] if block.get("source_idea_state_id") else [],
                    source_review_ids=block.get("source_review_trace_ids", []),
                    source_gap_ids=block.get("negative_memory_if_rejected", {}).get("source_gap_ids", []),
                )
            )
            infeasible_experiments.append(_infeasible_experiment_record(block, reason_type, reason))

    return {
        "negative_memory.jsonl": _dedupe_rows(negative),
        "reviewer_blockers.jsonl": _dedupe_rows(reviewer_blockers),
        "failed_gap_paths.jsonl": _dedupe_rows(failed_gap_paths),
        "infeasible_experiments.jsonl": _dedupe_rows(infeasible_experiments),
    }


def _negative_memory_record(
    *,
    subject_id: str,
    subject_type: str,
    reason_type: str,
    reason: str,
    evidence_status: str,
    evidence_card_ids: list[str],
    decision_status: str,
    parent_state_ids: list[str],
    source_review_ids: list[str],
    source_gap_ids: list[str],
) -> dict[str, Any]:
    dedupe_key = _dedupe_key("negative", subject_type, subject_id, reason_type, source_gap_ids)
    core = {
        "dedupe_key": dedupe_key,
        "subject_id": subject_id,
        "subject_type": subject_type,
        "reason_type": reason_type,
        "reason": _safe_reason(reason),
        "evidence_card_ids": _clean_ids(evidence_card_ids),
        "decision_status": decision_status,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("negative_memory", core),
        "created_at": utc_now(),
        "input_hash": input_hash(core),
        "parent_state_ids": _clean_ids(parent_state_ids),
        "producer": MEMORY_PRODUCER,
        "memory_id": "memory:" + stable_hash(core)[:16],
        "subject_id": subject_id,
        "subject_type": subject_type,
        "reason": core["reason"],
        "evidence_status": evidence_status,
        "evidence_card_ids": core["evidence_card_ids"],
        "decision_status": decision_status,
        "dedupe_key": dedupe_key,
        "reason_type": reason_type,
        "source_review_ids": _clean_ids(source_review_ids),
        "source_gap_ids": _clean_ids(source_gap_ids),
    }


def _reviewer_blocker_record(
    idea_id: str,
    blocker: dict[str, Any],
    decision: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    reason_type = str(blocker.get("blocker_type", "review_blocker"))
    dedupe_key = _dedupe_key("reviewer_blocker", "idea", idea_id, reason_type, blocker.get("evidence_ids", []))
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "dedupe_key": dedupe_key,
        "idea_id": idea_id,
        "source_gap_ids": _clean_ids(snapshot.get("source_gap_ids", [])),
        "review_id": blocker.get("review_id", ""),
        "reviewer_role": blocker.get("reviewer_role", ""),
        "blocker_type": reason_type,
        "severity": blocker.get("severity", "unknown"),
        "evidence_status": blocker.get("evidence_status", "unknown"),
        "evidence_ids": _clean_ids(blocker.get("evidence_ids", [])),
        "explanation": _safe_reason(str(blocker.get("explanation", ""))),
        "decision_status": decision.get("final_status", "unknown"),
    }


def _failed_gap_record(
    gap_id: str,
    idea_id: str,
    reason_type: str,
    reason: str,
    evidence_ids: list[str],
    decision: dict[str, Any],
) -> dict[str, Any]:
    dedupe_key = _dedupe_key("failed_gap", "gap", gap_id, reason_type, [idea_id])
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "dedupe_key": dedupe_key,
        "gap_id": gap_id,
        "idea_id": idea_id,
        "reason_type": reason_type,
        "reason": _safe_reason(reason),
        "evidence_card_ids": _clean_ids(evidence_ids),
        "decision_status": decision.get("final_status", "unknown"),
    }


def _infeasible_experiment_record(block: dict[str, Any], reason_type: str, reason: str) -> dict[str, Any]:
    experiment_id = str(block.get("experiment_id", ""))
    idea_id = str(block.get("idea_id", ""))
    dedupe_key = _dedupe_key("infeasible_experiment", "experiment", experiment_id, reason_type, [idea_id])
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "dedupe_key": dedupe_key,
        "experiment_id": experiment_id,
        "idea_id": idea_id,
        "reason_type": reason_type,
        "reason": _safe_reason(reason),
        "execution_status": block.get("execution_status", "unknown"),
        "budget_status": block.get("estimated_cost", {}).get("budget_status", "unknown"),
        "required_follow_up": _required_follow_up(block),
    }


def _append_unique(path: Path, rows: list[dict[str, Any]]) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_keys = _existing_keys(path)
    appended = 0
    skipped = 0
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            key = str(row.get("dedupe_key") or _fallback_key(row))
            if key in existing_keys:
                skipped += 1
                continue
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            existing_keys.add(key)
            appended += 1
    return {"appended": appended, "skipped_duplicates": skipped}


def _existing_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                keys.add(str(row.get("dedupe_key") or _fallback_key(row)))
    return keys


def _fallback_key(row: dict[str, Any]) -> str:
    payload = {
        "subject_id": row.get("subject_id") or row.get("idea_id") or row.get("gap_id") or row.get("experiment_id"),
        "reason_type": row.get("reason_type") or row.get("blocker_type"),
        "reason": row.get("reason") or row.get("explanation"),
    }
    return "fallback:" + stable_hash(payload)


def _load_reviews(path: Path) -> dict[str, Any]:
    return {
        "killed": _read_jsonl(path / "killed_ideas.jsonl"),
        "revise": _read_jsonl(path / "revise_ideas.jsonl"),
        "human_gate": _read_jsonl(path / "human_gate_ideas.jsonl"),
    }


def _load_blueprint(path: Path) -> dict[str, Any]:
    target = path / "experiment_blueprint.json" if path.is_dir() else path
    return _read_json(target)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {path}:{line_no}")
            rows.append(payload)
    return rows


def _reason_from_decision(decision: dict[str, Any], fallback: str) -> str:
    reasons = [str(item) for item in decision.get("decision_reasons", []) if item]
    blockers = [
        str(blocker.get("explanation", ""))
        for blocker in decision.get("blockers", [])
        if isinstance(blocker, dict) and blocker.get("explanation")
    ]
    return "; ".join(reasons + blockers) or fallback


def _experiment_reason(block: dict[str, Any]) -> str:
    parts = [
        str(block.get("failure_interpretation", "")),
        "budget_status=" + str(block.get("estimated_cost", {}).get("budget_status", "unknown")),
    ]
    return "; ".join(part for part in parts if part)


def _is_memory_worthy_blocked_path(decision: dict[str, Any], blockers: list[dict[str, Any]]) -> bool:
    reasons = " ".join(str(item).lower() for item in decision.get("decision_reasons", []))
    if any(term in reasons for term in ("baseline", "closest work", "missing raw review", "disagreement")):
        return True
    return any(str(blocker.get("severity")) in {"fatal", "major"} for blocker in blockers)


def _evidence_ids(blockers: list[dict[str, Any]], snapshot: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for blocker in blockers:
        ids.extend(str(item) for item in blocker.get("evidence_ids", []) if item)
    ids.extend(str(item) for item in snapshot.get("evidence_ids", []) if item)
    return _clean_ids(ids)


def _best_evidence_status(blockers: list[dict[str, Any]], default: str) -> str:
    statuses = {str(blocker.get("evidence_status", "")) for blocker in blockers}
    for status in ("supported", "mixed", "insufficient_evidence", "unknown", "not_applicable"):
        if status in statuses:
            return status
    return default


def _parent_state_ids(decision: dict[str, Any]) -> list[str]:
    values = [str(decision.get("source_idea_state_id", ""))]
    values.extend(str(item) for item in decision.get("review_trace_ids", []) if item)
    return _clean_ids(values)


def _required_follow_up(block: dict[str, Any]) -> list[str]:
    follow_up: list[str] = []
    follow_up.extend(block.get("baseline", {}).get("follow_up", []))
    follow_up.extend(block.get("dataset", {}).get("follow_up", []))
    if block.get("metric", {}).get("primary_metric") == "unknown_needs_followup":
        follow_up.append("define primary metric")
    return _clean_ids([str(item) for item in follow_up if item])


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("dedupe_key") or _fallback_key(row))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _dedupe_key(namespace: str, subject_type: str, subject_id: str, reason_type: str, refs: list[Any]) -> str:
    payload = {
        "namespace": namespace,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reason_type": reason_type,
        "refs": _clean_ids([str(item) for item in refs if item]),
    }
    return f"{namespace}:" + stable_hash(payload)[:24]


def _safe_reason(reason: str) -> str:
    banned = ("token", "secret", "api_key", "apikey", "password")
    lowered = reason.lower()
    if any(term in lowered for term in banned):
        return "[redacted sensitive-looking failure reason]"
    return " ".join(reason.split())[:800]


def _clean_ids(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append Phase 7 structured negative memory.")
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument("--experiment-plan", required=True, type=Path)
    parser.add_argument("--memory", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = write_negative_memory(reviews=args.reviews, experiment_plan=args.experiment_plan, memory=args.memory)
    except Exception as exc:
        print(f"ERROR {exc}")
        return 1
    print(
        "[idea] wrote negative_memory "
        f"appended={result['appended']} skipped_duplicates={result['skipped_duplicates']} dir={result['memory_dir']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
