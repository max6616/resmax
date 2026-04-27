from __future__ import annotations

from typing import Any, Mapping, Sequence


def recall_at_k(returned: Sequence[str], expected: Sequence[str], k: int) -> float:
    expected_set = {paper_id for paper_id in expected if paper_id}
    if not expected_set:
        return 0.0
    returned_set = set(returned[:k])
    return len(expected_set & returned_set) / len(expected_set)


def hit_rate_at_k(returned: Sequence[str], expected: Sequence[str], k: int) -> float:
    expected_set = {paper_id for paper_id in expected if paper_id}
    if not expected_set:
        return 0.0
    return 1.0 if expected_set & set(returned[:k]) else 0.0


def mrr_at_k(returned: Sequence[str], expected: Sequence[str], k: int) -> float:
    expected_set = {paper_id for paper_id in expected if paper_id}
    if not expected_set:
        return 0.0
    for idx, paper_id in enumerate(returned[:k], 1):
        if paper_id in expected_set:
            return 1.0 / idx
    return 0.0


def evaluate_runs(spec: Mapping[str, Any], runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics: list[dict[str, Any]] = []
    expected_by_name = {
        baseline["name"]: baseline.get("expected_paper_ids", [])
        for baseline in spec.get("baselines", [])
    }

    for run in runs:
        name = run["name"]
        top_k = int(run["top_k"])
        returned = list(run.get("returned_paper_ids", []))
        expected = list(expected_by_name.get(name, []))
        metrics.append(
            {
                "name": name,
                "mode": run["mode"],
                "top_k": top_k,
                "expected_count": len(expected),
                "returned_count": len(returned),
                "hit_rate_at_k": hit_rate_at_k(returned, expected, top_k),
                "recall_at_k": recall_at_k(returned, expected, top_k),
                "mrr_at_k": mrr_at_k(returned, expected, top_k),
                "degraded": bool(run.get("degraded_reason")),
                "degraded_reason": run.get("degraded_reason", ""),
            }
        )

    count = len(metrics) or 1
    return {
        "schema_version": "0.1.0",
        "spec_name": spec.get("name", ""),
        "run_count": len(metrics),
        "aggregate": {
            "mean_hit_rate_at_k": sum(item["hit_rate_at_k"] for item in metrics) / count,
            "mean_recall_at_k": sum(item["recall_at_k"] for item in metrics) / count,
            "mean_mrr_at_k": sum(item["mrr_at_k"] for item in metrics) / count,
            "degraded_run_count": sum(1 for item in metrics if item["degraded"]),
        },
        "per_run": metrics,
    }
