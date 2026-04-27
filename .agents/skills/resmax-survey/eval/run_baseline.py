#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
SHARED = ROOT / ".agents" / "skills" / "_shared"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import evaluate_runs  # noqa: E402
from resmax_core.corpus_api import load_corpus, search_papers  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic Resmax retrieval baselines.")
    parser.add_argument("--spec", required=True, help="Path to a pilot spec JSON file.")
    parser.add_argument("--out", required=True, help="Output directory for full baseline artifacts.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = ROOT / spec_path
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    corpus_spec = spec.get("corpus", {})
    accepted_csv = _resolve_path(corpus_spec["accepted_csv"])
    reviews_dir = _resolve_optional_path(corpus_spec.get("reviews_dir"))
    embedding_cache = _resolve_optional_path(corpus_spec.get("embedding_cache"))
    trace_path = out_dir / "retrieval_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    handle = load_corpus(
        accepted_csv,
        reviews_dir=reviews_dir,
        embedding_cache=embedding_cache,
        trace_path=trace_path,
    )

    runs: list[dict[str, Any]] = []
    for baseline in spec.get("baselines", []):
        hits = search_papers(
            handle,
            baseline.get("query", ""),
            filters=baseline.get("filters", {}),
            top_k=int(baseline.get("top_k", 50)),
            mode=baseline.get("mode", "keyword"),
        )
        run = {
            "name": baseline["name"],
            "mode": baseline.get("mode", "keyword"),
            "query": baseline.get("query", ""),
            "filters": _public_filters(baseline.get("filters", {})),
            "top_k": int(baseline.get("top_k", 50)),
            "trace_id": hits.trace.trace_id,
            "degraded_reason": hits.trace.degraded_reason,
            "returned_paper_ids": [hit.paper_id for hit in hits],
            "hits": [asdict(hit) for hit in hits],
        }
        runs.append(run)

    results = {
        "schema_version": "0.1.0",
        "spec_name": spec.get("name", ""),
        "spec_path": str(spec_path.relative_to(ROOT)) if spec_path.is_relative_to(ROOT) else str(spec_path),
        "corpus": {
            "accepted_index_sha256": handle.accepted_index_sha256,
            "corpus_snapshot_hash": handle.corpus_snapshot_hash,
            "paper_count": len(handle.papers),
            "embedding_cache_meta": dict(handle.embedding_cache_meta),
        },
        "runs": runs,
    }
    metrics = evaluate_runs(spec, runs)

    _write_json(out_dir / "baseline_results.json", results)
    _write_json(out_dir / "metrics.json", metrics)
    (out_dir / "summary.md").write_text(_summary(results, metrics), encoding="utf-8")
    print(f"[baseline] wrote baseline_results.json, metrics.json, retrieval_trace.jsonl to {out_dir}")
    return 0


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _resolve_optional_path(raw: str | None) -> Path | None:
    if not raw:
        return None
    return _resolve_path(raw)


def _public_filters(filters: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if key not in {"_query_vector", "query_vector"}}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _summary(results: dict[str, Any], metrics: dict[str, Any]) -> str:
    lines = [
        "# Resmax Eval Baseline",
        "",
        f"- Spec: {results['spec_name']}",
        f"- Paper count: {results['corpus']['paper_count']}",
        f"- Runs: {metrics['run_count']}",
        f"- Mean recall@k: {metrics['aggregate']['mean_recall_at_k']:.4f}",
        f"- Degraded runs: {metrics['aggregate']['degraded_run_count']}",
        "",
        "| Run | Mode | Returned | Recall@k | Degraded |",
        "|---|---|---:|---:|---|",
    ]
    per_run = {item["name"]: item for item in metrics["per_run"]}
    for run in results["runs"]:
        item = per_run[run["name"]]
        degraded = item["degraded_reason"] or ""
        lines.append(
            f"| {run['name']} | {run['mode']} | {len(run['returned_paper_ids'])} | "
            f"{item['recall_at_k']:.4f} | {degraded} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
