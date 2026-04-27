from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "resmax-survey" / "scripts"
FIXTURE_PACK = ROOT / "tests" / "fixtures" / "research_pack" / "valid_minimal"
FIXTURE_REVIEWS = ROOT / "tests" / "fixtures" / "reviews" / "minimal"
VALIDATOR = ROOT / ".agents" / "skills" / "_shared" / "resmax_core" / "validators" / "validate_research_pack.py"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS)
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=_env(), text=True, capture_output=True, check=False)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_extract_reviewer_pressure_uses_real_review_cache_and_links_gap_evidence(tmp_path: Path) -> None:
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
            str(tmp_path),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    pack = tmp_path / "research_pack"
    notes = _jsonl(pack / "reviewer_pressure_notes.jsonl")
    assert notes
    assert {note["paper_id"] for note in notes} == {"p-graph-diffusion"}
    assert {note["objection_type"] for note in notes} >= {"baseline", "efficiency", "reproducibility"}
    assert all(note["source_kind"] == "review_cache" for note in notes)
    assert all(note["source_path"].endswith("forum-graph.json") for note in notes)
    assert all(note["source_review_id"] for note in notes)
    assert all(note["gap_id"].startswith("gap:") for note in notes)
    assert all(note["evidence_ids"] for note in notes)
    assert all(note["inferred"] is False for note in notes)
    assert all("do not convert" in note["implication_for_new_idea"] for note in notes)

    validate = _run([sys.executable, str(VALIDATOR), "--pack", str(pack)])
    assert validate.returncode == 0, validate.stdout + validate.stderr


def test_expected_review_cache_missing_fails_loudly(tmp_path: Path) -> None:
    empty_reviews = tmp_path / "empty_reviews"
    empty_reviews.mkdir()
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "build-roi-lens",
            "--pack",
            str(FIXTURE_PACK),
            "--reviews",
            str(empty_reviews),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    assert result.returncode != 0
    assert "ensure_reviews_available.py" in result.stdout + result.stderr
