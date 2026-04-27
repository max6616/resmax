from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / ".agents" / "skills" / "_shared"
CORE = SHARED / "resmax_core"
SCHEMAS = CORE / "schemas"
sys.path.insert(0, str(SHARED))

from resmax_core import SCHEMA_VERSION  # noqa: E402
from resmax_core.ids import input_hash, make_state_id, stable_hash  # noqa: E402
from resmax_core.state import DecisionStatus, EvidenceStatus, Producer, SourceWeight  # noqa: E402
from resmax_core.trace import append_jsonl, make_trace_event  # noqa: E402


REQUIRED_SCHEMAS = {
    "research_spec.schema.json",
    "source_policy.schema.json",
    "query_family.schema.json",
    "retrieval_trace.schema.json",
    "evidence_span.schema.json",
    "evidence_card.schema.json",
    "claim_graph.schema.json",
    "gap_map.schema.json",
    "research_pack_manifest.schema.json",
    "idea_card.schema.json",
    "review_trace.schema.json",
    "experiment_blueprint.schema.json",
    "negative_memory.schema.json",
}


def test_required_schemas_exist_and_pin_schema_version() -> None:
    found = {path.name for path in SCHEMAS.glob("*.schema.json")}
    assert REQUIRED_SCHEMAS <= found

    for schema_path in SCHEMAS.glob("*.schema.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["schema_version"] == SCHEMA_VERSION
        assert "schema_version" in schema["required"]
        assert schema["properties"]["schema_version"]["enum"] == [SCHEMA_VERSION]


def test_state_enums_keep_unknown_statuses_distinct() -> None:
    assert EvidenceStatus.UNKNOWN.value == "unknown"
    assert EvidenceStatus.NOT_FOUND.value == "not_found"
    assert EvidenceStatus.NOT_APPLICABLE.value == "not_applicable"
    assert EvidenceStatus.INSUFFICIENT_EVIDENCE.value == "insufficient_evidence"
    assert SourceWeight.PRIMARY.value == "primary"
    assert DecisionStatus.NEEDS_REVISION.value == "needs_revision"


def test_hash_and_state_id_helpers_are_deterministic() -> None:
    left = {"b": [2, 1], "a": {"x": "y"}}
    right = {"a": {"x": "y"}, "b": [2, 1]}
    assert stable_hash(left) == stable_hash(right)
    assert input_hash(left).startswith("sha256:")
    assert make_state_id("evidence_card", left) == make_state_id("evidence_card", right)
    assert make_state_id("evidence_card", left).startswith("evidence_card:")

    with pytest.raises(ValueError):
        make_state_id("EvidenceCard", left)


def test_trace_event_appends_jsonl(tmp_path: Path) -> None:
    event = make_trace_event(
        event_type="validator.pass",
        state_id="evidence_card:12345678",
        producer=Producer(name="pytest", version="0.1.0", run_id="trace"),
        payload={"schema": "evidence_card.schema.json"},
        message="validated",
    )
    out = tmp_path / "trace.jsonl"
    append_jsonl(out, event)
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["schema_version"] == SCHEMA_VERSION
    assert row["trace_id"].startswith("trace_event:")
    assert row["event_type"] == "validator.pass"
    assert row["producer"]["name"] == "pytest"
