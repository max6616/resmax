from __future__ import annotations

from typing import Any


def lineage_for_gap(gap: dict[str, Any], status: str) -> dict[str, Any]:
    gap_type = gap.get("gap_type", "unknown")
    operator = {
        "resource_arbitrage": "resource_arbitrage_compile",
        "benchmark_blind_spot": "benchmark_blindspot_compile",
        "method_transfer": "method_transfer_compile",
        "reviewer_pressure": "reviewer_pressure_constraint_compile",
        "missing_evidence": "evidence_gap_hold",
    }.get(gap_type, "gap_driven_compile")
    return {
        "parent_gap_ids": [gap.get("gap_id", "")] if gap.get("gap_id") else [],
        "parent_idea_ids": [],
        "mutation_operator": operator,
        "mutation_reason": gap.get("description", ""),
        "status": _lineage_status(status),
    }


def build_lineage_graph(ideas: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "nodes": [
            {
                "idea_id": idea["idea_id"],
                "parent_gap_ids": idea.get("lineage", {}).get("parent_gap_ids", []),
                "parent_idea_ids": idea.get("lineage", {}).get("parent_idea_ids", []),
                "mutation_operator": idea.get("lineage", {}).get("mutation_operator", ""),
                "mutation_reason": idea.get("lineage", {}).get("mutation_reason", ""),
                "status": idea.get("lineage", {}).get("status", "refine"),
            }
            for idea in ideas
        ],
        "edges": [
            {"source_id": gap_id, "target_id": idea["idea_id"], "relation": "gap_to_idea"}
            for idea in ideas
            for gap_id in idea.get("source_gap_ids", [])
        ],
    }


def _lineage_status(status: str) -> str:
    if status == "phase6_ready":
        return "proceed"
    if status in {"insufficient_evidence", "duplicate_risk"}:
        return "reject"
    return "refine"
