#!/usr/bin/env python3
"""Package OpenReview JSON cache into Hub-friendly review shards.

The raw cache contains tens of thousands of small JSON files. Uploading them
directly to the Hub makes the repository hard to browse and slow to sync. This
script keeps the original JSON payloads intact, but groups them by conf_year
into deterministic tar.zst shards and writes a row-level index for lookup.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import tarfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_csv(path: Path) -> list[dict]:
    csv.field_size_limit(100 * 1024 * 1024)
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def reviews_relative_path(raw: str, reviews_dir: Path, row: dict | None = None) -> str:
    text = (raw or "").strip()
    if text:
        p = Path(text)
        parts = p.parts
        if "reviews" in parts:
            idx = parts.index("reviews")
            return str(Path(*parts[idx + 1:]))
        try:
            return str(p.resolve().relative_to(reviews_dir.resolve()))
        except Exception:
            pass
        if len(parts) >= 2:
            return str(Path(*parts[-2:]))
    if row:
        conf_year = row.get("conf_year", "").strip()
        forum_id = row.get("openreview_forum_id", "").strip()
        if conf_year and forum_id:
            return str(Path(conf_year) / f"{forum_id}.json")
    return text


def read_review_summary(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "json_parse_ok": "no",
            "json_error": f"{type(exc).__name__}: {exc}",
        }
    reviews = doc.get("reviews", []) or []
    return {
        "json_parse_ok": "yes",
        "json_error": "",
        "json_paper_id": str(doc.get("paper_id", "") or ""),
        "json_forum_id": str(doc.get("forum_id", "") or ""),
        "json_reviews_count": str(len(reviews)),
        "json_decision": str(doc.get("decision", "") or ""),
        "json_fetched_at": str(doc.get("fetched_at", "") or ""),
    }


def make_tar_zst(archive_path: Path, members: list[tuple[Path, str]], level: int) -> dict:
    try:
        import zstandard as zstd
    except ImportError as exc:
        raise RuntimeError("zstandard is required to write .tar.zst archives") from exc

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    uncompressed_bytes = 0
    with archive_path.open("wb") as raw:
        cctx = zstd.ZstdCompressor(level=level, threads=0, write_checksum=True)
        with cctx.stream_writer(raw, closefd=False) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as tar:
                for src, member_name in members:
                    data = src.read_bytes()
                    uncompressed_bytes += len(data)
                    info = tarfile.TarInfo(member_name)
                    info.size = len(data)
                    info.mtime = 0
                    info.mode = 0o644
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    tar.addfile(info, io.BytesIO(data))
    return {
        "path": str(archive_path),
        "bytes": archive_path.stat().st_size,
        "uncompressed_bytes": uncompressed_bytes,
        "sha256": sha256_file(archive_path),
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def maybe_write_parquet(path: Path, rows: list[dict]) -> bool:
    try:
        import pandas as pd
    except ImportError:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return True


def write_readme(path: Path, manifest: dict) -> None:
    shard_lines = []
    for shard in manifest["shards"]:
        shard_lines.append(
            f"| {shard['conf_year']} | {shard['json_files']} | "
            f"{shard['bytes']} | `{shard['path_in_package']}` |"
        )
    content = f"""# Resmax Review Cache

This folder packages the raw OpenReview JSON cache for the Resmax paper
database. The original JSON payloads are preserved inside one tar.zst archive
per `conf_year`.

## Layout

- `reviews_index.csv`: one row per review JSON file, including the archive path
  and tar member path needed to locate the payload.
- `reviews_index.parquet`: the same index in Parquet format when local
  dependencies are available.
- `reviews_manifest.json`: package metadata, source CSV hash, counts, and shard
  checksums.
- `checksums.sha256`: SHA256 checksums for generated upload artifacts.
- `archives/reviews_<conf_year>.tar.zst`: raw JSON shards.

## Summary

