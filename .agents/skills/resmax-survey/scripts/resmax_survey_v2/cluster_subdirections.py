from __future__ import annotations

import re
from typing import Any


BUCKETS = (
    (
        "dynamic_action_4d_editing",
        "Dynamic 4D/action Gaussian editing",
        (
            "4dgs",
            "4d",
            "dynamic",
            "temporal",
            "temporally",
            "action",
            "motion",
            "video",
            "coherence",
            "real-time",
            "realtime",
            "feed-forward",
            "feedforward",
        ),
    ),
    ("graph_reasoning", "Graph reasoning and planning", ("graph", "relation", "planning", "grounding")),
    ("agentic_tool_use", "Agentic tool use and memory", ("agent", "tool", "memory")),
    ("generative_editing", "Generative editing and diffusion transfer", ("diffusion", "editing", "gaussian", "splatting", "4dgs")),
    ("benchmark_evaluation", "Benchmark and evaluation leverage", ("benchmark", "evaluation", "dataset", "control")),
)


def assign_subdirection(candidate: dict[str, Any]) -> tuple[str, str]:
    text = " ".join(
        [
            candidate.get("title", ""),
            candidate.get("abstract_raw", ""),
            candidate.get("keywords_raw", ""),
            candidate.get("query_roles", ""),
        ]
    ).lower()
    best_slug = "general_method_map"
    best_label = "General method map"
    best_hits = 0
    for slug, label, terms in BUCKETS:
        hits = sum(1 for term in terms if term in text)
        if hits > best_hits:
            best_slug = slug
            best_label = label
            best_hits = hits
    return f"sdir_{best_slug}", best_label


def build_subdirection_map(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        subdirection_id, label = assign_subdirection(candidate)
        candidate["subdirection_id"] = subdirection_id
        entry = grouped.setdefault(
            subdirection_id,
            {
                "subdirection_id": subdirection_id,
                "label": label,
                "description": _description(label),
                "paper_ids": [],
                "query_roles": set(),
                "positive_signals": set(),
                "difficulty_signals": set(),
                "evidence_status": "unknown",
                "roi_unknowns": set(),
                "representative_papers": [],
            },
        )
        entry["paper_ids"].append(candidate["paper_id"])
        entry["query_roles"].update(_split_pipe(candidate.get("query_roles", "")))
        entry["positive_signals"].update(_split_pipe(candidate.get("rough_positive_signal", "")))
        entry["difficulty_signals"].update(_split_pipe(candidate.get("rough_difficulty_signal", "")))
        entry["roi_unknowns"].update(_split_pipe(candidate.get("roi_unknowns", "")))
        if candidate.get("rough_roi_evidence_status") == "weak":
            entry["evidence_status"] = "weak"
        if len(entry["representative_papers"]) < 3:
            entry["representative_papers"].append(
                {
                    "paper_id": candidate["paper_id"],
                    "title": candidate["title"],
                    "venue": candidate["venue"],
                    "year": candidate["year"],
                }
            )

    subdirections = []
    for entry in grouped.values():
        normalized = dict(entry)
        normalized["query_roles"] = sorted(normalized["query_roles"])
        normalized["positive_signals"] = sorted(normalized["positive_signals"])
        normalized["difficulty_signals"] = sorted(normalized["difficulty_signals"])
        normalized["roi_unknowns"] = sorted(normalized["roi_unknowns"])
        normalized["paper_count"] = len(normalized["paper_ids"])
        subdirections.append(normalized)
    subdirections.sort(key=lambda item: (-item["paper_count"], item["label"], item["subdirection_id"]))
    return {
        "schema_version": "0.1.0",
        "subdirections": subdirections,
        "notes": [
            "Subdirection labels are conservative metadata/query-role clusters.",
            "No single total ROI score is emitted in Phase 2.",
        ],
    }


def build_roi_rows(subdirection_map: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in subdirection_map["subdirections"]:
        benchmark_burden = _weak_if_signal(entry["positive_signals"], "benchmark_mentions")
        roi_unknowns = set(entry["roi_unknowns"])
        if benchmark_burden == "weak":
            roi_unknowns.discard("benchmark_burden")
        rows.append(
            {
                "subdirection_id": entry["subdirection_id"],
                "label": entry["label"],
                "paper_count": str(entry["paper_count"]),
                "positive_signals": "|".join(entry["positive_signals"]) or "unknown",
                "difficulty_signals": "|".join(entry["difficulty_signals"]) or "unknown",
                "benchmark_burden": benchmark_burden,
                "compute_burden": "unknown",
                "baseline_burden": "unknown",
                "reviewer_risk": "unknown",
                "evidence_status": entry["evidence_status"] if entry["evidence_status"] in {"weak", "unknown"} else "unknown",
                "rough_roi_confidence": "low",
                "roi_unknowns": "|".join(sorted(roi_unknowns)) or "benchmark_burden|compute_burden|baseline_burden|reviewer_risk",
                "representative_papers": "|".join(paper["paper_id"] for paper in entry["representative_papers"]),
            }
        )
    return rows


def _description(label: str) -> str:
    return f"Macro-level cluster for {label.lower()} candidates. Phase 2 does not promote ideas from this label."


def _weak_if_signal(signals: set[str] | list[str], target: str) -> str:
    return "weak" if target in set(signals) else "unknown"


def _split_pipe(value: str) -> list[str]:
    return [part for part in re.split(r"[|,]+", value or "") if part]
