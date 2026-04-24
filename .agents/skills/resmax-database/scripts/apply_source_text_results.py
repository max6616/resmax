#!/usr/bin/env python3
"""Apply reviewed source-text search results back to accepted_index.csv."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import sys

_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
from data_contracts import SOURCE_TEXT_STATUS_VALUES, is_pdf_like_url, normalize_http_url  # noqa: E402


REQUIRED_RESULT_FIELDS = {
    "paper_id",
    "source_text_status",
    "source_text_url",
    "source_text_source",
    "source_text_evidence",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="paper_database/accepted_index.csv")
    parser.add_argument("--results-jsonl", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    csv.field_size_limit(100 * 1024 * 1024)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_results(path: Path) -> list[dict]:
    out = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        missing = REQUIRED_RESULT_FIELDS - set(item)
        if missing:
            raise ValueError(f"{path}:{lineno}: missing fields {sorted(missing)}")
        status = str(item.get("source_text_status", "")).strip()
        if status not in SOURCE_TEXT_STATUS_VALUES or not status:
            raise ValueError(f"{path}:{lineno}: invalid source_text_status={status!r}")
        url = normalize_http_url(str(item.get("source_text_url", "")))
        if status not in {"missing_anchor_needs_search", "unresolved_after_search"} and not url:
            raise ValueError(f"{path}:{lineno}: {status} requires source_text_url")
        evidence = item.get("source_text_evidence")
        if isinstance(evidence, dict):
            item["source_text_evidence"] = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
        elif not str(evidence or "").strip():
            raise ValueError(f"{path}:{lineno}: source_text_evidence is empty")
        item["source_text_status"] = status
        item["source_text_url"] = url
        out.append(item)
    return out


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv)
    fields, rows = _load_csv(csv_path)
    for field in [
        "source_text_status",
        "source_text_url",
        "source_text_source",
        "source_text_evidence",
        "source_text_search_query",
        "source_text_checked_at",
        "pdf_url",
        "pdf_status",
        "pdf_source",
        "has_pdf_camera_ready",
    ]:
        if field not in fields:
            fields.append(field)

    by_id = {row.get("paper_id", ""): row for row in rows}
    results = _load_results(Path(args.results_jsonl))
    checked_at = datetime.now(timezone.utc).isoformat()
    updated = 0
    missing_ids = []

    for item in results:
        paper_id = str(item["paper_id"])
        row = by_id.get(paper_id)
        if not row:
            missing_ids.append(paper_id)
            continue
        status = item["source_text_status"]
        url = item["source_text_url"]
        row["source_text_status"] = status
        row["source_text_url"] = url
        row["source_text_source"] = str(item.get("source_text_source", ""))
        row["source_text_evidence"] = str(item.get("source_text_evidence", ""))
        row["source_text_search_query"] = str(item.get("source_text_search_query", row.get("source_text_search_query", "")))
        row["source_text_checked_at"] = checked_at

        if status in {"pdf_available", "preprint_available"}:
            if not is_pdf_like_url(url):
                raise ValueError(f"{paper_id}: {status} result URL does not look like a PDF: {url}")
            row["pdf_url"] = url
            row["pdf_status"] = "available"
            row["pdf_source"] = row["source_text_source"] or "web_search"
            row["has_pdf_camera_ready"] = "yes"
        updated += 1

    if missing_ids:
        raise ValueError(f"{len(missing_ids)} result paper_ids not in CSV, sample={missing_ids[:5]}")

    if not args.dry_run:
        _write_csv(csv_path, fields, rows)
    print(json.dumps({"updated": updated, "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
