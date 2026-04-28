from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now


PRODUCER = {"name": "resmax_survey_v2.record_source_replenishment", "version": SCHEMA_VERSION, "run_id": "phase3"}

READABLE_SOURCE_FILES = (
    ("paper.tex", "arxiv_tex"),
    ("paper.pdftxt", "official_pdf_text"),
    ("paper.md", "markdown_text"),
    ("manual.md", "manual_text"),
)

AUXILIARY_SOURCE_FILES = (
    ("paper.pdf", "official_pdf"),
    ("arxiv_source.tar.gz", "arxiv_source_tarball"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record legal public source replenishment provenance for a resmax-survey ResearchPack."
    )
    parser.add_argument("--pack", required=True, type=Path, help="ResearchPack directory or parent output directory.")
    parser.add_argument("--paper-id", required=True, help="Paper id from source_materialization_report.json.")
    parser.add_argument("--source-url", action="append", required=True, help="Legal public source URL; repeatable.")
    parser.add_argument("--cache-dir", type=Path, help="Replenished global source cache directory for this paper.")
    parser.add_argument("--method", default="legal_public_web_search")
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)

    try:
        log_path, log = record_source_replenishment(
            pack=args.pack,
            paper_id=args.paper_id,
            source_urls=args.source_url or [],
            cache_dir=args.cache_dir,
            method=args.method,
            note=args.note,
        )
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    print(
        f"wrote {log_path} with {log['record_count']} replenishment record(s); "
        f"recorded {args.paper_id}"
    )
    return 0


def record_source_replenishment(
    *,
    pack: Path,
    paper_id: str,
    source_urls: list[str],
    cache_dir: Path | None = None,
    method: str = "legal_public_web_search",
    note: str = "",
) -> tuple[Path, dict[str, Any]]:
    pack_dir = _resolve_pack_dir(pack)
    report_path = pack_dir / "source_materialization_report.json"
    if not report_path.exists():
        raise FileNotFoundError(f"source materialization report not found: {report_path}")

    report = _load_json(report_path)
    source_urls = _dedup_strings(source_urls)
    _validate_source_urls(source_urls)

    replenishment_entry = _find_replenishment_entry(report, paper_id)
    report_record = _find_materialization_record(report, paper_id)
    resolved_cache_dir = _resolve_cache_dir(report, replenishment_entry, paper_id, cache_dir)
    if not resolved_cache_dir.exists() or not resolved_cache_dir.is_dir():
        raise FileNotFoundError(f"source cache directory not found: {resolved_cache_dir}")

    readable_files = _cache_file_records(resolved_cache_dir, READABLE_SOURCE_FILES)
    if not readable_files:
        raise ValueError(
            "replenished cache has no readable full-text file; expected one of "
            + ", ".join(filename for filename, _kind in READABLE_SOURCE_FILES)
        )

    auxiliary_files = _cache_file_records(resolved_cache_dir, AUXILIARY_SOURCE_FILES)
    title = str((replenishment_entry or report_record).get("title", "") if (replenishment_entry or report_record) else "")
    record_input = {
        "paper_id": paper_id,
        "title": title,
        "method": method,
        "source_urls": source_urls,
        "cache_dir": str(resolved_cache_dir),
        "readable_source_files": readable_files,
        "auxiliary_source_files": auxiliary_files,
        "source_materialization_report": "source_materialization_report.json",
        "source_materialization_report_created_at": report.get("created_at", ""),
        "source_materialization_report_counts": report.get("counts", {}),
        "matching_replenishment_entry_found": replenishment_entry is not None,
        "recovered_doi": str((replenishment_entry or {}).get("recovered_doi", "")),
        "note": note,
    }
    record = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("source_replenishment", record_input),
        "created_at": utc_now(),
        "input_hash": input_hash(record_input),
        **record_input,
        "readable_source_count": len(readable_files),
    }

    log_path = pack_dir / "source_replenishment_log.json"
    existing = _load_existing_log(log_path)
    records = [row for row in existing.get("records", []) if row.get("paper_id") != paper_id]
    records.append(record)
    records.sort(key=lambda row: str(row.get("paper_id", "")))

    log_input = {"records": records}
    log = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("source_replenishment_log", log_input),
        "created_at": utc_now(),
        "input_hash": input_hash(log_input),
        "producer": PRODUCER,
        "record_count": len(records),
        "records": records,
    }
    _write_json(log_path, log)
    return log_path, log


def _resolve_pack_dir(path: Path) -> Path:
    path = path.resolve()
    return path if path.name == "research_pack" else path / "research_pack"


def _resolve_cache_dir(
    report: dict[str, Any],
    replenishment_entry: dict[str, Any] | None,
    paper_id: str,
    cache_dir: Path | None,
) -> Path:
    if cache_dir is not None:
        return cache_dir.resolve()
    if replenishment_entry and replenishment_entry.get("cache_dir"):
        return Path(str(replenishment_entry["cache_dir"])).resolve()
    base = str(report.get("cache_dir", "")).strip()
    if not base:
        raise ValueError("cache dir must be supplied when source_materialization_report.json has no cache_dir")
    return (Path(base) / _safe_id(paper_id)).resolve()


def _find_replenishment_entry(report: dict[str, Any], paper_id: str) -> dict[str, Any] | None:
    for entry in report.get("web_search_replenishment", []):
        if isinstance(entry, dict) and entry.get("paper_id") == paper_id:
            return entry
    return None


def _find_materialization_record(report: dict[str, Any], paper_id: str) -> dict[str, Any] | None:
    for record in report.get("records", []):
        if isinstance(record, dict) and record.get("paper_id") == paper_id:
            return record
    return None


def _cache_file_records(cache_dir: Path, specs: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for filename, source_type in specs:
        path = cache_dir / filename
        if not path.exists() or not path.is_file():
            continue
        size = path.stat().st_size
        if size <= 0:
            continue
        records.append(
            {
                "filename": filename,
                "source_type": source_type,
                "path": str(path),
                "size_bytes": size,
                "sha256": _sha256_file(path),
            }
        )
    return records


def _load_existing_log(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"records": []}
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"source replenishment log must be a JSON object: {path}")
    records = payload.get("records", [])
    if not isinstance(records, list):
        raise ValueError(f"source replenishment log records must be a list: {path}")
    return payload


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _validate_source_urls(urls: list[str]) -> None:
    if not urls:
        raise ValueError("at least one --source-url is required")
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"source URL must be http(s): {url}")


def _dedup_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = str(value).strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _safe_id(paper_id: str) -> str:
    return paper_id.replace("/", "__").replace(":", "_")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
