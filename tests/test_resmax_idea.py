from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SURVEY_SCRIPTS = ROOT / ".agents" / "skills" / "resmax-survey" / "scripts"
IDEA_SCRIPTS = ROOT / ".agents" / "skills" / "resmax-idea" / "scripts"
FIXTURE_PACK = ROOT / "tests" / "fixtures" / "research_pack" / "valid_minimal"
FIXTURE_REVIEWS = ROOT / "tests" / "fixtures" / "reviews" / "minimal"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(IDEA_SCRIPTS), str(SURVEY_SCRIPTS)])
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=_env(), text=True, capture_output=True, check=False)


def _build_roi(tmp_path: Path) -> Path:
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "build-roi-lens",
            "--pack",
            str(FIXTURE_PACK),
            "--reviews",
            str(FIXTURE_REVIEWS),
            "--out",
            str(tmp_path / "roi"),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return tmp_path / "roi" / "research_pack"


def _generate(tmp_path: Path, pack: Path, negative_memory: Path | None = None) -> Path:
    out = tmp_path / "ideas"
    args = [
        sys.executable,
        "-m",
        "resmax_idea",
        "generate",
        "--pack",
        str(pack),
        "--out",
        str(out),
    ]
    if negative_memory is not None:
        args.extend(["--negative-memory", str(negative_memory)])
    result = _run(args)
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_generate_writes_structured_portfolio_and_validate_passes(tmp_path: Path) -> None:
    pack = _build_roi(tmp_path)
    ideas = _generate(tmp_path, pack)

    for rel in (
        "manifest.json",
        "idea_cards.jsonl",
        "idea_lineage.json",
        "closest_work_checks.jsonl",
        "strongest_rejection_cases.md",
        "cheapest_falsification.md",
        "generation_trace.jsonl",
        "idea_report.md",
    ):
        assert (ideas / rel).exists()

    cards = _jsonl(ideas / "idea_cards.jsonl")
    assert cards
    assert all("topic_direct" not in card["generation_sources"] for card in cards)
    assert any(card["readiness"]["phase6_review_ready"] for card in cards)
    assert "rendered from structured artifacts" in (ideas / "idea_report.md").read_text(encoding="utf-8")

    result = _run([sys.executable, "-m", "resmax_idea", "validate", "--ideas", str(ideas)])
    assert result.returncode == 0, result.stdout + result.stderr


def test_duplicate_negative_memory_marks_duplicate_risk(tmp_path: Path) -> None:
    pack = _build_roi(tmp_path)
    memory = tmp_path / "negative_memory.jsonl"
    memory.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "state_id": "negative_memory:11111111",
                "created_at": "2026-04-27T00:00:00Z",
                "input_hash": "sha256:" + "1" * 64,
                "parent_state_ids": [],
                "producer": {"name": "pytest", "version": "0.1.0", "run_id": "fixture"},
                "memory_id": "killed-resource-idea",
                "subject_id": "idea:deadbeef",
                "subject_type": "idea",
                "reason": "Killed resource compute cost angle for Graph reasoning planning because baseline burden and compute burden remained unresolved.",
                "evidence_status": "supported",
                "evidence_card_ids": [],
                "decision_status": "killed",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    ideas = _generate(tmp_path, pack, memory)
    cards = _jsonl(ideas / "idea_cards.jsonl")
    assert any(card["status"] == "duplicate_risk" and card["duplicate_memory_matches"] for card in cards)

    result = _run([sys.executable, "-m", "resmax_idea", "validate", "--ideas", str(ideas)])
    assert result.returncode == 0, result.stdout + result.stderr