- Source CSV rows with `review_available=yes`: {manifest['accepted_review_rows']}
- Review JSON files packaged: {manifest['review_json_files']}
- Missing review JSON files referenced by CSV: {manifest['missing_review_files']}
- Review JSON files not referenced by CSV: {manifest['orphaned_review_files']}

## Shards

| conf_year | JSON files | archive bytes | archive |
| --- | ---: | ---: | --- |
{chr(10).join(shard_lines)}

## Integrity

Use `checksums.sha256` to verify downloaded files. Each index row includes
`json_sha256`, `archive_path`, and `archive_member_path` so consumers can map a
paper row back to the raw review JSON.

## Restore for Resmax

The Resmax database scripts do not read these compressed shards directly. After
downloading this package, run the review availability gate before
`validate_database.py` or `enrich_reviews.py --rehydrate`:

```bash
python3 .agents/skills/resmax-database/scripts/ensure_reviews_available.py \\
  --package-dir paper_database/hf_export/reviews \\
  --reviews-dir paper_database/reviews \\
  --csv paper_database/accepted_index.csv
```

If the package is not already present locally, configure the private Hub repo
before running the same command:

```bash
export RESMAX_HF_DATASET_REPO=<owner>/<dataset-repo>
export RESMAX_HF_REVIEWS_PATH=reviews
```

