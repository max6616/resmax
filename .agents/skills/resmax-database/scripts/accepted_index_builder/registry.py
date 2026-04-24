from __future__ import annotations

import json
from pathlib import Path

from .models import ConferenceYearConfig, SourceConfig


def _load_source(raw: dict) -> SourceConfig:
    return SourceConfig(
        kind=str(raw.get("kind", "")).strip(),
        url=str(raw.get("url", "")).strip(),
        parser=str(raw.get("parser", "")).strip(),
        expected_count=raw.get("expected_count"),
        parser_args=raw.get("parser_args"),
    )


def load_registry(path: Path) -> list[ConferenceYearConfig]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for raw in data.get("conference_years", []):
        items.append(
            ConferenceYearConfig(
                venue=str(raw.get("venue", "")).strip(),
                year=int(raw.get("year", 0)),
                conf_year=str(raw.get("conf_year", "")).strip(),
                status=str(raw.get("status", "active")).strip(),
                skip_reason=str(raw.get("skip_reason", "")).strip(),
                primary_source=_load_source(raw.get("primary_source", {})),
                auxiliary_sources=[_load_source(x) for x in raw.get("auxiliary_sources", [])],
                notes=str(raw.get("notes", "")).strip(),
            )
        )
    return items
