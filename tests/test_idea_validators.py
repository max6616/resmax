from __future__ import annotations

import hashlib
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


def _build_ideas(tmp_path: Path) -> Path:
    roi = tmp_path / "roi"
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
            str(roi),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    ideas = tmp_path / "ideas"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_idea",
            "generate",
            "--pack",
            str(roi / "research_pack"),
            "--out",
            str(ideas),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return ideas


def _cards(path: Path) -> list[dict]:
    return [json.loads(line) for line in (path / "idea_cards.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_cards(path: Path, cards: list[dict]) -> None:
    (path / "idea_cards.jsonl").write_text(
        "".join(json.dumps(card, sort_keys=True) + "\n" for card in cards),
        encoding="utf-8",
    )
    _refresh_manifest_hash(path, "idea_cards.jsonl")


def _refresh_manifest_hash(path: Path, rel_path: str) -> None:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256((path / rel_path).read_bytes()).hexdigest()
    for artifact in manifest["artifacts"]:
        if artifact["path"] == rel_path:
            artifact["sha256"] = f"sha256:{digest}"
            break
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate(path: Path) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "resmax_idea", "validate", "--ideas", str(path)])


def test_idea_cannot_be_ready_without_gap_ids(tmp_path: Path) -> None:
    ideas = _build_ideas(tmp_path)
    cards = _cards(ideas)
    cards[0]["source_gap_ids"] = []
    cards[0]["status"] = "not_ready_for_phase6"
    _write_cards(ideas, cards)

    result = _validate(ideas)
    assert result.returncode == 1
    assert "without source gaps/evidence" in result.stdout + result.stderr


def test_missing_closest_work_prevents_phase6_readiness(tmp_path: Path) -> None:
    ideas = _build_ideas(tmp_path)
    cards = _cards(ideas)
    cards[0]["closest_work_ids"] = []
    cards[0]["readiness"]["phase6_review_ready"] = True
    cards[0]["status"] = "phase6_ready"
    _write_cards(ideas, cards)

    result = _validate(ideas)
    assert result.returncode == 1
    assert "phase6_review_ready without closest_work_ids" in result.stdout + result.stderr


def test_evidence_ids_must_exist_in_source_pack(tmp_path: Path) -> None:
    ideas = _build_ideas(tmp_path)
    cards = _cards(ideas)
    cards[0]["evidence_ids"] = ["evidence_card:deadbeef"]
    _write_cards(ideas, cards)

    result = _validate(ideas)
    assert result.returncode == 1
    assert "unknown evidence_id evidence_card:deadbeef" in result.stdout + result.stderr


def test_validate_fails_when_speculative_idea_is_marked_recommended(tmp_path: Path) -> None:
    ideas = _build_ideas(tmp_path)
    cards = _cards(ideas)
    cards[0]["source_gap_ids"] = []
    cards[0]["evidence_ids"] = []
    cards[0]["status"] = "recommended"
    _write_cards(ideas, cards)

    result = _validate(ideas)
    assert result.returncode == 1
    assert "recommended" in result.stdout + result.stderr
