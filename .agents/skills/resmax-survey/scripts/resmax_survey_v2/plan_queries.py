from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now
from resmax_core.validators.common import load_json, validate_with_schema

from . import ROLE_ORDER, SCHEMA_ROOT


AGENT_QUERY_PLANNER_PROMPT = """You are generating retrieval queries for a research survey system.

Input:
- raw_intent: original user research goal
- target roles:
  - direct_baseline
  - method_donor
  - benchmark_opportunity
  - implementation_reference
  - negative_evidence
  - reviewer_risk
  - survey_or_taxonomy

Generate high-quality retrieval queries.

Rules:
1. Preserve domain-specific concepts from raw_intent.
2. Separate semantic embedding text from keyword search terms.
3. Do not include noisy resource numbers unless they affect retrieval meaning.
4. Include synonyms and spelling variants.
5. For each role, generate 2-4 queries.
6. Each query must have required concept groups and boost phrases.
7. Each query must be traceable: semantic_text plus generation_reason must contain at least two meaningful terms from raw_intent or search_profile. Prefer core_topic/entities such as 4DGS, 3DGS, Gaussian Splatting, dynamic scenes, editing, real-time, feed-forward, temporal consistency, action editing, public datasets, and benchmark terms when present.
8. Avoid generic queries like "evaluation metrics for 3D editing" unless the query also carries the user's concrete domain or objective terms.
9. Output strict JSON matching the schema.
"""

ROLE_INFORMATION_NEEDS = {
    "direct_baseline": "Find closest work that directly attacks the stated problem or task.",
    "method_donor": "Find reusable methods from adjacent areas that may transfer into the target direction.",
    "benchmark_opportunity": "Find benchmark gaps, evaluation settings, and datasets that could create leverage.",
    "implementation_reference": "Find papers likely to provide code, datasets, or pretrained weights for fast reuse.",
    "negative_evidence": "Find failure modes, limitations, or negative results that constrain the direction.",
    "reviewer_risk": "Find objections reviewers might raise: novelty, baseline strength, compute burden, or evaluation weakness.",
    "survey_or_taxonomy": "Find survey, taxonomy, or overview papers that map adjacent subfields.",
}
NOISY_RESOURCE_RE = re.compile(
    r"\b(?:\d+\s*(?:x|gpu|gpus|rtx|week|weeks|day|days|month|months|researcher|researchers)|rtx\s*\d+|\d{4,5})\b",
    re.I,
)


def build_query_planner_request(research_spec: dict[str, Any]) -> dict[str, Any]:
    raw_intent = _require_text(research_spec.get("raw_intent", ""), "raw_intent")
    search_profile = research_spec.get("search_profile")
    if not isinstance(search_profile, dict) or not search_profile.get("core_topic"):
        raise ValueError("research_spec.search_profile is required before query planning")
    return {
        "schema_version": SCHEMA_VERSION,
        "request_type": "subagent_query_planning",
        "planner_prompt": AGENT_QUERY_PLANNER_PROMPT,
        "raw_intent": raw_intent,
        "search_profile": search_profile,
        "traceability_terms": _planner_traceability_terms(search_profile),
        "target_roles": list(ROLE_ORDER),
        "role_information_needs": ROLE_INFORMATION_NEEDS,
        "output_contract": {
            "schema_version": SCHEMA_VERSION,
            "shape": {
                "schema_version": SCHEMA_VERSION,
                "raw_intent": raw_intent,
                "query_families": [
                    {
                        "family_role": "<one target role>",
                        "information_need": "<why this family exists>",
                        "retrieval_mode": "hybrid",
                        "filters": {},
                        "queries": [
                            {
                                "query_id": "q_<role>_<n>",
                                "semantic_text": "<embedding query>",
                                "keyword_query": {
                                    "required_concepts": [["<synonym>", "<variant>"], ["<required concept>"]],
                                    "boost_phrases": ["<exact phrase>"],
                                    "optional_terms": ["<term>"],
                                },
                                "query_type": "semantic_and_keyword",
                                "generation_reason": "<traceable reason grounded in raw_intent>",
                            }
                        ],
                    }
                ],
            },
            "requirements": [
                "Return only JSON; no markdown fences or prose.",
                "Generate 2-4 queries per role.",
                "Every query must have semantic_text, keyword_query.required_concepts, keyword_query.boost_phrases, and generation_reason.",
                "Every query must be traceable to raw_intent/search_profile: semantic_text plus generation_reason should include at least two meaningful traceability terms from core_topic, entities, desired_properties, constraints, or raw_intent.",
                "For broad benchmark/evaluation queries, include the concrete target domain or desired property (for example 4DGS/Gaussian/dynamic scene editing, temporal consistency, action editing accuracy, public benchmarks, qualitative visualization).",
                "Do not perform retrieval.",
                "Do not include noisy resource numbers such as GPU count, GPU model, or timeline unless retrieval meaning depends on them.",
            ],
        },
    }


