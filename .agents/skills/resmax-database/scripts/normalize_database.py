#!/usr/bin/env python3
"""Normalize accepted_index.csv and emit a reproducibility manifest.

This script is intentionally deterministic and local-only. It repairs schema
and value-level issues that should not require network access:

* canonical repository URLs (`code_url`)
* normalized PDF contract fields (`landing_url`, `pdf_url`, `pdf_status`)
* original-text anchor fields (`source_text_*`)
* normalized `has_pdf_camera_ready`
* explicit `review_score_status`
* manifest with hashes and coverage metrics
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import sys

_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
from data_contracts import (  # noqa: E402
    derive_pdf_contract,
    derive_source_text_contract,
    is_valid_abstract,
    normalize_repo_url,
    normalize_yes_no,
    review_score_status,
)


NORMALIZED_FIELDS = [
    "landing_url",
    "pdf_url",
    "pdf_status",
    "pdf_source",
    "source_text_status",
    "source_text_url",
    "source_text_source",
    "source_text_evidence",
    "source_text_search_query",
    "source_text_checked_at",
    "abstract_status",
    "review_score_status",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path) -> tuple[list[str], list[dict]]:
    csv.field_size_limit(100 * 1024 * 1024)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def abstract_status(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "missing"
    if text.lower() in {"none", "null", "nan", "n/a"}:
        return "placeholder"
    if len(text) < 80:
        return "short"
    return "ok"


def normalize_rows(rows: list[dict], fieldnames: list[str]) -> dict:
    for field in NORMALIZED_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)

    stats = Counter()
    by_conf_year: dict[str, Counter] = defaultdict(Counter)
    checked_at = datetime.now(timezone.utc).isoformat()

    for row in rows:
        cy = row.get("conf_year", "UNKNOWN")

        old_code = (row.get("code_url", "") or "").strip()
        new_code = normalize_repo_url(old_code) if old_code else ""
        if old_code != new_code:
            stats["code_url_normalized"] += 1
            row["code_url"] = new_code

        old_pdf_flag = row.get("has_pdf_camera_ready", "")
        new_pdf_flag = normalize_yes_no(old_pdf_flag)
        if old_pdf_flag != new_pdf_flag:
            stats["has_pdf_camera_ready_normalized"] += 1
            row["has_pdf_camera_ready"] = new_pdf_flag

        a_status = abstract_status(row.get("abstract_raw", ""))
        row["abstract_status"] = a_status
        if a_status == "placeholder":
            row["abstract_raw"] = ""
            stats["abstract_placeholder_cleared"] += 1

        pdf = derive_pdf_contract(row)
        row["landing_url"] = pdf.landing_url
        row["pdf_url"] = pdf.pdf_url
        row["pdf_status"] = pdf.pdf_status
        row["pdf_source"] = pdf.pdf_source

        if pdf.pdf_url and row.get("has_pdf_camera_ready", "") != "yes":
            row["has_pdf_camera_ready"] = "yes"

        source_text = derive_source_text_contract(row)
        row["source_text_status"] = source_text.source_text_status
        row["source_text_url"] = source_text.source_text_url
        row["source_text_source"] = source_text.source_text_source
        row["source_text_evidence"] = source_text.source_text_evidence
        row["source_text_search_query"] = source_text.source_text_search_query
        row["source_text_checked_at"] = checked_at

        row["review_score_status"] = review_score_status(row)

        stats[f"pdf_status:{row['pdf_status']}"] += 1
        stats[f"source_text_status:{row['source_text_status']}"] += 1
        stats[f"review_score_status:{row['review_score_status']}"] += 1
        by_conf_year[cy][f"abstract_status:{row['abstract_status']}"] += 1
        by_conf_year[cy][f"pdf_status:{row['pdf_status']}"] += 1
        by_conf_year[cy][f"source_text_status:{row['source_text_status']}"] += 1
        by_conf_year[cy][f"review_score_status:{row['review_score_status']}"] += 1

    return {
        "rows": len(rows),
        "changes": dict(stats),
        "conf_year_stats": {k: dict(v) for k, v in sorted(by_conf_year.items())},
    }


def parse_coverage_report(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "source_status": {}}
    source_status: dict[str, dict] = {}
    current = ""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            current = m.group(1).strip()
            source_status[current] = {}
            continue
        if not current:
            continue
        kv = re.match(r"^-\s+([a-zA-Z_]+):\s+(.+)$", line)
        if kv:
            source_status[current][kv.group(1)] = kv.group(2).strip()
    return {
        "path": str(path),
        "exists": True,
        "sha256": sha256_file(path),
        "source_status": source_status,
    }


def hash_tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    out: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = str(path.relative_to(root))
        out[rel] = sha256_file(path)
    return out


def embedding_manifest(cache_path: Path, csv_ids: set[str]) -> dict:
    if not cache_path.exists():
        return {"path": str(cache_path), "exists": False}
    result = {
        "path": str(cache_path),
        "exists": True,
        "sha256": sha256_file(cache_path),
        "safe_load": True,
    }
    try:
        import numpy as np

        try:
            data = np.load(cache_path, allow_pickle=False)
            requires_pickle = False
        except ValueError:
            data = np.load(cache_path, allow_pickle=True)
            requires_pickle = True
            result["safe_load"] = False
        ids = [str(x) for x in data["paper_ids"].tolist()]
        cached = set(ids)
        result.update({
            "requires_pickle": requires_pickle,
            "cached_papers": len(cached),
            "csv_papers": len(csv_ids),
            "overlap_pct": round(len(cached & csv_ids) * 100 / len(csv_ids), 2) if csv_ids else 0,
            "missing_in_cache": len(csv_ids - cached),
            "orphaned_in_cache": len(cached - csv_ids),
            "embedding_dim": int(data["embeddings"].shape[1]) if data["embeddings"].ndim == 2 else None,
        })
        if "meta" in data:
            result["meta"] = json.loads(str(data["meta"]))
    except Exception as exc:
        result.update({"safe_load": False, "error": f"{type(exc).__name__}: {exc}"})
    return result


def build_manifest(
    *,
    csv_path: Path,
    rows: list[dict],
    registry_path: Path,
    coverage_report_path: Path,
    fixtures_dir: Path,
    cache_path: Path,
    command: list[str],
) -> dict:
    total = len(rows)
    csv_ids = {
        r.get("paper_id", "")
        for r in rows
        if r.get("paper_id", "") and is_valid_abstract(r.get("abstract_raw", ""))
    }
    valid_abs = sum(1 for r in rows if is_valid_abstract(r.get("abstract_raw", "")))
    pdf_available = sum(1 for r in rows if r.get("pdf_status") == "available")
    source_text_status = Counter((r.get("source_text_status", "") or "").strip() or "empty" for r in rows)
    source_text_evidence = sum(1 for r in rows if (r.get("source_text_status", "") or "").strip() and (r.get("source_text_evidence", "") or "").strip())
    doi = sum(1 for r in rows if (r.get("doi", "") or "").strip())
    review_available = Counter((r.get("review_available", "") or "").strip() or "empty" for r in rows)
    review_score = Counter((r.get("review_score_status", "") or "").strip() or "empty" for r in rows)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "csv": {
            "path": str(csv_path),
            "sha256": sha256_file(csv_path),
            "rows": total,
            "columns": len(rows[0].keys()) if rows else 0,
        },
        "registry": {
            "path": str(registry_path),
            "exists": registry_path.exists(),
            "sha256": sha256_file(registry_path) if registry_path.exists() else "",
        },
        "coverage": {
            "valid_abstract_pct": round(valid_abs * 100 / total, 2) if total else 0,
            "doi_pct": round(doi * 100 / total, 2) if total else 0,
            "pdf_available_pct": round(pdf_available * 100 / total, 2) if total else 0,
            "source_text_evidence_pct": round(source_text_evidence * 100 / total, 2) if total else 0,
            "source_text_status_counts": dict(source_text_status),
            "review_available_counts": dict(review_available),
            "review_score_status_counts": dict(review_score),
        },
        "source_report": parse_coverage_report(coverage_report_path),
        "fixtures": {
            "root": str(fixtures_dir),
            "files": hash_tree(fixtures_dir),
        },
        "embedding": embedding_manifest(cache_path, csv_ids),
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", default="paper_database/accepted_index.csv")
    p.add_argument("--registry", default=".agents/skills/resmax-database/config/source_registry.json")
    p.add_argument("--coverage-report", default="paper_database/accepted_index_coverage_report.md")
    p.add_argument("--fixtures-dir", default=".agents/skills/resmax-database/fixtures")
    p.add_argument("--cache", default="paper_database/embedding_cache/qwen3_8b.npz")
    p.add_argument("--manifest", default="paper_database/manifest.json")
    p.add_argument("--skip-normalize", action="store_true")
    p.add_argument("--skip-manifest", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[ERROR] CSV not found: {csv_path}", file=sys.stderr)
        return 1

    fieldnames, rows = load_csv(csv_path)
    normalize_report = {"rows": len(rows), "changes": {}, "conf_year_stats": {}}
    if not args.skip_normalize:
        normalize_report = normalize_rows(rows, fieldnames)

    if args.dry_run:
        print(json.dumps({"normalize": normalize_report}, ensure_ascii=False, indent=2))
        return 0

    if not args.skip_normalize:
        write_csv(csv_path, fieldnames, rows)
        print(f"[normalize] wrote normalized CSV: {csv_path}")

    if not args.skip_manifest:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = build_manifest(
            csv_path=csv_path,
            rows=rows,
            registry_path=Path(args.registry),
            coverage_report_path=Path(args.coverage_report),
            fixtures_dir=Path(args.fixtures_dir),
            cache_path=Path(args.cache),
            command=["normalize_database.py", *sys.argv[1:]],
        )
        manifest["normalize"] = normalize_report
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[manifest] wrote: {manifest_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
