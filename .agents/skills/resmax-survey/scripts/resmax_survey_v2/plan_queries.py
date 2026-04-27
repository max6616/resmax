from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now
from resmax_core.validators.common import load_json, validate_with_schema

from . import ROLE_ORDER, SCHEMA_ROOT


ROLE_DEFINITIONS = {
    "direct_baseline": {
        "need": "Find closest work that directly attacks the stated problem or task.",
        "suffixes": ["baseline method", "closest work", "task benchmark"],
    },
    "method_donor": {
        "need": "Find reusable methods from adjacent areas that may transfer into the target direction.",
        "suffixes": ["diffusion transformer adaptation", "representation editing transfer"],
    },
    "benchmark_opportunity": {
        "need": "Find benchmark gaps, evaluation settings, and datasets that could create leverage.",
        "suffixes": ["benchmark evaluation dataset", "low compute benchmark opportunity"],
    },
    "implementation_reference": {
        "need": "Find papers likely to provide code, datasets, or pretrained weights for fast reuse.",
        "suffixes": ["code implementation repository", "open source pretrained weights dataset"],
    },
    "negative_evidence": {
        "need": "Find failure modes, limitations, or negative results that constrain the direction.",
        "suffixes": ["failure limitation negative result", "ablation weakness robustness"],
    },
    "reviewer_risk": {
        "need": "Find objections reviewers might raise: novelty, baseline strength, compute burden, or evaluation weakness.",
        "suffixes": ["novelty baseline compute burden", "review risk limitation"],
    },
    "survey_or_taxonomy": {
        "need": "Find survey, taxonomy, or overview papers that map adjacent subfields.",
        "suffixes": ["survey taxonomy overview", "comprehensive review"],
    },
}


def build_query_families(research_spec: dict[str, Any]) -> list[dict[str, Any]]:
    intent = research_spec["raw_intent"]
    anchor = research_spec["problem_anchor"]
    families: list[dict[str, Any]] = []
    for role in ROLE_ORDER:
        role_def = ROLE_DEFINITIONS[role]
        queries = []
        for idx, suffix in enumerate(role_def["suffixes"], 1):
            query_text = f"{anchor} {suffix}".strip()
            queries.append(
                {
                    "query_id": f"q_{role}_{idx}",
                    "text": query_text,
                    "query_type": "semantic",
                    "intent": f"{role_def['need']} Seed intent: {intent}",
                }
            )
        state_input = {
            "research_spec_id": research_spec["state_id"],
            "family_role": role,
            "queries": queries,
            "information_need": role_def["need"],
        }
        families.append(
            {
                "schema_version": SCHEMA_VERSION,
                "state_id": make_state_id("query_family", state_input),
                "created_at": utc_now(),
                "input_hash": input_hash(state_input),
                "parent_state_ids": [research_spec["state_id"]],
                "producer": {"name": "resmax_survey_v2.plan_queries", "version": SCHEMA_VERSION, "run_id": "macro_v2"},
                "research_spec_id": research_spec["state_id"],
                "family_role": role,
                "information_need": role_def["need"],
                "retrieval_mode": "hybrid",
                "filters": {},
                "queries": queries,
                "evidence_status": "unknown",
            }
        )
    return families


def write_query_families(path: Path, families: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = load_json(SCHEMA_ROOT / "query_family.schema.json")
    lines = []
    for family in families:
        errors = validate_with_schema(family, schema)
        if errors:
            detail = "\n".join(error.format() for error in errors)
            raise ValueError(f"query family failed schema validation:\n{detail}")
        lines.append(json.dumps(family, ensure_ascii=False, sort_keys=True))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_query_families(path: Path) -> list[dict[str, Any]]:
    families: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                families.append(json.loads(raw))
    return families


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan role-based query families for a ResearchSpec.")
    parser.add_argument("--spec", required=True, type=Path, help="Path to research_spec.json.")
    parser.add_argument("--out", required=True, type=Path, help="Path to query_families.jsonl.")
    args = parser.parse_args(argv)

    research_spec = json.loads(args.spec.read_text(encoding="utf-8"))
    families = build_query_families(research_spec)
    write_query_families(args.out, families)
    print(f"[survey-v2] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