def write_query_planner_request(request_path: Path, prompt_path: Path, request: dict[str, Any]) -> None:
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    prompt_path.write_text(_render_subagent_prompt(request), encoding="utf-8")


def normalize_agent_query_families(research_spec: dict[str, Any], agent_output: dict[str, Any]) -> list[dict[str, Any]]:
    _validate_agent_output(research_spec, agent_output)
    families: list[dict[str, Any]] = []
    for raw_family in agent_output["query_families"]:
        role = raw_family["family_role"]
        queries = [_normalize_query(role, idx, query) for idx, query in enumerate(raw_family["queries"], 1)]
        state_input = {
            "research_spec_id": research_spec["state_id"],
            "family_role": role,
            "raw_intent": research_spec["raw_intent"],
            "search_profile": research_spec["search_profile"],
            "queries": queries,
            "information_need": raw_family["information_need"],
            "planner_prompt": AGENT_QUERY_PLANNER_PROMPT,
            "agent_output_hash": input_hash(agent_output),
        }
        families.append(
            {
                "schema_version": SCHEMA_VERSION,
                "state_id": make_state_id("query_family", state_input),
                "created_at": utc_now(),
                "input_hash": input_hash(state_input),
                "parent_state_ids": [research_spec["state_id"]],
                "producer": {"name": "resmax_survey_v2.plan_queries.subagent", "version": SCHEMA_VERSION, "run_id": "macro_v2"},
                "research_spec_id": research_spec["state_id"],
                "family_role": role,
                "information_need": raw_family["information_need"],
                "retrieval_mode": raw_family.get("retrieval_mode", "hybrid"),
                "filters": raw_family.get("filters", {}),
                "planner": {
                    "prompt": AGENT_QUERY_PLANNER_PROMPT,
                    "raw_intent": research_spec["raw_intent"],
                    "search_profile": research_spec["search_profile"],
                },
                "queries": queries,
                "evidence_status": "unknown",
            }
        )
    families.sort(key=lambda family: ROLE_ORDER.index(family["family_role"]))
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
    parser = argparse.ArgumentParser(description="Validate subagent-generated query families for a ResearchSpec.")
    parser.add_argument("--spec", required=True, type=Path, help="Path to research_spec.json.")
    parser.add_argument("--out", type=Path, default=None, help="Path to write final query_families.jsonl.")
    parser.add_argument("--agent-output", type=Path, default=None, help="Strict JSON produced by the query-planning subagent.")
    parser.add_argument("--emit-request", action="store_true", help="Write the subagent request/prompt without query generation.")
    parser.add_argument("--request-out", type=Path, default=None, help="Path to query_planner_request.json.")
    parser.add_argument("--prompt-out", type=Path, default=None, help="Path to query_planner_prompt.md.")
    args = parser.parse_args(argv)

    research_spec = json.loads(args.spec.read_text(encoding="utf-8"))
    if args.emit_request:
        request = build_query_planner_request(research_spec)
        request_path = args.request_out or args.spec.parent / "query_planner_request.json"
        prompt_path = args.prompt_out or args.spec.parent / "query_planner_prompt.md"
        write_query_planner_request(request_path, prompt_path, request)
        print(f"[survey-v2] wrote {request_path}")
        print(f"[survey-v2] wrote {prompt_path}")
        return 0

    if args.agent_output is None or args.out is None:
        raise SystemExit("ERROR plan-queries requires --agent-output and --out; no deterministic fallback is available")
    agent_output = json.loads(args.agent_output.read_text(encoding="utf-8"))
    families = normalize_agent_query_families(research_spec, agent_output)
    write_query_families(args.out, families)
    print(f"[survey-v2] wrote {args.out}")
    return 0


