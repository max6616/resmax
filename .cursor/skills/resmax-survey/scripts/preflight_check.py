#!/usr/bin/env python3
"""Pre-flight check for paper database integrity.

Validates that accepted_index.csv and embedding cache are present,
complete, and consistent before running resmax-survey.

Exit code 0 = all checks passed; exit code 1 = blocking issues found.
Output is a compact JSON report for agent consumption.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None


def _load_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_csv(csv_path: Path) -> dict:
    if not csv_path.exists():
        return {"status": "FAIL", "reason": f"{csv_path} not found"}

    rows = _load_csv(csv_path)
    if not rows:
        return {"status": "FAIL", "reason": "CSV is empty"}

    total = len(rows)
    venue_year_counts: Counter[str] = Counter()
    missing_title = 0
    missing_abstract = 0
    paper_ids: list[str] = []

    for r in rows:
        cy = r.get("conf_year", "UNKNOWN")
        venue_year_counts[cy] += 1
        if not r.get("title", "").strip():
            missing_title += 1
        if not r.get("abstract_raw", "").strip():
            missing_abstract += 1
        paper_ids.append(r.get("paper_id", ""))

    dup_ids = total - len(set(paper_ids))
    abstract_pct = (total - missing_abstract) / total * 100

    issues: list[str] = []
    if missing_title > 0:
        issues.append(f"{missing_title} papers missing title")
    if missing_abstract > 0:
        issues.append(
            f"{missing_abstract}/{total} papers missing abstract "
            f"({abstract_pct:.1f}% coverage)"
        )
    if dup_ids > 0:
        issues.append(f"{dup_ids} duplicate paper_id values")

    coverage = {
        cy: cnt
        for cy, cnt in sorted(venue_year_counts.items(), key=lambda x: x[0])
    }

    return {
        "status": "FAIL" if missing_title > 0 or dup_ids > 0 else "OK",
        "total_papers": total,
        "conferences": coverage,
        "abstract_coverage_pct": round(abstract_pct, 1),
        "issues": issues,
        "paper_ids": paper_ids,
    }


def check_embedding(cache_path: Path, paper_ids: list[str]) -> dict:
    if not cache_path.exists():
        return {"status": "FAIL", "reason": f"{cache_path} not found"}

    if np is None:
        return {
            "status": "WARN",
            "reason": "numpy not installed, cannot verify embedding cache",
        }

    data = np.load(cache_path, allow_pickle=True)
    if "paper_ids" not in data or "embeddings" not in data:
        return {
            "status": "FAIL",
            "reason": "cache missing 'paper_ids' or 'embeddings' array",
        }

    cached_ids = set(data["paper_ids"].tolist())
    csv_ids = set(paper_ids)
    missing = csv_ids - cached_ids
    dim = data["embeddings"].shape[1] if data["embeddings"].ndim == 2 else "?"

    issues: list[str] = []
    if missing:
        issues.append(
            f"{len(missing)}/{len(csv_ids)} papers not in embedding cache"
        )

    return {
        "status": "FAIL" if len(missing) > len(csv_ids) * 0.05 else "OK",
        "cached_papers": len(cached_ids),
        "embedding_dim": int(dim) if isinstance(dim, (int, float)) else dim,
        "missing_count": len(missing),
        "issues": issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        default="paper_database/accepted_index.csv",
        help="Path to accepted_index.csv",
    )
    parser.add_argument(
        "--cache",
        default="paper_database/embedding_cache/qwen3_8b.npz",
        help="Path to embedding cache .npz",
    )
    args = parser.parse_args()

    csv_result = check_csv(Path(args.csv))
    paper_ids = csv_result.pop("paper_ids", [])
    emb_result = check_embedding(Path(args.cache), paper_ids)

    report = {"csv": csv_result, "embedding": emb_result}

    all_ok = (
        csv_result["status"] == "OK" and emb_result["status"] == "OK"
    )
    report["overall"] = "PASS" if all_ok else "FAIL"

    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
