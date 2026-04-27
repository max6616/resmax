from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IDEA_SCRIPTS = ROOT / ".agents" / "skills" / "resmax-idea" / "scripts"
REVIEW_SCRIPTS = ROOT / ".agents" / "skills" / "resmax-review" / "scripts"
FIXTURE_PACK = ROOT / "tests" / "fixtures" / "research_pack" / "valid_roi_pack"
FIXTURE_IDEAS = ROOT / "tests" / "fixtures" / "ideas" / "valid_portfolio"
RAW_SMOKE = ROOT / "tests" / "fixtures" / "reviews" / "raw_review_smoke"
KILLED_IDEA = "idea:5e301f25743423ef"


def _env(*paths: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in paths)
    return env


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, check=False)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _aggregate_reviews(tmp_path: Path) -> Path:
    out = tmp_path / "reviews"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "aggregate",
            "--ideas",
            str(FIXTURE_IDEAS),
            "--raw-reviews",
            str(RAW_SMOKE),
            "--out",
            str(out),
        ],
        _env(REVIEW_SCRIPTS),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def _compile_plan(tmp_path: Path, reviews: Path) -> Path:
    out = tmp_path / "experiment_plan"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_idea",
            "compile-experiment-plan",
            "--pack",
            str(FIXTURE_PACK),
            "--ideas",
            str(FIXTURE_IDEAS),
            "--reviews",
            str(reviews),
            "--out",
            str(out),
        ],
        _env(IDEA_SCRIPTS),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def _write_memory(reviews: Path, plan: Path, memory: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            sys.executable,
            "-m",
            "resmax_idea",
            "write-negative-memory",
            "--reviews",
            str(reviews),
            "--experiment-plan",
            str(plan),
            "--memory",
            str(memory),
            "--confirm-write",
        ],
        _env(IDEA_SCRIPTS),
    )


def test_negative_memory_requires_explicit_confirm_write(tmp_path: Path) -> None:
    reviews = _aggregate_reviews(tmp_path)
    plan = _compile_plan(tmp_path, reviews)
    memory = tmp_path / "resmax_memory"

    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_idea",
            "write-negative-memory",
            "--reviews",
            str(reviews),
            "--experiment-plan",
            str(plan),
            "--memory",
            str(memory),
        ],
        _env(IDEA_SCRIPTS),
    )
    assert result.returncode == 1
    assert "G8 negative memory write gate required" in result.stdout + result.stderr
    assert not (memory / "negative_memory.jsonl").exists()


def test_killed_idea_writes_blocker_negative_memory(tmp_path: Path) -> None:
    reviews = _aggregate_reviews(tmp_path)
    plan = _compile_plan(tmp_path, reviews)
    memory = tmp_path / "resmax_memory"

    result = _write_memory(reviews, plan, memory)
    assert result.returncode == 0, result.stdout + result.stderr

    negative = _jsonl(memory / "negative_memory.jsonl")
    blockers = _jsonl(memory / "reviewer_blockers.jsonl")
    failed_gaps = _jsonl(memory / "failed_gap_paths.jsonl")

    killed_rows = [row for row in negative if row["subject_id"] == KILLED_IDEA and row["decision_status"] == "killed"]
    assert killed_rows
    assert killed_rows[0]["reason_type"] == "fatal_blocker_kill"
    assert killed_rows[0]["dedupe_key"]
    assert any(row["idea_id"] == KILLED_IDEA and row["blocker_type"] == "closest_work_subsumes_delta" for row in blockers)
    assert any(row["idea_id"] == KILLED_IDEA for row in failed_gaps)


def test_duplicate_memory_entry_is_deduped_not_duplicated(tmp_path: Path) -> None:
    reviews = _aggregate_reviews(tmp_path)
    plan = _compile_plan(tmp_path, reviews)
    memory = tmp_path / "resmax_memory"

    first = _write_memory(reviews, plan, memory)
    assert first.returncode == 0, first.stdout + first.stderr
    before = {
        name: _jsonl(memory / name)
        for name in (
            "negative_memory.jsonl",
            "reviewer_blockers.jsonl",
            "failed_gap_paths.jsonl",
            "infeasible_experiments.jsonl",
        )
    }

    second = _write_memory(reviews, plan, memory)
    assert second.returncode == 0, second.stdout + second.stderr
    after = {name: _jsonl(memory / name) for name in before}

    assert {name: len(rows) for name, rows in before.items()} == {name: len(rows) for name, rows in after.items()}
    for rows in after.values():
        keys = [row["dedupe_key"] for row in rows]
        assert len(keys) == len(set(keys))