def _render_subagent_prompt(request: dict[str, Any]) -> str:
    return "\n".join(
        [
            request["planner_prompt"],
            "",
            "Use this exact input JSON:",
            "```json",
            json.dumps(
                {
                    "raw_intent": request["raw_intent"],
                    "search_profile": request["search_profile"],
                    "traceability_terms": request["traceability_terms"],
                    "target_roles": request["target_roles"],
                    "role_information_needs": request["role_information_needs"],
                    "output_contract": request["output_contract"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            "Return only strict JSON with top-level schema_version, raw_intent, and query_families.",
        ]
    ) + "\n"


def _validate_agent_output(research_spec: dict[str, Any], payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("agent output must be a JSON object")
    schema_errors = validate_with_schema(payload, load_json(SCHEMA_ROOT / "query_planner_agent_output.schema.json"))
    if schema_errors:
        detail = "\n".join(error.format() for error in schema_errors)
        raise ValueError(f"agent output failed schema validation:\n{detail}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"agent output schema_version must be {SCHEMA_VERSION}")
    if payload.get("raw_intent") != research_spec.get("raw_intent"):
        raise ValueError("agent output raw_intent must exactly match research_spec.raw_intent")
    families = payload.get("query_families")
    if not isinstance(families, list):
        raise ValueError("agent output query_families must be a list")
    roles = [family.get("family_role") for family in families if isinstance(family, dict)]
    if sorted(roles) != sorted(ROLE_ORDER):
        raise ValueError(f"agent output must include exactly these roles once: {list(ROLE_ORDER)}")
    if len(set(roles)) != len(roles):
        raise ValueError("agent output has duplicate family_role values")
    for family in families:
        _validate_raw_family(research_spec, family)


def _validate_raw_family(research_spec: dict[str, Any], family: Any) -> None:
    if not isinstance(family, dict):
        raise ValueError("each query family must be an object")
    role = family.get("family_role")
    if role not in ROLE_ORDER:
        raise ValueError(f"invalid family_role: {role!r}")
    if not str(family.get("information_need", "")).strip():
        raise ValueError(f"{role} missing information_need")
    if family.get("retrieval_mode", "hybrid") != "hybrid":
        raise ValueError(f"{role} retrieval_mode must be hybrid")
    queries = family.get("queries")
    if not isinstance(queries, list) or not 2 <= len(queries) <= 4:
        raise ValueError(f"{role} must contain 2-4 queries")
    for idx, query in enumerate(queries, 1):
        _validate_raw_query(research_spec, role, idx, query)


def _validate_raw_query(research_spec: dict[str, Any], role: str, idx: int, query: Any) -> None:
    if not isinstance(query, dict):
        raise ValueError(f"{role} query {idx} must be an object")
    semantic_text = str(query.get("semantic_text", "")).strip()
    reason = str(query.get("generation_reason", "")).strip()
    if not semantic_text:
        raise ValueError(f"{role} query {idx} missing semantic_text")
    if not reason:
        raise ValueError(f"{role} query {idx} missing generation_reason")
    if query.get("query_type") != "semantic_and_keyword":
        raise ValueError(f"{role} query {idx} query_type must be semantic_and_keyword")
    if _has_noisy_resource_terms(semantic_text):
        raise ValueError(f"{role} query {idx} semantic_text contains noisy resource terms")
    if not _traces_to_intent(research_spec, semantic_text, reason):
        raise ValueError(f"{role} query {idx} is not traceable to raw_intent/search_profile")
    keyword_query = query.get("keyword_query")
    if not isinstance(keyword_query, dict):
        raise ValueError(f"{role} query {idx} missing keyword_query")
    required = keyword_query.get("required_concepts")
    boosts = keyword_query.get("boost_phrases")
    if not isinstance(required, list) or not required:
        raise ValueError(f"{role} query {idx} keyword_query.required_concepts must be non-empty")
    if not isinstance(boosts, list) or not boosts:
        raise ValueError(f"{role} query {idx} keyword_query.boost_phrases must be non-empty")
    for group in required:
        if not isinstance(group, list) or not any(str(term).strip() for term in group):
            raise ValueError(f"{role} query {idx} has an empty required concept group")
        if any(_has_noisy_resource_terms(str(term)) for term in group):
            raise ValueError(f"{role} query {idx} required_concepts contains noisy resource terms")
    if any(_has_noisy_resource_terms(str(phrase)) for phrase in boosts):
        raise ValueError(f"{role} query {idx} boost_phrases contains noisy resource terms")


def _normalize_query(role: str, idx: int, query: dict[str, Any]) -> dict[str, Any]:
    query_id = str(query.get("query_id") or f"q_{role}_{idx}").strip()
    normalized = {
        "query_id": query_id,
        "semantic_text": str(query["semantic_text"]).strip(),
        "keyword_query": {
            "required_concepts": _normalize_concept_groups(query["keyword_query"]["required_concepts"]),
            "boost_phrases": _normalize_list(query["keyword_query"]["boost_phrases"]),
            "optional_terms": _normalize_list(query["keyword_query"].get("optional_terms", [])),
        },
        "query_type": "semantic_and_keyword",
        "generation_reason": str(query["generation_reason"]).strip(),
    }
    if "text" in query:
        normalized["text"] = str(query["text"]).strip()
    return normalized


def _normalize_concept_groups(groups: list[Any]) -> list[list[str]]:
    return [_normalize_list(group) for group in groups]


def _normalize_list(values: Any) -> list[str]:
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []
    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        clean = re.sub(r"\s+", " ", str(value).strip())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def _traces_to_intent(research_spec: dict[str, Any], semantic_text: str, generation_reason: str) -> bool:
    text = f"{semantic_text} {generation_reason}".lower()
    terms = _traceability_terms(research_spec)
    return sum(1 for term in terms if _term_in_text(term, text)) >= 2


def _traceability_terms(research_spec: dict[str, Any]) -> list[str]:
    profile = research_spec.get("search_profile", {})
    if not isinstance(profile, dict):
        profile = {}
    chunks = [
        str(research_spec.get("raw_intent", "")),
        str(profile.get("core_topic", "")),
        " ".join(str(value) for value in profile.get("entities", []) if value),
        " ".join(str(value) for value in profile.get("desired_properties", []) if value),
        " ".join(str(value) for value in profile.get("constraints", []) if value),
    ]
    terms: list[str] = []
    for chunk in chunks:
        terms.extend(_meaningful_terms(chunk))
    terms.extend(_expanded_trace_terms(terms))
    return _dedupe_terms(terms)


def _planner_traceability_terms(search_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "core_topic": search_profile.get("core_topic", ""),
        "entities": search_profile.get("entities", []),
        "desired_properties": search_profile.get("desired_properties", []),
        "constraints": search_profile.get("constraints", []),
    }


def _meaningful_terms(text: str) -> list[str]:
    stop = {
        "and",
        "are",
        "build",
        "for",
        "from",
        "into",
        "not",
        "only",
        "the",
        "this",
        "that",
        "with",
        "without",
        "target",
        "venue",
        "budget",
        "gpu",
        "gpus",
        "rtx",
        "time",
        "timeline",
        "week",
        "weeks",
    }
    terms = []
    for part in re.split(r"[^A-Za-z0-9_+-]+", text):
        clean = part.strip().lower()
        if (len(clean) >= 3 or clean in {"3d", "4d"}) and clean not in stop and not _has_noisy_resource_terms(clean):
            terms.append(clean)
    return terms


def _expanded_trace_terms(terms: list[str]) -> list[str]:
    expanded: list[str] = []
    term_set = set(terms)
    if "4dgs" in term_set:
        expanded.extend(["4d", "gaussian", "splatting"])
    if "3dgs" in term_set:
        expanded.extend(["3d", "gaussian", "splatting"])
    if "feed" in term_set and "forward" in term_set:
        expanded.append("feed-forward")
    if "real" in term_set and "time" in term_set:
        expanded.append("real-time")
    return expanded


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        clean = term.strip().lower()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _term_in_text(term: str, text: str) -> bool:
    if re.fullmatch(r"[a-z0-9_+-]+", term):
        return bool(re.search(rf"(?<![a-z0-9_+-]){re.escape(term)}(?![a-z0-9_+-])", text))
    return term in text


def _has_noisy_resource_terms(text: str) -> bool:
    return bool(NOISY_RESOURCE_RE.search(text))


def _require_text(value: str, name: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{name} must not be empty")
    return clean


if __name__ == "__main__":
    raise SystemExit(main())
