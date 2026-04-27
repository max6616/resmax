"""Shared state contracts and validation helpers for Resmax research artifacts."""

from .ids import canonical_json, input_hash, make_state_id, stable_hash
from .corpus_api import (
    CorpusHandle,
    PaperHit,
    PaperRecord,
    RetrievalTrace,
    ReviewRecord,
    SearchResults,
    SourceTextRecord,
    fetch_paper,
    fetch_review,
    fetch_source_text,
    load_corpus,
    search_papers,
)
from .state import (
    COMMON_STATE_FIELDS,
    SCHEMA_VERSION,
    DecisionStatus,
    EvidenceStatus,
    Producer,
    SourceWeight,
    StateEnvelope,
    utc_now,
)
from .trace import TraceEvent, append_jsonl, make_trace_event

__all__ = [
    "COMMON_STATE_FIELDS",
    "CorpusHandle",
    "SCHEMA_VERSION",
    "DecisionStatus",
    "EvidenceStatus",
    "PaperHit",
    "PaperRecord",
    "Producer",
    "RetrievalTrace",
    "ReviewRecord",
    "SourceWeight",
    "SearchResults",
    "StateEnvelope",
    "SourceTextRecord",
    "TraceEvent",
    "append_jsonl",
    "canonical_json",
    "fetch_paper",
    "fetch_review",
    "fetch_source_text",
    "input_hash",
    "load_corpus",
    "make_state_id",
    "make_trace_event",
    "search_papers",
    "stable_hash",
    "utc_now",
]
