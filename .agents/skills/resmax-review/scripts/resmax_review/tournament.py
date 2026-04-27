from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any

from resmax_core.state import utc_now

from . import PRODUCER


STATUS_PRIORITY = {
    "promoted": 0,
    "revise": 1,
    "human_gate": 2,
    "killed": 3,
}


def rank_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        decisions,
        key=lambda row: (
            STATUS_PRIORITY.get(row.get("final_status", "human_gate"), 9),
            _fatal_count(row),
            len(row.get("blockers", [])),
            row.get("idea_id", ""),
        ),
    )


def build_tournament_events(decisions: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for left, right in combinations(decisions, 2):
        winner = _pairwise_winner(left, right)
        loser = right if winner is left else left
        events.append(
            {
                "schema_version": "0.1.0",
                "created_at": utc_now(),
                "event_type": "pairwise_blocker_decision",
                "producer": PRODUCER,
                "run_id": run_id,
                "left_idea_id": left["idea_id"],
                "right_idea_id": right["idea_id"],
                "winner_idea_id": winner["idea_id"],
                "loser_idea_id": loser["idea_id"],
                "basis": "blocker_first_status_then_fatal_count_then_blocker_count",
                "left_status": left["final_status"],
                "right_status": right["final_status"],
                "left_fatal_blockers": _fatal_count(left),
                "right_fatal_blockers": _fatal_count(right),
            }
        )
    for rank, row in enumerate(rank_decisions(decisions), 1):
        events.append(
            {
                "schema_version": "0.1.0",
                "created_at": utc_now(),
                "event_type": "rank_assignment",
                "producer": PRODUCER,
                "run_id": run_id,
                "idea_id": row["idea_id"],
                "rank": rank,
                "final_status": row["final_status"],
                "basis": "auxiliary_order_only_not_average_score",
            }
        )
    return events


def append_tournament_trace(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    offset = _existing_line_count(path)
    with path.open("a", encoding="utf-8") as f:
        for index, event in enumerate(events, offset + 1):
            f.write(json.dumps({**event, "event_index": index}, ensure_ascii=False, sort_keys=True) + "\n")


def _pairwise_winner(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_key = (STATUS_PRIORITY.get(left.get("final_status", "human_gate"), 9), _fatal_count(left), len(left.get("blockers", [])))
    right_key = (STATUS_PRIORITY.get(right.get("final_status", "human_gate"), 9), _fatal_count(right), len(right.get("blockers", [])))
    return left if left_key <= right_key else right


def _fatal_count(row: dict[str, Any]) -> int:
    return sum(1 for blocker in row.get("blockers", []) if blocker.get("severity") == "fatal")


def _existing_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())
