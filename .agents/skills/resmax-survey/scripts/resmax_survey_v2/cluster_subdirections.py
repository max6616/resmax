from __future__ import annotations

import re
from typing import Any


BUCKETS = (
    (
        "method_architecture",
        "Method and architecture cluster",
        (
            "method",
            "architecture",
            "model",
            "transformer",
            "diffusion",
            "optimization",
            "retrieval",
            "representation",
        ),
    ),
    ("task_problem", "Task and problem setting cluster", ("task", "problem", "planning", "reasoning", "prediction", "generation", "classification")),
    ("implementation_reuse", "Implementation and reuse cluster", ("implementation", "code", "open-source", "pretrained", "weights", "reproduce")),
    ("benchmark_evaluation", "Benchmark and evaluation cluster", ("benchmark", "evaluation", "dataset", "metric", "baseline", "ablation")),
    ("limitation_risk", "Limitation and risk cluster", ("limitation", "failure", "robustness", "cost", "compute", "runtime")),
)
MIN_SUBDIRECTION_PAPERS = 50
FOUNDATION_LIMIT = 25


def assign_subdirection(candidate: dict[str, Any]) -> tuple[str, str]:
    assignments = assign_subdirections(candidate)
    if not assignments:
        return "sdir_general_method_map", "General method map"
    return assignments[0]["subdirection_id"], assignments[0]["label"]


