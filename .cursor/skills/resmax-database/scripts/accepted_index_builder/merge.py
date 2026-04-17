from __future__ import annotations

import csv
from pathlib import Path

from .models import AcceptedPaperRecord
from .normalize import normalize_authors, normalize_title, normalize_whitespace, slugify_short_title

FIELDNAMES = [
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
]


def merge_prefer_existing(base: AcceptedPaperRecord, incoming: AcceptedPaperRecord) -> AcceptedPaperRecord:
    for field in FIELDNAMES:
        if field in {"paper_id", "short_id"}:
            continue
        current = getattr(base, field)
        new_value = getattr(incoming, field)
        if (current is None or current == "") and new_value not in (None, ""):
            setattr(base, field, new_value)
    return base


def record_key(record: AcceptedPaperRecord) -> tuple[str, int, str]:
    return (record.venue.upper(), int(record.year), normalize_title(record.title))


def load_existing_records(path: Path) -> list[AcceptedPaperRecord]:
    if not path.exists():
        return []
    records: list[AcceptedPaperRecord] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(
                AcceptedPaperRecord(
                    paper_id=row.get("paper_id", ""),
                    short_id=row.get("short_id", ""),
                    venue=row.get("venue", ""),
                    year=int(row.get("year", 0) or 0),
                    conf_year=row.get("conf_year", ""),
                    title=row.get("title", ""),
                    authors=row.get("authors", ""),
                    source_type=row.get("source_type", ""),
                    source_url=row.get("source_url", ""),
                    paper_link=row.get("paper_link", ""),
                    arxiv_id=row.get("arxiv_id", ""),
                    arxiv_url=row.get("arxiv_url", ""),
                    keywords_raw=row.get("keywords_raw", ""),
                    abstract_raw=row.get("abstract_raw", ""),
                    doi=row.get("doi", ""),
                    openreview_forum_id=row.get("openreview_forum_id", ""),
                    has_pdf_camera_ready=row.get("has_pdf_camera_ready", ""),
                )
            )
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
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for record in records:
            row = {field: getattr(record, field) for field in FIELDNAMES}
            writer.writerow(row)
