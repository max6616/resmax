from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "resmax-survey" / "scripts"
FIXTURE_MACRO = ROOT / "tests" / "fixtures" / "resmax_survey_v2" / "macro_smoke"
VALIDATOR = ROOT / ".agents" / "skills" / "_shared" / "resmax_core" / "validators" / "validate_research_pack.py"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS)
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=_env(), text=True, capture_output=True, check=False)


def _build_pack(tmp_path: Path) -> Path:
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "build-pack",
            "--macro-dir",
            str(FIXTURE_MACRO),
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return tmp_path / "research_pack"


def _validate(pack: Path) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, str(VALIDATOR), "--pack", str(pack)])


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _refresh_manifest_hash(pack: Path, rel_path: str) -> None:
    manifest_path = pack / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256((pack / rel_path).read_bytes()).hexdigest()
    for artifact in manifest["artifacts"]:
        if artifact["path"] == rel_path:
            artifact["sha256"] = f"sha256:{digest}"
            break
    _write_json(manifest_path, manifest)


def test_research_pack_validator_accepts_pack_directory(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    ok = _validate(pack)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_research_pack_validator_checks_manifest_hashes(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    with (pack / "coverage_report.md").open("a", encoding="utf-8") as f:
        f.write("\nHash tamper.\n")
    bad = _validate(pack)
    assert bad.returncode == 1
    assert "sha256" in bad.stdout + bad.stderr


def test_research_pack_validator_rejects_card_with_unknown_span(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    cards_path = pack / "evidence_cards.jsonl"
    cards = _jsonl(cards_path)
    cards[0]["evidence_span_ids"] = ["evidence_span:deadbeef"]
    _write_jsonl(cards_path, cards)
    _refresh_manifest_hash(pack, "evidence_cards.jsonl")

    bad = _validate(pack)
    assert bad.returncode == 1
    assert "unknown evidence_span_id" in bad.stdout + bad.stderr


def test_research_pack_validator_rejects_selected_pack_with_zero_cards(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    manifest_path = pack / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence_coverage"]["evidence_card_count"] = 0
    _write_json(manifest_path, manifest)

    bad = _validate(pack)
    assert bad.returncode == 1
    assert "zero EvidenceCards" in bad.stdout + bad.stderr


def test_research_pack_validator_rejects_non_missing_gap_without_reference(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    gap_path = pack / "gap_map.json"
    gap_map = json.loads(gap_path.read_text(encoding="utf-8"))
    gap_map["gaps"][0]["gap_type"] = "benchmark_blind_spot"
    gap_map["gaps"][0]["supporting_claim_ids"] = []
    gap_map["gaps"][0]["evidence_card_ids"] = []
    _write_json(gap_path, gap_map)
    _refresh_manifest_hash(pack, "gap_map.json")

    bad = _validate(pack)
    assert bad.returncode == 1
    assert "must reference claim/evidence" in bad.stdout + bad.stderr


def test_research_pack_validator_rejects_strong_cross_scope_contradiction(tmp_path: Path) -> None:
    pack = _build_pack(tmp_path)
    graph_path = pack / "claim_graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    assert len(graph["claims"]) >= 2
    graph["claims"][0]["strength"] = "strong"
    graph["claims"][1]["strength"] = "strong"
    graph["claims"][1]["scope"] = "different_scope"
    graph["edges"].append(
        {
            "source_claim_id": graph["claims"][0]["claim_id"],
            "target_claim_id": graph["claims"][1]["claim_id"],
            "relation": "contradicts",
        }
    )
    _write_json(graph_path, graph)
    _refresh_manifest_hash(pack, "claim_graph.json")

    bad = _validate(pack)
    assert bad.returncode == 1
    assert "strong contradiction cannot connect claims with different scopes" in bad.stdout + bad.stderr