def assign_subdirections(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    text = " ".join(
        [
            candidate.get("title", ""),
            candidate.get("abstract_raw", ""),
            candidate.get("keywords_raw", ""),
            candidate.get("query_roles", ""),
        ]
    ).lower()
    assignments: list[dict[str, Any]] = []
    for slug, label, terms in BUCKETS:
        hits = sum(1 for term in terms if term in text)
        if hits:
            assignments.append(
                {
                    "subdirection_id": f"sdir_{slug}",
                    "label": label,
                    "match_score": hits,
                    "matched_terms": [term for term in terms if term in text],
                }
            )
    if not assignments:
        assignments.append(
            {
                "subdirection_id": "sdir_general_method_map",
                "label": "General method map",
                "match_score": 0,
                "matched_terms": [],
            }
        )
    assignments.sort(key=lambda item: (-int(item["match_score"]), item["label"], item["subdirection_id"]))
    return assignments


def build_subdirection_map(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    candidate_assignments: dict[str, list[dict[str, Any]]] = {}
    foundations = _foundation_candidates(candidates)
    for candidate in candidates:
        assignments = assign_subdirections(candidate)
        candidate_assignments[candidate["paper_id"]] = assignments
        candidate["subdirection_id"] = assignments[0]["subdirection_id"]
        candidate["subdirection_ids"] = "|".join(item["subdirection_id"] for item in assignments)
        candidate["subdirection_labels"] = "|".join(item["label"] for item in assignments)
        for assignment in assignments:
            _add_candidate(grouped, candidate, assignment, is_foundation=False)

    for subdirection_id in list(grouped):
        _add_foundations(grouped[subdirection_id], foundations)
        _expand_sparse_subdirection(grouped[subdirection_id], candidates, candidate_assignments)
    _sync_foundation_assignments(candidates, grouped, foundations)

    subdirections = []
    for entry in grouped.values():
        normalized = dict(entry)
        normalized["query_roles"] = sorted(normalized["query_roles"])
        normalized["positive_signals"] = sorted(normalized["positive_signals"])
        normalized["difficulty_signals"] = sorted(normalized["difficulty_signals"])
        normalized["roi_unknowns"] = sorted(normalized["roi_unknowns"])
        normalized["foundation_paper_ids"] = sorted(normalized["foundation_paper_ids"])
        normalized["paper_count"] = len(normalized["paper_ids"])
        subdirections.append(normalized)
    subdirections.sort(key=lambda item: (-item["paper_count"], item["label"], item["subdirection_id"]))
    return {
        "schema_version": "0.1.0",
        "subdirections": subdirections,
        "notes": [
            "Subdirection labels are multi-label metadata/query-role clusters.",
            "Mainline/foundation papers are intentionally repeated across subdirections.",
            f"Sparse subdirections are expanded toward {MIN_SUBDIRECTION_PAPERS} papers when the macro candidate pool has enough matching papers.",
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


def _add_candidate(
    grouped: dict[str, dict[str, Any]],
    candidate: dict[str, Any],
    assignment: dict[str, Any],
    *,
    is_foundation: bool,
) -> None:
    subdirection_id = assignment["subdirection_id"]
    entry = grouped.setdefault(
        subdirection_id,
        {
            "subdirection_id": subdirection_id,
            "label": assignment["label"],
            "description": _description(assignment["label"]),
            "paper_ids": [],
            "query_roles": set(),
            "positive_signals": set(),
            "difficulty_signals": set(),
            "evidence_status": "unknown",
            "roi_unknowns": set(),
            "representative_papers": [],
            "foundation_paper_ids": set(),
        },
    )
    paper_id = candidate["paper_id"]
    if paper_id not in entry["paper_ids"]:
        entry["paper_ids"].append(paper_id)
    if is_foundation:
        entry["foundation_paper_ids"].add(paper_id)
    entry["query_roles"].update(_split_pipe(candidate.get("query_roles", "")))
    entry["positive_signals"].update(_split_pipe(candidate.get("rough_positive_signal", "")))
    entry["difficulty_signals"].update(_split_pipe(candidate.get("rough_difficulty_signal", "")))
    entry["roi_unknowns"].update(_split_pipe(candidate.get("roi_unknowns", "")))
    if candidate.get("rough_roi_evidence_status") == "weak":
        entry["evidence_status"] = "weak"
    if len(entry["representative_papers"]) < 5 and paper_id not in {item["paper_id"] for item in entry["representative_papers"]}:
        entry["representative_papers"].append(
            {
                "paper_id": paper_id,
                "title": candidate["title"],
                "venue": candidate["venue"],
                "year": candidate["year"],
            }
        )


def _add_foundations(entry: dict[str, Any], foundations: list[dict[str, Any]]) -> None:
    for candidate in foundations:
        if candidate["paper_id"] not in entry["paper_ids"]:
            entry["paper_ids"].append(candidate["paper_id"])
        entry["foundation_paper_ids"].add(candidate["paper_id"])
        entry["query_roles"].update(_split_pipe(candidate.get("query_roles", "")))
        entry["positive_signals"].update(_split_pipe(candidate.get("rough_positive_signal", "")))
        entry["difficulty_signals"].update(_split_pipe(candidate.get("rough_difficulty_signal", "")))
        entry["roi_unknowns"].update(_split_pipe(candidate.get("roi_unknowns", "")))
        if candidate.get("rough_roi_evidence_status") == "weak":
            entry["evidence_status"] = "weak"


def _expand_sparse_subdirection(
    entry: dict[str, Any],
    candidates: list[dict[str, Any]],
    candidate_assignments: dict[str, list[dict[str, Any]]],
) -> None:
    if len(entry["paper_ids"]) >= MIN_SUBDIRECTION_PAPERS or len(candidates) < MIN_SUBDIRECTION_PAPERS:
        return
    subdirection_id = entry["subdirection_id"]
    scored: list[tuple[int, float, dict[str, Any]]] = []
    for candidate in candidates:
        if candidate["paper_id"] in entry["paper_ids"]:
            continue
        assignment_score = 0
        for assignment in candidate_assignments.get(candidate["paper_id"], []):
            if assignment["subdirection_id"] == subdirection_id:
                assignment_score = max(assignment_score, int(assignment.get("match_score") or 0))
        if assignment_score <= 0 and not _is_foundation_candidate(candidate):
            continue
        scored.append((assignment_score, _to_float(candidate.get("candidate_grade_score", "0")), candidate))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].get("title", ""), item[2].get("paper_id", "")))
    for _score, _grade, candidate in scored:
        if len(entry["paper_ids"]) >= MIN_SUBDIRECTION_PAPERS:
            break
        if candidate["paper_id"] not in entry["paper_ids"]:
            entry["paper_ids"].append(candidate["paper_id"])


def _foundation_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    foundations = [candidate for candidate in candidates if _is_foundation_candidate(candidate)]
    foundations.sort(
        key=lambda row: (
            -len(_split_pipe(row.get("query_roles", ""))),
            -_to_float(row.get("candidate_grade_score", "0")),
            row.get("title", ""),
            row.get("paper_id", ""),
        )
    )
    return foundations[:FOUNDATION_LIMIT]


def _sync_foundation_assignments(
    candidates: list[dict[str, Any]],
    grouped: dict[str, dict[str, Any]],
    foundations: list[dict[str, Any]],
) -> None:
    foundation_ids = {candidate["paper_id"] for candidate in foundations}
    if not foundation_ids:
        return
    all_ids = list(grouped)
    labels_by_id = {subdirection_id: entry["label"] for subdirection_id, entry in grouped.items()}
    for candidate in candidates:
        if candidate["paper_id"] not in foundation_ids:
            continue
        merged_ids = _dedupe_list(_split_pipe(candidate.get("subdirection_ids", "")) + all_ids)
        candidate["subdirection_ids"] = "|".join(merged_ids)
        candidate["subdirection_labels"] = "|".join(labels_by_id.get(subdirection_id, subdirection_id) for subdirection_id in merged_ids)


def _is_foundation_candidate(candidate: dict[str, Any]) -> bool:
    text = " ".join(
        [
            candidate.get("title", ""),
            candidate.get("abstract_raw", ""),
            candidate.get("keywords_raw", ""),
            candidate.get("query_roles", ""),
            candidate.get("candidate_grade_reasons", ""),
        ]
    ).lower()
    role_count = len(_split_pipe(candidate.get("query_roles", "")))
    if role_count >= 4:
        return True
    return any(
        phrase in text
        for phrase in (
            "foundation",
            "foundational",
            "survey",
            "taxonomy",
            "overview",
            "benchmark",
        )
    )


def _weak_if_signal(signals: set[str] | list[str], target: str) -> str:
    return "weak" if target in set(signals) else "unknown"


def _split_pipe(value: str) -> list[str]:
    return [part for part in re.split(r"[|,]+", value or "") if part]


def _dedupe_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _to_float(value: str) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
