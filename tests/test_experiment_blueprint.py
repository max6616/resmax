from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IDEA_SCRIPTS = ROOT / ".agents" / "skills" / "resmax-idea" / "scripts"
REVIEW_SCRIPTS = ROOT / ".agents" / "skills" / "resmax-review" / "scripts"
FIXTURE_PACK = ROOT / "tests" / "fixtures" / "research_pack" / "valid_roi_pack"
FIXTURE_IDEAS = ROOT / "tests" / "fixtures" / "ideas" / "valid_portfolio"
RAW_SMOKE = ROOT / "tests" / "fixtures" / "reviews" / "raw_review_smoke"
PROMOTE_IDEA = "idea:d3bf5354de3f1f42"


def _env(*paths: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in paths)
    return env


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, check=False)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _aggregate_reviews(tmp_path: Path, ideas: Path = FIXTURE_IDEAS) -> Path:
    out = tmp_path / "reviews"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "aggregate",
            "--ideas",
            str(ideas),
            "--raw-reviews",
            str(RAW_SMOKE),
            "--out",
            str(out),
        ],
        _env(REVIEW_SCRIPTS),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def _compile_plan(tmp_path: Path, reviews: Path, ideas: Path = FIXTURE_IDEAS) -> Path:
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
            str(ideas),
            "--reviews",
            str(reviews),
            "--out",
            str(out),
        ],
        _env(IDEA_SCRIPTS),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def test_compile_experiment_plan_writes_claim_driven_blueprint(tmp_path: Path) -> None:
    reviews = _aggregate_reviews(tmp_path)
    plan = _compile_plan(tmp_path, reviews)
    blueprint = _json(plan / "experiment_blueprint.json")

    assert (plan / "manifest.json").exists()
    assert (plan / "claim_to_experiment_matrix.csv").exists()
    assert blueprint["experiment_blocks"]
    block = blueprint["experiment_blocks"][0]
    assert block["tested_claim"]
    assert block["anti_claim"]
    assert block["baseline"]["category"] in {
        "must_run",
        "nice_to_have",
        "appendix_only",
        "not_applicable",
        "unknown_needs_followup",
    }
    assert block["dataset"]["name"]
    assert block["metric"]["primary_metric"]
    assert block["stop_condition"]
    assert block["failure_interpretation"]
    assert "primary_metric" in blueprint["metric_contract"]
    assert "must_run" in blueprint["baseline_contract"]
    assert "what_approval_enables" in blueprint["human_gate_package"][0]

    validation = _run(
        [
            sys.executable,
            ".agents/skills/_shared/resmax_core/validators/validate_state.py",
            "--schema",
            ".agents/skills/_shared/resmax_core/schemas/experiment_blueprint.schema.json",
            "--input",
            str(plan / "experiment_blueprint.json"),
        ],
        _env(IDEA_SCRIPTS),
    )
    assert validation.returncode == 0, validation.stdout + validation.stderr


def test_promoted_idea_missing_baseline_is_not_executable(tmp_path: Path) -> None:
    ideas = tmp_path / "ideas"
    shutil.copytree(FIXTURE_IDEAS, ideas)
    cards = _jsonl(ideas / "idea_cards.jsonl")
    for card in cards:
        if card["idea_id"] == PROMOTE_IDEA:
            card["direct_baselines"] = []
            card["readiness"]["experiment_blueprint_ready"] = False
            card["readiness"]["not_ready_reasons"] = ["missing_direct_baseline_for_experiment"]
    _write_jsonl(ideas / "idea_cards.jsonl", cards)

    reviews = _aggregate_reviews(tmp_path)
    plan = _compile_plan(tmp_path, reviews, ideas=ideas)
    blocks = _json(plan / "experiment_blueprint.json")["experiment_blocks"]
    promoted_block = next(block for block in blocks if block["idea_id"] == PROMOTE_IDEA)

    assert promoted_block["baseline"]["category"] == "unknown_needs_followup"
    assert promoted_block["execution_status"] == "insufficient_evidence"
    assert promoted_block["human_gate_required"] is True


def test_every_experiment_block_has_claim_and_anti_claim(tmp_path: Path) -> None:
    reviews = _aggregate_reviews(tmp_path)
    plan = _compile_plan(tmp_path, reviews)
    blocks = _json(plan / "experiment_blueprint.json")["experiment_blocks"]

    assert blocks
    for block in blocks:
        assert block["tested_claim"]
        assert block["anti_claim"]


def test_over_budget_experiment_requires_human_gate(tmp_path: Path) -> None:
    ideas = tmp_path / "ideas"
    shutil.copytree(FIXTURE_IDEAS, ideas)
    cards = _jsonl(ideas / "idea_cards.jsonl")
    for card in cards:
        if card["idea_id"] == PROMOTE_IDEA:
            card["estimated_compute"] = "high_requires_budget_gate"
    _write_jsonl(ideas / "idea_cards.jsonl", cards)

    reviews = _aggregate_reviews(tmp_path)
    plan = _compile_plan(tmp_path, reviews, ideas=ideas)
    blocks = _json(plan / "experiment_blueprint.json")["experiment_blocks"]
    promoted_block = next(block for block in blocks if block["idea_id"] == PROMOTE_IDEA)

    assert promoted_block["estimated_cost"]["budget_status"] == "over_budget"
    assert promoted_block["human_gate_required"] is True
    assert promoted_block["execution_status"] == "human_gate_required"
