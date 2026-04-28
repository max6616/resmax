from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "resmax-survey" / "scripts"
FIXTURE_INPUTS = ROOT / "tests" / "fixtures" / "survey_normalizer" / "generic"
ACCEPTED = ROOT / "tests" / "fixtures" / "resmax_core" / "corpus" / "accepted_index_small.csv"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS)
    env["PYTHONPYCACHEPREFIX"] = "/tmp/resmax_pycache"
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=_env(), text=True, capture_output=True, check=False)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_normalizer(tmp_path: Path) -> Path:
    out = tmp_path / "generic_graph_planning"
    result = _run(
        [
            sys.executable,
            str(SCRIPTS / "survey_normalizer.py"),
            "run-all",
            "--topic",
            "generic_graph_planning",
            "--input-dir",
            str(FIXTURE_INPUTS),
            "--accepted",
            str(ACCEPTED),
            "--out-dir",
            str(out),
            "--mode",
            "test",
            "--top-k",
            "4",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def test_normalizer_run_all_generates_required_layout_contract_and_validation(tmp_path: Path) -> None:
    out = _run_normalizer(tmp_path)

    required = [
        "survey_report.md",
        "manifest.json",
        "inputs/input_manifest.json",
        "normalized/seed_papers.normalized.jsonl",
        "audit/paper_audit.csv",
        "retrieval/retrieval_requests.jsonl",
        "retrieval/retrieval_trace.jsonl",
        "retrieval/closest_work_candidates.jsonl",
        "retrieval/falsification_checks.jsonl",
        "sources/source_manifest.jsonl",
        "assets/paper_assets.jsonl",
        "assets/asset_mentions.jsonl",
        "assets/evidence_cards.jsonl",
        "assets/claim_graph.json",
        "assets/gap_map.jsonl",
        "assets/missing_evidence.jsonl",
        "assets/asset_stats.csv",
        "downstream/survey_contract.json",
        "downstream/research_pack_compat/manifest.json",
        "validation/validation_report.json",
    ]
    for rel in required:
        assert (out / rel).exists(), rel

    assert sorted(path.name for path in out.glob("*.md")) == ["survey_report.md"]
    manifest = _json(out / "manifest.json")
    assert manifest["validation_status"] == "PASS"
    assert "downstream/survey_contract.json" in manifest["hashes"]
    assert manifest["database_snapshot"]["paper_count"] == 3

    validation = _json(out / "validation" / "validation_report.json")
    assert validation["status"] == "PASS", validation["errors"]


def test_input_normalization_paper_audit_seed_verifier_and_closest_work(tmp_path: Path) -> None:
    out = _run_normalizer(tmp_path)

    normalized_papers = _jsonl(out / "normalized" / "seed_papers.normalized.jsonl")
    assert {row["canonical_title"] for row in normalized_papers} >= {"Scene Graph Transformers", "Unlisted Planning Memory"}

    with (out / "audit" / "paper_audit.csv").open("r", encoding="utf-8", newline="") as f:
        audit_rows = list(csv.DictReader(f))
    statuses = {row["canonical_title"]: row["audit_status"] for row in audit_rows}
    assert statuses["Scene Graph Transformers"] == "verified_local"
    assert statuses["Unlisted Planning Memory"] == "external_only"
    assert all(row["reason"] for row in audit_rows)

    requests = _jsonl(out / "retrieval" / "retrieval_requests.jsonl")
    assert {"seed-list verifier", "local omission checker", "closest-work search", "infra search"}.issubset(
        {row["retrieval_mode"] for row in requests}
    )
    assert all(row["target_type"] and row["target_id"] and row["purpose"] and row["query"] for row in requests)
    assert all(int(row["top_k"]) <= 10 for row in requests)

    closest = _jsonl(out / "retrieval" / "closest_work_candidates.jsonl")
    assert any(row["target_type"] == "gap" and row["paper_id"] == "p-graph-diffusion" for row in closest)
    assert any(row["relation_to_target"] == "local_omission" for row in closest)
    assert all(row["trace_id"] for row in closest)


def test_claim_gap_falsification_assets_missing_evidence_and_contract(tmp_path: Path) -> None:
    out = _run_normalizer(tmp_path)

    falsification = _jsonl(out / "retrieval" / "falsification_checks.jsonl")
    assert any(row["target_type"] == "claim" for row in falsification)
    assert any(row["target_type"] == "gap" and row["status"] in {"potentially_covered", "needs_human_review"} for row in falsification)

    paper_assets = _jsonl(out / "assets" / "paper_assets.jsonl")
    scene_asset = next(row for row in paper_assets if row["paper_id"] == "p-scene-graph")
    assert "f1" in scene_asset["metrics"]
    assert scene_asset["baselines"]
    assert scene_asset["base_models"] or "Transformer" in " ".join(scene_asset["claimed_contributions"] + scene_asset["tasks"])
    assert scene_asset["implementation_barriers"]

    missing = _jsonl(out / "assets" / "missing_evidence.jsonl")
    assert any(row["scope"] == "paper_identity" and row["severity"] == "blocking_for_verified_fact" for row in missing)
    assert any(row["scope"] == "paper_asset" for row in missing)

    claim_graph = _json(out / "assets" / "claim_graph.json")
    assert claim_graph["claims"]
    assert all(claim["status"] != "verified_fact" for claim in claim_graph["claims"])

    gaps = _jsonl(out / "assets" / "gap_map.jsonl")
    assert gaps
    assert all(gap["falsification_status"] != "not_checked" for gap in gaps)
    assert all((gap["closest_work_ids"] or not gap["downstream_ready"]) for gap in gaps)

    contract = _json(out / "downstream" / "survey_contract.json")
    assert contract["verified_paper_set_path"] == "audit/verified_paper_set.jsonl"
    assert contract["claim_graph_path"] == "assets/claim_graph.json"
    assert any(not opportunity["downstream_ready"] or opportunity["closest_work_ids"] for opportunity in contract["seed_opportunities"])
    assert "external claims are not verified facts" in contract["warnings"]


def test_standalone_validator_and_legacy_macro_command_still_work(tmp_path: Path) -> None:
    out = _run_normalizer(tmp_path)

    validate = _run([sys.executable, str(SCRIPTS / "validate_normalized_survey.py"), "validate", "--dir", str(out)])
    assert validate.returncode == 0, validate.stdout + validate.stderr

    legacy_out = tmp_path / "legacy_macro"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "compile-spec",
            "--intent",
            "graph planning with low compute budget and public datasets",
            "--out-dir",
            str(legacy_out),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    spec = _json(legacy_out / "survey_v2" / "spec" / "research_spec.json")
    assert spec["search_profile"]["core_topic"].startswith("graph planning")
    assert "query_planner_prompt.md" in {path.name for path in (legacy_out / "survey_v2" / "spec").iterdir()}
