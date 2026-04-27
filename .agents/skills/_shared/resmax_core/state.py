from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


SCHEMA_VERSION = "0.1.0"

COMMON_STATE_FIELDS = (
    "schema_version",
    "state_id",
    "created_at",
    "input_hash",
    "parent_state_ids",
    "producer",
)


class EvidenceStatus(str, Enum):
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    MIXED = "mixed"


class SourceWeight(str, Enum):
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"
    WEAK = "weak"


class DecisionStatus(str, Enum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"
    KILLED = "killed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Producer:
    name: str
    version: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class StateEnvelope:
    schema_version: str
    state_id: str
    created_at: str
    input_hash: str
    producer: Producer
    parent_state_ids: list[str] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
