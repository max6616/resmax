from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now
from resmax_core.validators.common import load_json, validate_with_schema

from . import SCHEMA_ROOT
from .plan_queries import build_query_families, write_query_families


PRODUCER = {"name": "resmax_survey_v2.compile_spec", "version": SCHEMA_VERSION, "run_id": "macro_v2"}
DEFAULT_NON_GOALS = [
    "full-text extraction",
    "final idea generation",
    "strong recommendation",
    "experiment plan",
]
DEFAULT_HUMAN_GATES = [
    "after_macro_survey",
    "before_targeted_full_text",
    "before_idea_generation",
    "before_experiment_planning",
]
DEFAULT_ROI_OBJECTIVES = [
    "publication_upside",
    "novelty_headroom",
    "implementation_reuse",
    "low_compute_cost",
    "benchmark_leverage",
    "review_risk_visibility",
]
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def build_research_spec(
    *,
    intent: str,
    target_venue: str = "",
    timeline: str = "",
    compute_budget: str = "",
    team_size: str = "",
    non_goals: list[str] | None = None,
    parent_state_ids: list[str] | None = None,
) -> dict[str, Any]:
    clean_intent = _require_text(intent, "intent")
    merged_non_goals = _dedupe([*(non_goals or []), *DEFAULT_NON_GOALS])
    inferred = _infer_constraints(clean_intent)
    target_venue = target_venue.strip() or inferred.get("target_venue", "") or "unknown"
    timeline = timeline.strip() or inferred.get("timeline", "") or "unknown"
    compute_budget = compute_budget.strip() or inferred.get("compute_budget", "") or "unknown"
    team_size = team_size.strip() or "unknown"

    unknowns = []
    if target_venue == "unknown":
        unknowns.append("target_venue")
    if timeline == "unknown":
        unknowns.append("timeline")
    if compute_budget == "unknown":
        unknowns.append("compute_budget")
    if team_size == "unknown":
        unknowns.append("team_size")
    unknowns.extend(
        [
            "benchmark_burden",
            "baseline_burden",
            "compute_burden",
            "reviewer_blockers",
            "SOTA_pressure",
        ]
    )

    problem_anchor = _problem_anchor(clean_intent)
    state_input = {
        "raw_intent": clean_intent,
        "problem_anchor": problem_anchor,
        "target_venue": target_venue,
        "timeline": timeline,
        "compute_budget": compute_budget,
        "team_size": team_size,
        "non_goals": merged_non_goals,
        "human_gates": DEFAULT_HUMAN_GATES,
        "roi_objectives": DEFAULT_ROI_OBJECTIVES,
        "unknowns": unknowns,
    }
    state_id = make_state_id("research_spec", state_input)
    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": state_id,
        "created_at": utc_now(),
        "input_hash": input_hash(state_input),
        "parent_state_ids": parent_state_ids or [],
        "producer": PRODUCER,
        "raw_intent": clean_intent,
        "problem_anchor": problem_anchor,
        "target_venue": target_venue,
        "timeline": timeline,
        "compute_budget": compute_budget,
        "team_size": team_size,
        "non_goals": merged_non_goals,
        "human_gates": DEFAULT_HUMAN_GATES,
        "budget_policy": {
            "macro_max_candidates": 100,
            "max_targeted_evidence_candidates": 30,
            "evidence_expansion_requires_human_gate": True,
        },
        "research_question": f"What broad subdirections and rough ROI signals are visible for: {clean_intent}?",
        "objective": "Compile a schema-valid macro survey pack without final ideas or experiment plans.",
        "scope": {
            "included_topics": [problem_anchor],
            "excluded_topics": merged_non_goals,
        },
        "roi_objectives": DEFAULT_ROI_OBJECTIVES,
        "unknowns": _dedupe(unknowns),
        "decision_status": "pending",
    }