The ensure script uses the existing raw JSON cache when available, restores this
package when raw JSON is missing, and can download the package from a configured
private Hugging Face dataset repo when neither is present. It verifies
`checksums.sha256`, CSV hash, index paths, archive member hashes, and rejects
unsafe archive paths. It restores files to
`paper_database/reviews/{{conf_year}}/{{forum_id}}.json`, which is the layout
used by existing Resmax skills.
"""
    path.write_text(content, encoding="utf-8")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", default="paper_database/accepted_index.csv")
    p.add_argument("--reviews-dir", default="paper_database/reviews")
    p.add_argument("--out-dir", default="paper_database/hf_export/reviews")
    p.add_argument("--zstd-level", type=int, default=10)
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    csv_path = Path(args.csv)
    reviews_dir = Path(args.reviews_dir)
    out_dir = Path(args.out_dir)
    archive_dir = out_dir / "archives"

    if not csv_path.exists():
        print(f"[ERROR] CSV not found: {csv_path}", file=sys.stderr)
        return 1
    if not reviews_dir.exists():
        print(f"[ERROR] reviews dir not found: {reviews_dir}", file=sys.stderr)
        return 1

    rows = load_csv(csv_path)
    expected: dict[str, dict] = {}
    for row in rows:
        if row.get("review_available", "").strip() != "yes":
            continue
        rel = reviews_relative_path(row.get("review_detail_path", ""), reviews_dir, row)
        if rel:
            expected[rel] = row

    json_paths = sorted(reviews_dir.glob("*/*.json"))
    json_by_rel = {str(p.relative_to(reviews_dir)): p for p in json_paths}
    missing = sorted(set(expected) - set(json_by_rel))
    orphaned = sorted(set(json_by_rel) - set(expected))

    index_rows: list[dict] = []
    by_conf_year: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for rel, path in sorted(json_by_rel.items()):
        conf_year = Path(rel).parts[0]
        member_path = str(Path("reviews") / rel)
        archive_name = f"reviews_{conf_year}.tar.zst"
        archive_rel = str(Path("archives") / archive_name)
        row = expected.get(rel, {})
        summary = read_review_summary(path)
        by_conf_year[conf_year].append((path, member_path))
        index_rows.append({
            "conf_year": conf_year,
            "paper_id": row.get("paper_id", ""),
            "venue": row.get("venue", ""),
            "year": row.get("year", ""),
            "openreview_forum_id": row.get("openreview_forum_id", ""),
            "review_available": row.get("review_available", ""),
            "review_score_status": row.get("review_score_status", ""),
            "review_num_reviewers": row.get("review_num_reviewers", ""),
            "review_score_mean": row.get("review_score_mean", ""),
            "review_confidence_mean": row.get("review_confidence_mean", ""),
            "source_review_detail_path": row.get("review_detail_path", ""),
            "in_accepted_index": "yes" if rel in expected else "no",
            "json_path": str(Path("reviews") / rel),
            "json_bytes": str(path.stat().st_size),
            "json_sha256": sha256_file(path),
            "archive_path": archive_rel,
            "archive_member_path": member_path,
            **summary,
        })

    fields = [
        "conf_year",
        "paper_id",
        "venue",
        "year",
        "openreview_forum_id",
        "review_available",
        "review_score_status",
        "review_num_reviewers",
        "review_score_mean",
        "review_confidence_mean",
        "source_review_detail_path",
        "in_accepted_index",
        "json_path",
        "json_bytes",
        "json_sha256",
        "archive_path",
        "archive_member_path",
        "json_parse_ok",
        "json_error",
        "json_paper_id",
        "json_forum_id",
        "json_reviews_count",
        "json_decision",
        "json_fetched_at",
    ]

    shards = []
    for conf_year, members in sorted(by_conf_year.items()):
        archive_path = archive_dir / f"reviews_{conf_year}.tar.zst"
        info = make_tar_zst(archive_path, members, args.zstd_level)
        shards.append({
            "conf_year": conf_year,
            "json_files": len(members),
            "path": info["path"],
            "path_in_package": str(archive_path.relative_to(out_dir)),
            "bytes": info["bytes"],
            "uncompressed_bytes": info["uncompressed_bytes"],
            "sha256": info["sha256"],
        })
        print(f"[archive] {conf_year}: {len(members)} files -> {archive_path} ({info['bytes']} bytes)")

    out_dir.mkdir(parents=True, exist_ok=True)
    index_csv = out_dir / "reviews_index.csv"
    write_csv(index_csv, index_rows, fields)
    parquet_path = out_dir / "reviews_index.parquet"
    parquet_written = maybe_write_parquet(parquet_path, index_rows)

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_csv": str(csv_path),
        "source_csv_sha256": sha256_file(csv_path),
        "source_reviews_dir": str(reviews_dir),
        "accepted_review_rows": len(expected),
        "review_json_files": len(json_paths),
        "missing_review_files": len(missing),
        "orphaned_review_files": len(orphaned),
        "missing_review_file_sample": missing[:20],
        "orphaned_review_file_sample": orphaned[:20],
        "index": {
            "csv": "reviews_index.csv",
            "csv_sha256": sha256_file(index_csv),
            "rows": len(index_rows),
            "parquet": "reviews_index.parquet" if parquet_written else "",
            "parquet_sha256": sha256_file(parquet_path) if parquet_written else "",
        },
        "archives_format": "tar.zst",
        "archives_member_root": "reviews/",
        "shards": shards,
    }

    manifest_path = out_dir / "reviews_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    readme_path = out_dir / "README.md"
    write_readme(readme_path, manifest)

    checksum_targets = [readme_path, index_csv, manifest_path]
    if parquet_written:
        checksum_targets.append(parquet_path)
    checksum_targets.extend(archive_dir / f"reviews_{s['conf_year']}.tar.zst" for s in shards)
    checksum_lines = [
        f"{sha256_file(path)}  {path.relative_to(out_dir)}"
        for path in checksum_targets
    ]
    checksums_path = out_dir / "checksums.sha256"
    checksums_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print(f"[index] wrote {index_csv} ({len(index_rows)} rows)")
    if parquet_written:
        print(f"[index] wrote {parquet_path}")
    print(f"[manifest] wrote {manifest_path}")
    print(f"[checksums] wrote {checksums_path}")
    if missing:
        print(f"[WARN] {len(missing)} CSV review rows missing JSON files", file=sys.stderr)
    if orphaned:
        print(f"[WARN] {len(orphaned)} JSON files are not referenced by accepted_index.csv", file=sys.stderr)
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
