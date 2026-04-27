from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_SCRIPTS = ROOT / ".agents" / "skills" / "resmax-review" / "scripts"
FIXTURE_IDEAS = ROOT / "tests" / "fixtures" / "ideas" / "valid_portfolio"
RAW_SMOKE = ROOT / "tests" / "fixtures" / "reviews" / "raw_review_smoke"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REVIEW_SCRIPTS)
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=_env(), text=True, capture_output=True, check=False)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_build_packages_uses_standard_evidence_package_not_generator_pitch(tmp_path: Path) -> None:
    out = tmp_path / "reviews"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "build-packages",
            "--ideas",
            str(FIXTURE_IDEAS),
            "--out",
            str(out),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    packages = sorted((out / "evidence_packages").glob("*.json"))
    assert len(packages) == 1
    package = json.loads(packages[0].read_text(encoding="utf-8"))
    policy = package["review_input_policy"]
    assert policy["reviewer_reads_only_standard_evidence_package"] is True
    assert policy["generator_persuasive_pitch_allowed"] is False
    assert "idea_report" not in package
    assert "chat_transcript" not in package


def test_run_reviewers_stub_writes_raw_traces_and_aggregates(tmp_path: Path) -> None:
    out = tmp_path / "reviews"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "run-reviewers",
            "--ideas",
            str(FIXTURE_IDEAS),
            "--out",
            str(out),
            "--provider",
            "stub",
            "--all-ideas",
            "--generator-model",
            "stub-reviewer",
            "--allow-same-model-review",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "provider=stub" in result.stdout

    raw_paths = sorted((out / "raw").glob("*/*.json"))
    idea_count = len(_jsonl(FIXTURE_IDEAS / "idea_cards.jsonl"))
    assert len(raw_paths) == idea_count * 5

    trace = json.loads(raw_paths[0].read_text(encoding="utf-8"))
    assert trace["prompt"]
    assert trace["raw_response"]
    assert trace["reviewer_model"] == "stub-reviewer"
    assert trace["generator_model"] == "stub-reviewer"
    assert trace["review_independence_confidence"] == "low"
    assert trace["fallback_reason"] == "same model used for generation and review"

    aggregate = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "aggregate",
            "--ideas",
            str(FIXTURE_IDEAS),
            "--raw-reviews",
            str(out / "raw"),
            "--out",
            str(out),
            "--all-ideas",
        ]
    )
    assert aggregate.returncode == 0, aggregate.stdout + aggregate.stderr

    validate = _run([sys.executable, "-m", "resmax_review", "validate", "--reviews", str(out)])
    assert validate.returncode == 0, validate.stdout + validate.stderr


def test_run_reviewers_same_model_requires_explicit_approval(tmp_path: Path) -> None:
    out = tmp_path / "reviews"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "run-reviewers",
            "--ideas",
            str(FIXTURE_IDEAS),
            "--out",
            str(out),
            "--provider",
            "stub",
            "--generator-model",
            "stub-reviewer",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    raw_paths = sorted((out / "raw").glob("*/*.json"))
    assert raw_paths
    trace = json.loads(raw_paths[0].read_text(encoding="utf-8"))
    assert trace["recommended_status"] == "human_gate"
    assert trace["review_independence_confidence"] == "low"
    assert trace["blockers"][0]["blocker_type"] == "same_model_review_not_allowed"
    assert "same model used for generation and review" in trace["fallback_reason"]

    aggregate = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "aggregate",
            "--ideas",
            str(FIXTURE_IDEAS),
            "--raw-reviews",
            str(out / "raw"),
            "--out",
            str(out),
        ]
    )
    assert aggregate.returncode == 0, aggregate.stdout + aggregate.stderr
    assert len(_jsonl(out / "human_gate_ideas.jsonl")) == 1
    assert not _jsonl(out / "promoted_ideas.jsonl")


