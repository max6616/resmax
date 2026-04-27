from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / ".agents" / "skills" / "resmax-survey" / "eval" / "run_baseline.py"
SPEC = ROOT / ".agents" / "skills" / "resmax-survey" / "eval" / "pilot_specs" / "smoke_fixture.json"


def _run_baseline(out_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--spec",
            str(SPEC),
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_eval_baseline_writes_deterministic_artifacts(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_run = _run_baseline(first)
    assert first_run.returncode == 0, first_run.stdout + first_run.stderr
    second_run = _run_baseline(second)
    assert second_run.returncode == 0, second_run.stdout + second_run.stderr

    first_results = json.loads((first / "baseline_results.json").read_text(encoding="utf-8"))
    second_results = json.loads((second / "baseline_results.json").read_text(encoding="utf-8"))
    first_metrics = json.loads((first / "metrics.json").read_text(encoding="utf-8"))
    second_metrics = json.loads((second / "metrics.json").read_text(encoding="utf-8"))

    assert first_results == second_results
    assert first_metrics == second_metrics
    assert first_results["runs"][0]["returned_paper_ids"] == ["p-scene-graph", "p-graph-diffusion"]
    assert first_metrics["aggregate"]["mean_recall_at_k"] == 1.0
    assert (first / "retrieval_trace.jsonl").exists()
    assert (first / "summary.md").exists()
