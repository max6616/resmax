from __future__ import annotations

import csv
from pathlib import Path

from .models import AcceptedPaperRecord
from .normalize import normalize_authors, normalize_title, normalize_whitespace, slugify_short_title

# Core fields defined on AcceptedPaperRecord; CSV may additionally contain
# enrich-only columns (review_*, code_is_real, code_stars, has_pretrained_weights,
# etc.) that we carry on AcceptedPaperRecord.extras untouched.
CORE_FIELDNAMES = [
    "paper_id",
    "short_id",
    "venue",
    "year",
    "conf_year",
    "title",
    "authors",
    "source_type",
    "source_url",
    "paper_link",
    "arxiv_id",
    "arxiv_url",
    "keywords_raw",
    "abstract_raw",
    "doi",
    "openreview_forum_id",
    "has_pdf_camera_ready",
    "decision",
    "acceptance_type",
    "topic",
    "code_url",
    "paper_url",
    "virtual_id",
    "virtual_uid",
    "virtualsite_url",
    "sourceid",
    "sourceurl",
    "session",
    "eventtype",
    "event_type",
    "room_name",
    "starttime",
    "endtime",
    "poster_position",
]

# Deprecated alias kept for backwards compatibility; new code should use CORE_FIELDNAMES.
FIELDNAMES = CORE_FIELDNAMES


def merge_prefer_existing(base: AcceptedPaperRecord, incoming: AcceptedPaperRecord) -> AcceptedPaperRecord:
    for field in CORE_FIELDNAMES:
        if field in {"paper_id", "short_id"}:
            continue
        current = getattr(base, field)
        new_value = getattr(incoming, field)
        if (current is None or current == "") and new_value not in (None, ""):
            setattr(base, field, new_value)
    # Merge extras: base wins on non-empty conflicts; incoming fills holes.
    # Work on a fresh dict so we never mutate an alias shared with another record.
    base_extras = dict(base.extras) if isinstance(base.extras, dict) else {}
    inc_extras = incoming.extras if isinstance(incoming.extras, dict) else {}
    for k, v in inc_extras.items():
        if v in (None, ""):
            continue
        if not base_extras.get(k):
            base_extras[k] = v
    base.extras = base_extras
    return base


def record_key(record: AcceptedPaperRecord) -> tuple[str, int, str]:
    return (record.venue.upper(), int(record.year), normalize_title(record.title))


def load_existing_records(path: Path) -> list[AcceptedPaperRecord]:
    if not path.exists():
        return []
    records: list[AcceptedPaperRecord] = []
    csv.field_size_limit(100 * 1024 * 1024)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            kwargs = {}
            for fn in CORE_FIELDNAMES:
                val = row.get(fn, "")
                if fn == "year":
                    kwargs[fn] = int(val or 0)
                else:
                    kwargs[fn] = val or ""
            extras = {
                k: (v or "")
                for k, v in row.items()
                if k and k not in CORE_FIELDNAMES
            }
            records.append(AcceptedPaperRecord(**kwargs, extras=extras))
    return records


def assign_stable_ids(records: list[AcceptedPaperRecord], existing_records: list[AcceptedPaperRecord]) -> list[AcceptedPaperRecord]:
    existing_map = {record_key(r): r for r in existing_records}
    counters: dict[str, int] = {}
    for r in existing_records:
        venue = r.venue.upper()
        counters[venue] = max(counters.get(venue, 0), _extract_short_seq(r.short_id))

    for record in records:
        record.title = normalize_whitespace(record.title)
        record.authors = normalize_authors(record.authors)
        key = record_key(record)
        if key in existing_map:
            existing = existing_map[key]
            record.paper_id = existing.paper_id
            record.short_id = existing.short_id
            continue
        venue = record.venue.upper()
        counters[venue] = counters.get(venue, 0) + 1
        seq = counters[venue]
        record.paper_id = f"{record.conf_year}::{normalize_title(record.title).replace(' ', '_')}"
        record.short_id = f"{venue}_{record.year}_A{seq:03d}_{slugify_short_title(record.title)}"
    return records


def _extract_short_seq(short_id: str) -> int:
    if "_A" not in short_id:
        return 0
    try:
        return int(short_id.split("_A", 1)[1].split("_", 1)[0])
    except Exception:
        return 0


def merge_records(primary_records: list[AcceptedPaperRecord], auxiliary_records: list[AcceptedPaperRecord], existing_records: list[AcceptedPaperRecord]) -> list[AcceptedPaperRecord]:
    existing_map: dict[tuple[str, int, str], AcceptedPaperRecord] = {}
    for record in existing_records:
        existing_map[record_key(record)] = record

    merged: dict[tuple[str, int, str], AcceptedPaperRecord] = {}
    for record in primary_records + auxiliary_records:
        key = record_key(record)
        if key in merged:
            merged[key] = merge_prefer_existing(merged[key], record)
        else:
            merged[key] = AcceptedPaperRecord(**record.__dict__)

    for key, record in merged.items():
        if key in existing_map:
            record = merge_prefer_existing(record, existing_map[key])
            merged[key] = merge_prefer_existing(existing_map[key], record)

    output = list(merged.values())
    output.sort(key=lambda r: (r.venue.upper(), int(r.year), normalize_title(r.title)))
    return assign_stable_ids(output, existing_records)


def write_csv(path: Path, records: list[AcceptedPaperRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    # Collect every extras key that appears on any record. We write them
    # after the core fields in deterministic order so the header layout is
    # stable across builds.
    extra_keys: set[str] = set()
    for r in records:
        if isinstance(r.extras, dict):
            extra_keys.update(k for k in r.extras.keys() if k)
    ordered_extras = sorted(extra_keys)
    fieldnames = CORE_FIELDNAMES + ordered_extras

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = {fn: getattr(record, fn, "") for fn in CORE_FIELDNAMES}
            extras = record.extras if isinstance(record.extras, dict) else {}
            for fn in ordered_extras:
                row[fn] = extras.get(fn, "")
            writer.writerow(row)
