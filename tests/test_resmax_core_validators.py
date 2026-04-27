from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / ".agents" / "skills" / "_shared"
CORE = SHARED / "resmax_core"
SCHEMAS = CORE / "schemas"
VALID = ROOT / "tests" / "fixtures" / "resmax_core" / "valid"
INVALID = ROOT / "tests" / "fixtures" / "resmax_core" / "invalid"
sys.path.insert(0, str(SHARED))

from resmax_core.validators.common import validate_json_file  # noqa: E402


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)


def test_valid_json_fixtures_match_their_schemas() -> None:
    for fixture in sorted(VALID.glob("*.json")):
        schema = SCHEMAS / f"{fixture.stem}.schema.json"
        assert schema.exists(), fixture
        errors = validate_json_file(fixture, schema)
        assert not errors, [error.format() for error in errors]


def test_validate_state_cli_passes_and_fails_with_field_path() -> None:
    ok = _run([
        sys.executable,
        ".agents/skills/_shared/resmax_core/validators/validate_state.py",
        "--schema",
        ".agents/skills/_shared/resmax_core/schemas/evidence_card.schema.json",
        "--input",
        "tests/fixtures/resmax_core/valid/evidence_card.json",
    ])
    assert ok.returncode == 0, ok.stdout + ok.stderr

    bad = _run([
        sys.executable,
        ".agents/skills/_shared/resmax_core/validators/validate_state.py",
        "--schema",
        ".agents/skills/_shared/resmax_core/schemas/evidence_card.schema.json",
        "--input",
        "tests/fixtures/resmax_core/invalid/evidence_card_missing_span.json",
    ])
    assert bad.returncode == 1
    assert "$.evidence_span_ids" in bad.stdout + bad.stderr


def test_jsonl_validator_reports_line_number_and_field_path() -> None:
    ok = _run([
        sys.executable,
        ".agents/skills/_shared/resmax_core/validators/validate_jsonl.py",
        "--schema",
        ".agents/skills/_shared/resmax_core/schemas/retrieval_trace.schema.json",
        "--input",
        "tests/fixtures/resmax_core/valid/retrieval_trace.jsonl",
    ])
    assert ok.returncode == 0, ok.stdout + ok.stderr

    bad = _run([
        sys.executable,
        ".agents/skills/_shared/resmax_core/validators/validate_jsonl.py",
        "--schema",
        ".agents/skills/_shared/resmax_core/schemas/retrieval_trace.schema.json",
        "--input",
        "tests/fixtures/resmax_core/invalid/retrieval_trace_missing_query.jsonl",
    ])
    assert bad.returncode == 1
    assert "line 2 $.query_id" in bad.stdout + bad.stderr


def test_strong_claim_requires_evidence_or_insufficient_evidence() -> None:
    bad = _run([
        sys.executable,
        ".agents/skills/_shared/resmax_core/validators/validate_state.py",
        "--schema",
        ".agents/skills/_shared/resmax_core/schemas/claim_graph.schema.json",
        "--input",
        "tests/fixtures/resmax_core/invalid/claim_graph_strong_claim_without_evidence.json",
    ])
    assert bad.returncode == 1
    assert "strong claim must reference" in bad.stdout + bad.stderr


def test_research_pack_validator_checks_manifest_and_artifacts() -> None:
    ok = _run([
        sys.executable,
        ".agents/skills/_shared/resmax_core/validators/validate_research_pack.py",
        "--manifest",
        "tests/fixtures/resmax_core/valid/research_pack_manifest.json",
    ])
    assert ok.returncode == 0, ok.stdout + ok.stderr

    bad = _run([
        sys.executable,
        ".agents/skills/_shared/resmax_core/validators/validate_research_pack.py",
        "--manifest",
        "tests/fixtures/resmax_core/invalid/research_pack_manifest_missing_artifact.json",
    ])
    assert bad.returncode == 1
    assert "artifact does not exist" in bad.stdout + bad.stderr


def test_idea_pack_validator_checks_supplied_artifacts() -> None:
    ok = _run([
        sys.executable,
        ".agents/skills/_shared/resmax_core/validators/validate_idea_pack.py",
        "--idea-card",
        "tests/fixtures/resmax_core/valid/idea_card.json",
        "--review-trace",
        "tests/fixtures/resmax_core/valid/review_trace.json",
        "--experiment-blueprint",
        "tests/fixtures/resmax_core/valid/experiment_blueprint.json",
        "--negative-memory",
        "tests/fixtures/resmax_core/valid/negative_memory.json",
    ])
    assert ok.returncode == 0, ok.stdout + ok.stderr

    bad = _run([
        sys.executable,
        ".agents/skills/_shared/resmax_core/validators/validate_idea_pack.py",
        "--idea-card",
        "tests/fixtures/resmax_core/invalid/idea_card_missing_gap.json",
    ])
    assert bad.returncode == 1
    assert "$.source_gap_ids" in bad.stdout + bad.stderr
