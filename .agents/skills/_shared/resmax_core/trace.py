from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .ids import input_hash, make_state_id
from .state import SCHEMA_VERSION, Producer, utc_now


@dataclass(frozen=True)
class TraceEvent:
    schema_version: str
    trace_id: str
    created_at: str
    event_type: str
    state_id: str
    producer: Producer
    parent_state_ids: list[str] = field(default_factory=list)
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


def make_trace_event(
    *,
    event_type: str,
    state_id: str,
    producer: Producer,
    payload: dict[str, Any] | None = None,
    parent_state_ids: list[str] | None = None,
    message: str = "",
) -> TraceEvent:
    data = {
        "event_type": event_type,
        "state_id": state_id,
        "producer": asdict(producer),
        "payload_hash": input_hash(payload or {}),
        "parent_state_ids": parent_state_ids or [],
        "message": message,
    }
    return TraceEvent(
        schema_version=SCHEMA_VERSION,
        trace_id=make_state_id("trace_event", data),
        created_at=utc_now(),
        event_type=event_type,
        state_id=state_id,
        producer=producer,
        parent_state_ids=parent_state_ids or [],
        message=message,
        payload=payload or {},
    )


def append_jsonl(path: Path, event: TraceEvent | dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = asdict(event) if isinstance(event, TraceEvent) else event
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