def test_reviewer_provider_error_routes_to_human_gate_trace(tmp_path: Path) -> None:
    out = tmp_path / "reviews"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "build-packages",
            "--ideas",
            str(FIXTURE_IDEAS),
            "--out",
            str(out),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    sys.path.insert(0, str(REVIEW_SCRIPTS))
    from resmax_review.build_evidence_package import read_json
    from resmax_review.run_reviewers import _review_one_with_retries

    class FailingProvider:
        def review(self, role: str, prompt: str, evidence_package: dict) -> dict:
            raise RuntimeError("transport ended prematurely")

    package_path = sorted((out / "evidence_packages").glob("*.json"))[0]
    trace = _review_one_with_retries(
        provider="mcp-deepseek",
        caller=FailingProvider(),
        role="novelty",
        evidence_package=read_json(package_path),
        evidence_package_path=package_path,
        generator_model="resmax_idea",
        retries=1,
    )

    assert trace["recommended_status"] == "human_gate"
    assert trace["review_independence_confidence"] == "unknown"
    assert trace["blockers"][0]["blocker_type"] == "external_reviewer_execution_failed"
    assert "transport ended prematurely" in trace["raw_response"]


def test_empty_reviewer_response_routes_to_human_gate_trace(tmp_path: Path) -> None:
    out = tmp_path / "reviews"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "build-packages",
            "--ideas",
            str(FIXTURE_IDEAS),
            "--out",
            str(out),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    sys.path.insert(0, str(REVIEW_SCRIPTS))
    from resmax_review.build_evidence_package import read_json
    from resmax_review.run_reviewers import _review_one_with_retries

    class EmptyProvider:
        def review(self, role: str, prompt: str, evidence_package: dict) -> dict:
            return {"model": "empty-reviewer", "content": "", "usage": {}}

    package_path = sorted((out / "evidence_packages").glob("*.json"))[0]
    trace = _review_one_with_retries(
        provider="mcp-deepseek",
        caller=EmptyProvider(),
        role="experiment",
        evidence_package=read_json(package_path),
        evidence_package_path=package_path,
        generator_model="resmax_idea",
        retries=1,
    )

    assert trace["recommended_status"] == "human_gate"
    assert trace["raw_response"]
    assert trace["blockers"][0]["blocker_type"] == "external_reviewer_execution_failed"
    assert "empty reviewer response" in trace["raw_response"]


def test_fixture_aggregation_smoke_covers_all_statuses_and_validates(tmp_path: Path) -> None:
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
            "--all-ideas",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    assert len(_jsonl(out / "promoted_ideas.jsonl")) == 1
    assert len(_jsonl(out / "killed_ideas.jsonl")) == 1
    assert len(_jsonl(out / "revise_ideas.jsonl")) == 1
    assert len(_jsonl(out / "human_gate_ideas.jsonl")) == 1

    validate = _run([sys.executable, "-m", "resmax_review", "validate", "--reviews", str(out)])
    assert validate.returncode == 0, validate.stdout + validate.stderr

    raw = next((out / "raw" / "reviewer_pressure").glob("idea:d3bf5354de3f1f42.json"))
    trace = json.loads(raw.read_text(encoding="utf-8"))
    assert trace["raw_response"]
    assert trace["prompt"]
    assert trace["reviewer_model"] == trace["generator_model"]
    assert trace["review_independence_confidence"] == "low"
    assert trace["fallback_reason"] == "same model used for generation and review"


def test_validate_rejects_bad_same_model_fallback(tmp_path: Path) -> None:
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
            "--all-ideas",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    raw = out / "raw" / "reviewer_pressure" / "idea:d3bf5354de3f1f42.json"
    trace = json.loads(raw.read_text(encoding="utf-8"))
    trace["review_independence_confidence"] = "high"
    raw.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    validate = _run([sys.executable, "-m", "resmax_review", "validate", "--reviews", str(out)])
    assert validate.returncode == 1
    assert "same-model fallback" in validate.stdout + validate.stderr
