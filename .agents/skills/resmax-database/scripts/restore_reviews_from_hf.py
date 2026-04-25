#!/usr/bin/env python3
"""Restore Hub-packaged review shards to paper_database/reviews.

The resmax database scripts consume raw JSON files at
`paper_database/reviews/{conf_year}/{forum_id}.json`. Hugging Face exports store
those files in tar.zst shards to avoid uploading tens of thousands of small
files. This script verifies the package and restores the original layout.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath
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


def verify_checksums(package_dir: Path) -> None:
    checksums_path = package_dir / "checksums.sha256"
    if not checksums_path.exists():
        raise FileNotFoundError(f"checksums not found: {checksums_path}")
    for lineno, line in enumerate(checksums_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            expected, rel = line.split(None, 1)
        except ValueError as exc:
            raise ValueError(f"invalid checksum line {lineno}: {line!r}") from exc
        rel_path = Path(rel.strip())
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise ValueError(f"unsafe checksum path on line {lineno}: {rel!r}")
        path = package_dir / rel_path
        if not path.exists():
            raise FileNotFoundError(f"checksum target missing: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"checksum mismatch for {rel}: expected {expected}, got {actual}")


def load_index(package_dir: Path) -> list[dict]:
    index_path = package_dir / "reviews_index.csv"
    if not index_path.exists():
        raise FileNotFoundError(f"index not found: {index_path}")
    return load_csv(index_path)


def reviews_relative_path(raw: str, row: dict | None = None) -> str:
    text = (raw or "").strip()
    if text:
        p = Path(text)
        parts = p.parts
        if "reviews" in parts:
            idx = parts.index("reviews")
            return str(Path(*parts[idx + 1:]))
        if len(parts) >= 2:
            return str(Path(*parts[-2:]))
    if row:
        conf_year = row.get("conf_year", "").strip()
        forum_id = row.get("openreview_forum_id", "").strip()
        if conf_year and forum_id:
            return str(Path(conf_year) / f"{forum_id}.json")
    return text


def expected_from_csv(csv_path: Path) -> set[str]:
    rows = load_csv(csv_path)
    out = set()
    for row in rows:
        if row.get("review_available", "").strip() != "yes":
            continue
        rel = reviews_relative_path(row.get("review_detail_path", ""), row)
        if rel:
            out.add(rel)
    return out


def member_to_output_path(member_name: str, out_dir: Path) -> Path:
    pure = PurePosixPath(member_name)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe archive member path: {member_name!r}")
    parts = pure.parts
    if not parts or parts[0] != "reviews":
        raise ValueError(f"archive member does not start with reviews/: {member_name!r}")
    if len(parts) < 3:
        raise ValueError(f"archive member is too shallow: {member_name!r}")
    return out_dir.joinpath(*parts[1:])


def selected_archives(manifest: dict, conf_years: set[str] | None) -> list[dict]:
    shards = manifest.get("shards", [])
    if not isinstance(shards, list):
        raise ValueError("manifest.shards must be a list")
    selected = []
    available = set()
    for shard in shards:
        cy = str(shard.get("conf_year", ""))
        available.add(cy)
        if conf_years is None or cy in conf_years:
            selected.append(shard)
    if conf_years:
        missing = sorted(conf_years - available)
        if missing:
            raise ValueError(f"requested conf_years not in package: {missing}")
    return selected


def restore_archive(
    *,
    archive_path: Path,
    out_dir: Path,
    index_by_member: dict[str, dict],
    overwrite: bool,
    dry_run: bool,
) -> tuple[int, int, int]:
    try:
        import zstandard as zstd
    except ImportError as exc:
        raise RuntimeError(
            "zstandard is required to restore .tar.zst review shards. "
            "Install scripts/requirements.txt first."
        ) from exc

    restored = 0
    skipped = 0
    members = 0
    dctx = zstd.ZstdDecompressor()
    with archive_path.open("rb") as f, dctx.stream_reader(f) as reader, tarfile.open(fileobj=reader, mode="r|") as tar:
        for member in tar:
            if not member.isfile():
                continue
            members += 1
            out_path = member_to_output_path(member.name, out_dir)
            expected = index_by_member.get(member.name, {}).get("json_sha256", "")
            if out_path.exists():
                actual = sha256_file(out_path)
                if expected and actual == expected:
                    skipped += 1
                    continue
                if not overwrite:
                    raise FileExistsError(
                        f"existing file differs and --overwrite was not set: {out_path}"
                    )
            if dry_run:
                restored += 1
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError(f"cannot extract member: {member.name}")
            data = extracted.read()
            if expected:
                actual_data = hashlib.sha256(data).hexdigest()
                if actual_data != expected:
                    raise ValueError(
                        f"archive member hash mismatch for {member.name}: "
                        f"expected {expected}, got {actual_data}"
                    )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            restored += 1
    return restored, skipped, members


def verify_restored(index_rows: list[dict], out_dir: Path, conf_years: set[str] | None) -> tuple[int, int]:
    checked = 0
    missing = 0
    for row in index_rows:
        if conf_years is not None and row.get("conf_year", "") not in conf_years:
            continue
        member = row.get("archive_member_path", "")
        out_path = member_to_output_path(member, out_dir)
        checked += 1
        if not out_path.exists():
            missing += 1
            continue
        expected = row.get("json_sha256", "")
        if expected and sha256_file(out_path) != expected:
            raise ValueError(f"restored file hash mismatch: {out_path}")
    return checked, missing


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--package-dir", default="paper_database/hf_export/reviews")
    p.add_argument("--out-dir", default="paper_database/reviews")
    p.add_argument("--csv", default="paper_database/accepted_index.csv")
    p.add_argument("--conf-years", nargs="*", default=None)
    p.add_argument("--skip-checksums", action="store_true")
    p.add_argument("--allow-csv-hash-mismatch", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    package_dir = Path(args.package_dir)
    out_dir = Path(args.out_dir)
    csv_path = Path(args.csv)
    conf_years = set(args.conf_years) if args.conf_years else None

    manifest_path = package_dir / "reviews_manifest.json"
    if not manifest_path.exists():
        print(f"[ERROR] manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if not args.skip_checksums:
        verify_checksums(package_dir)
        print("[verify] checksums OK")

    if csv_path.exists() and not args.allow_csv_hash_mismatch:
        actual_csv_sha = sha256_file(csv_path)
        expected_csv_sha = manifest.get("source_csv_sha256", "")
        if expected_csv_sha and actual_csv_sha != expected_csv_sha:
            print(
                f"[ERROR] CSV hash mismatch: expected {expected_csv_sha}, got {actual_csv_sha}. "
                "Use --allow-csv-hash-mismatch only if you know the review package matches your CSV.",
                file=sys.stderr,
            )
            return 1

    index_rows = load_index(package_dir)
    if len(index_rows) != int(manifest.get("review_json_files", -1)):
        print(
            f"[ERROR] index rows {len(index_rows)} != manifest review_json_files "
            f"{manifest.get('review_json_files')}",
            file=sys.stderr,
        )
        return 1

    if csv_path.exists():
        expected = expected_from_csv(csv_path)
        indexed = {
            str(Path(row["archive_member_path"]).relative_to("reviews"))
            for row in index_rows
        }
        if conf_years is not None:
            expected = {
                rel for rel in expected
                if Path(rel).parts and Path(rel).parts[0] in conf_years
            }
            indexed = {
                rel for rel in indexed
                if Path(rel).parts and Path(rel).parts[0] in conf_years
            }
        missing_from_index = expected - indexed
        extra_in_index = indexed - expected
        if missing_from_index or extra_in_index:
            print(
                f"[ERROR] CSV/index review path mismatch: "
                f"missing_from_index={len(missing_from_index)}, extra_in_index={len(extra_in_index)}",
                file=sys.stderr,
            )
            if missing_from_index:
                print(f"  missing sample: {sorted(missing_from_index)[:5]}", file=sys.stderr)
            if extra_in_index:
                print(f"  extra sample: {sorted(extra_in_index)[:5]}", file=sys.stderr)
            return 1
        print(f"[verify] CSV/index paths OK ({len(expected)} review files)")

    index_by_member = {row["archive_member_path"]: row for row in index_rows}
    restored_total = 0
    skipped_total = 0
    member_total = 0
    for shard in selected_archives(manifest, conf_years):
        archive_rel = shard.get("path_in_package", "")
        archive_path = package_dir / archive_rel
        if not archive_path.exists():
            print(f"[ERROR] archive missing: {archive_path}", file=sys.stderr)
            return 1
        restored, skipped, members = restore_archive(
            archive_path=archive_path,
            out_dir=out_dir,
            index_by_member=index_by_member,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
        restored_total += restored
        skipped_total += skipped
        member_total += members
        action = "would restore" if args.dry_run else "restored"
        print(
            f"[archive] {shard.get('conf_year')}: {action}={restored}, "
            f"skipped={skipped}, members={members}"
        )

    if not args.dry_run:
        checked, missing = verify_restored(index_rows, out_dir, conf_years)
        if missing:
            print(f"[ERROR] missing restored files: {missing}/{checked}", file=sys.stderr)
            return 1
        print(f"[verify] restored file hashes OK ({checked} files)")

    print(
        f"[done] package={package_dir}, out_dir={out_dir}, "
        f"archives={len(selected_archives(manifest, conf_years))}, "
        f"members={member_total}, restored={restored_total}, skipped={skipped_total}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
