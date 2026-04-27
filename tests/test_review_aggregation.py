from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_SCRIPTS = ROOT / ".agents" / "skills" / "resmax-review" / "scripts"
FIXTURE_IDEAS = ROOT / "tests" / "fixtures" / "ideas" / "valid_portfolio"
RAW_SMOKE = ROOT / "tests" / "fixtures" / "reviews" / "raw_review_smoke"

sys.path.insert(0, str(REVIEW_SCRIPTS))
from resmax_review import REVIEWER_ROLES  # noqa: E402
from resmax_review.build_evidence_package import read_json, sha256_file, sha256_text  # noqa: E402
from resmax_review.reviewer_prompts import build_prompt  # noqa: E402


PROMOTE_IDEA = "idea:d3bf5354de3f1f42"
KILLED_IDEA = "idea:5e301f25743423ef"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REVIEW_SCRIPTS)
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=_env(), text=True, capture_output=True, check=False)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_fatal_blocker_prevents_promotion(tmp_path: Path) -> None:
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
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    killed = _jsonl(out / "killed_ideas.jsonl")
    assert [row["idea_id"] for row in killed] == [KILLED_IDEA]
    assert any(blocker["severity"] == "fatal" for blocker in killed[0]["blockers"])
    assert KILLED_IDEA not in [row["idea_id"] for row in _jsonl(out / "promoted_ideas.jsonl")]


def test_raw_review_missing_prevents_promotion(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    shutil.copytree(RAW_SMOKE, raw)
    (raw / "novelty" / f"{PROMOTE_IDEA}.json").unlink()
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
            str(raw),
            "--out",
            str(out),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    assert PROMOTE_IDEA not in [row["idea_id"] for row in _jsonl(out / "promoted_ideas.jsonl")]
    human_gate = {row["idea_id"]: row for row in _jsonl(out / "human_gate_ideas.jsonl")}
    assert PROMOTE_IDEA in human_gate
    assert "novelty" in human_gate[PROMOTE_IDEA]["missing_review_roles"]


def test_reviewer_cannot_promote_idea_missing_closest_work(tmp_path: Path) -> None:
    ideas = tmp_path / "ideas"
    shutil.copytree(FIXTURE_IDEAS, ideas)
    cards = _jsonl(ideas / "idea_cards.jsonl")
    checks = _jsonl(ideas / "closest_work_checks.jsonl")
    for card in cards:
        if card["idea_id"] == PROMOTE_IDEA:
            card["closest_work_ids"] = []
            card["direct_baselines"] = []
            card["readiness"] = {
                "phase6_review_ready": False,
                "experiment_blueprint_ready": False,
                "not_ready_reasons": ["missing_closest_work"],
            }
            card["status"] = "not_ready_for_phase6"
    for check in checks:
        if check["idea_id"] == PROMOTE_IDEA:
            check["closest_work_ids"] = []
            check["phase6_review_ready"] = False
            check["failure_reason"] = "closest_work_or_evidence_missing"
            check["novelty_proximity"] = "missing_closest_work"
    _write_jsonl(ideas / "idea_cards.jsonl", cards)
    _write_jsonl(ideas / "closest_work_checks.jsonl", checks)
    _refresh_manifest_hash(ideas, "idea_cards.jsonl")
    _refresh_manifest_hash(ideas, "closest_work_checks.jsonl")

    package_out = tmp_path / "package_build"
    build = _run(
        [
            sys.executable,
            "-m",
            "resmax_review",
            "build-packages",
            "--ideas",
            str(ideas),
            "--out",
            str(package_out),
        ]
    )
    assert build.returncode == 0, build.stdout + build.stderr
    raw = tmp_path / "raw"
    _write_all_promote_reviews(package_out, raw)

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
            str(raw),
            "--out",
            str(out),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    assert PROMOTE_IDEA not in [row["idea_id"] for row in _jsonl(out / "promoted_ideas.jsonl")]
    revise = {row["idea_id"]: row for row in _jsonl(out / "revise_ideas.jsonl")}
    assert PROMOTE_IDEA in revise
    assert "closest work missing" in "; ".join(revise[PROMOTE_IDEA]["decision_reasons"])


def test_tournament_trace_is_append_only_jsonl(tmp_path: Path) -> None:
    out = tmp_path / "reviews"
    args = [
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
    ]
    first = _run(args)
    assert first.returncode == 0, first.stdout + first.stderr
    first_lines = (out / "tournament_trace.jsonl").read_text(encoding="utf-8").splitlines()
    second = _run(args)
    assert second.returncode == 0, second.stdout + second.stderr
    second_lines = (out / "tournament_trace.jsonl").read_text(encoding="utf-8").splitlines()

    assert second_lines[: len(first_lines)] == first_lines
    assert len(second_lines) > len(first_lines)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _refresh_manifest_hash(ideas: Path, rel_path: str) -> None:
    manifest_path = ideas / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256((ideas / rel_path).read_bytes()).hexdigest()
    for artifact in manifest["artifacts"]:
        if artifact["path"] == rel_path:
            artifact["sha256"] = f"sha256:{digest}"
            break
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_all_promote_reviews(package_out: Path, raw_dir: Path) -> None:
    for package_path in sorted((package_out / "evidence_packages").glob("*.json")):
        package = read_json(package_path)
        evidence_hash = sha256_file(package_path)
        for role in REVIEWER_ROLES:
            prompt = build_prompt(role, package)
            payload = {
                "schema_version": "0.1.0",
                "state_id": f"review_trace:{_hash({'idea_id': package['idea_id'], 'role': role})[:16]}",
                "created_at": "2026-04-27T00:00:00Z",
                "input_hash": "sha256:" + _hash({"prompt": prompt, "evidence_hash": evidence_hash}),
                "parent_state_ids": [package["package_id"]],
                "producer": {"name": "pytest", "version": "0.1.0", "run_id": "all_promote"},
                "review_id": f"review:{_hash({'review': package['idea_id'], 'role': role})[:16]}",
                "idea_id": package["idea_id"],
                "reviewer_role": role,
                "reviewer_model": f"review-{role}",
                "generator_model": "generator-model-a",
                "review_independence_confidence": "high",
                "prompt": prompt,
                "prompt_hash": sha256_text(prompt),
                "evidence_package_hash": evidence_hash,
                "raw_response": "Promote after blocker-first review.",
                "raw_review": "Promote after blocker-first review.",
                "blockers": [],
                "recommended_status": "promote",
                "decision_status": "promoted",
            }
            target = raw_dir / role / f"{package['idea_id']}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