def build_source_policy(research_spec: dict[str, Any]) -> dict[str, Any]:
    state_input = {
        "research_spec_id": research_spec["state_id"],
        "policy": "macro_survey_rough_roi_only",
        "disabled": DEFAULT_NON_GOALS,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("source_policy", state_input),
        "created_at": utc_now(),
        "input_hash": input_hash(state_input),
        "parent_state_ids": [research_spec["state_id"]],
        "producer": {"name": "resmax_survey_v2.compile_spec", "version": SCHEMA_VERSION, "run_id": "macro_v2"},
        "research_spec_id": research_spec["state_id"],
        "allowed_source_tiers": [
            "full_text",
            "landing_only",
            "listing_only",
            "metadata_plus_aux",
            "metadata_only",
            "unknown",
        ],
        "allowed_retrieval_modes": ["keyword", "hybrid", "embedding"],
        "disallowed_sources": ["sci_hub", "mineru", "full_text_extraction"],
        "disabled_capabilities": [
            "full_text_extraction",
            "mineru",
            "sci_hub",
            "final_idea_generation",
            "experiment_plan",
        ],
        "claim_support_policy": {
            "rough_roi_only": True,
            "allow_strong_recommendation": False,
            "unknown_must_remain_unknown": True,
        },
        "evidence_defaults": {
            "rough_roi": "weak",
            "benchmark_burden": "unknown",
            "compute_burden": "unknown",
            "baseline_burden": "unknown",
            "reviewer_risk": "unknown",
        },
    }


def write_spec_pack(out_dir: Path, research_spec: dict[str, Any], source_policy: dict[str, Any]) -> dict[str, Path]:
    spec_dir = out_dir / "survey_v2" / "spec"
    spec_dir.mkdir(parents=True, exist_ok=True)
    research_spec_path = spec_dir / "research_spec.json"
    source_policy_path = spec_dir / "source_policy.json"
    query_family_path = spec_dir / "query_families.jsonl"

    _write_json(research_spec_path, research_spec)
    _write_json(source_policy_path, source_policy)
    query_families = build_query_families(research_spec)
    write_query_families(query_family_path, query_families)

    _validate_json(research_spec_path, SCHEMA_ROOT / "research_spec.schema.json")
    _validate_json(source_policy_path, SCHEMA_ROOT / "source_policy.schema.json")
    return {
        "research_spec": research_spec_path,
        "source_policy": source_policy_path,
        "query_families": query_family_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile a Resmax Survey V2 macro ResearchSpec.")
    parser.add_argument("--intent", required=True, help="Natural-language research intent.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output root for survey_v2 artifacts.")
    parser.add_argument("--target-venue", default="", help="Target venue; defaults to unknown.")
    parser.add_argument("--timeline", default="", help="Timeline constraint; defaults to unknown.")
    parser.add_argument("--compute-budget", default="", help="Compute budget; defaults to unknown.")
    parser.add_argument("--team-size", default="", help="Team size; defaults to unknown.")
    parser.add_argument("--non-goal", action="append", default=[], help="Additional non-goal. May be repeated.")
    args = parser.parse_args(argv)

    research_spec = build_research_spec(
        intent=args.intent,
        target_venue=args.target_venue,
        timeline=args.timeline,
        compute_budget=args.compute_budget,
        team_size=args.team_size,
        non_goals=args.non_goal,
    )
    source_policy = build_source_policy(research_spec)
    paths = write_spec_pack(args.out_dir, research_spec, source_policy)
    print(f"[survey-v2] wrote {paths['research_spec']}")
    print(f"[survey-v2] wrote {paths['source_policy']}")
    print(f"[survey-v2] wrote {paths['query_families']}")
    return 0


def _problem_anchor(intent: str) -> str:
    words = [
        part
        for part in re.split(r"[^A-Za-z0-9_+-]+", intent.strip())
        if part and part.lower() not in STOPWORDS
    ]
    if not words:
        return intent.strip()
    return " ".join(words[:12])


def _infer_constraints(intent: str) -> dict[str, str]:
    return {
        "target_venue": _extract_labeled_value(intent, ("target venue", "venue")),
        "compute_budget": _extract_labeled_value(intent, ("compute budget", "budget")),
        "timeline": _extract_labeled_value(intent, ("timeline", "time budget")),
    }


def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        pattern = rf"(?i)\b{re.escape(label)}\s*:\s*([^.;\n]+)"
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _require_text(value: str, name: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{name} must not be empty")
    return clean


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_json(path: Path, schema_path: Path) -> None:
    errors = validate_with_schema(load_json(path), load_json(schema_path))
    if errors:
        detail = "\n".join(error.format() for error in errors)
        raise ValueError(f"{path} failed schema validation:\n{detail}")


if __name__ == "__main__":
    raise SystemExit(main())
