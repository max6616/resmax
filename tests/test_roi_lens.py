from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "resmax-survey" / "scripts"
FIXTURE_PACK = ROOT / "tests" / "fixtures" / "research_pack" / "valid_minimal"
FIXTURE_REVIEWS = ROOT / "tests" / "fixtures" / "reviews" / "minimal"


POSITIVE_DIMENSIONS = {
    "publication_upside",
    "novelty_headroom",
    "evidence_confidence",
    "benchmark_leverage",
    "implementation_reuse",
    "story_clarity",
    "information_gap",
}

DIFFICULTY_DIMENSIONS = {
    "sota_pressure",
    "baseline_burden",
    "compute_cost",
    "data_friction",
    "engineering_risk",
    "timeline_risk",
    "review_risk",
}

ROLE_TAXONOMY = {
    "direct_baseline",
    "method_donor",
    "benchmark_opportunity",
    "dataset_source",
    "implementation_reference",
    "negative_evidence",
    "survey_or_taxonomy",
    "theory_or_mechanism",
    "visualization_reference",
    "reviewer_expectation_reference",
}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS)
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
            str(tmp_path),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return tmp_path / "research_pack"


def test_build_roi_lens_writes_dimension_vector_unknowns_and_no_black_box_score(tmp_path: Path) -> None:
    pack = _build_roi(tmp_path)
    roi_lens = json.loads((pack / "roi_lens.json").read_text(encoding="utf-8"))
    assert roi_lens["decision_policy"]["single_roi_score_allowed"] is False
    assert set(roi_lens["positive_dimensions"]) == POSITIVE_DIMENSIONS
    assert set(roi_lens["difficulty_dimensions"]) == DIFFICULTY_DIMENSIONS
    assert roi_lens["gap_roi"]

    for entry in roi_lens["gap_roi"]:
        assert set(entry["positive_signals"]) == POSITIVE_DIMENSIONS
        assert set(entry["difficulty_signals"]) == DIFFICULTY_DIMENSIONS
        assert entry["decision_support"]["single_roi_score"] is None
        assert all(unknown["follow_up_retrieval_target"] for unknown in entry["unknowns"])

    with (pack / "gap_roi_table.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows
    assert all(row["single_roi_score"] == "" for row in rows)
    assert any(row["unknowns"] and row["follow_up_retrieval_targets"] for row in rows)


def test_role_matrices_and_manifest_phase4_counts_are_present(tmp_path: Path) -> None:
    pack = _build_roi(tmp_path)
    roles = json.loads((pack / "paper_roles.json").read_text(encoding="utf-8"))
    assert ROLE_TAXONOMY.issubset(set(roles["role_taxonomy"]))
    graph_diffusion = next(row for row in roles["assignments"] if row["paper_id"] == "p-graph-diffusion")
    assert {role["role"] for role in graph_diffusion["roles"]} >= {
        "implementation_reference",
        "reviewer_expectation_reference",
    }

    for rel in ("baseline_matrix.csv", "benchmark_matrix.csv", "implementation_matrix.csv"):
        assert (pack / rel).exists()
        with (pack / rel).open("r", encoding="utf-8", newline="") as f:
            assert list(csv.DictReader(f))

    risk_register = (pack / "risk_register.md").read_text(encoding="utf-8")
    constraints = (pack / "idea_seed_constraints.md").read_text(encoding="utf-8")
    assert "roi_lens.json" in risk_register
    assert "gap_roi_table.csv" in risk_register
    assert "not ideas" in constraints.lower()

    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    artifact_paths = {artifact["path"] for artifact in manifest["artifacts"]}
    assert {
        "reviewer_pressure_notes.jsonl",
        "paper_roles.json",
        "roi_lens.json",
        "gap_roi_table.csv",
        "risk_register.md",
        "idea_seed_constraints.md",
    }.issubset(artifact_paths)
    assert manifest["source_counts"]["reviewer_pressure_notes"] >= 1
    assert manifest["mechanical_checks"]["single_black_box_roi_score_absent"] is True
