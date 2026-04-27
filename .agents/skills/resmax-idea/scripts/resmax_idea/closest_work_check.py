from __future__ import annotations

from typing import Any

from .load_pack import PackContext


def build_closest_work_check(ctx: PackContext, idea: dict[str, Any]) -> dict[str, Any]:
    closest_ids = list(idea.get("closest_work_ids", []))
    covered = [
        {
            "paper_id": paper_id,
            "title": ctx.title_for_paper(paper_id),
            "roles": sorted(ctx.roles_for_paper(paper_id)),
        }
        for paper_id in closest_ids
    ]
    remaining_delta = idea.get("core_delta", "")
    phase6_ready = bool(closest_ids) and bool(idea.get("source_gap_ids")) and bool(idea.get("evidence_ids"))
    return {
        "idea_id": idea["idea_id"],
        "source_gap_ids": idea.get("source_gap_ids", []),
        "closest_work_ids": closest_ids,
        "covered_by_closest_work": covered,
        "remaining_delta": remaining_delta,
        "novelty_proximity": "delta_stated_needs_review" if closest_ids else "missing_closest_work",
        "phase6_review_ready": phase6_ready,
        "failure_reason": "" if phase6_ready else "closest_work_or_evidence_missing",
    }
