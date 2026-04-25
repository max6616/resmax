#!/usr/bin/env python3
"""Ensure review JSON cache is available for resmax skills.

Execution order:
1. If `paper_database/reviews/{conf_year}/{forum_id}.json` already covers all
   `review_available=yes` rows in accepted_index.csv, do nothing.
2. If a local Hugging Face review package exists, restore it.
3. Otherwise, download the review package from a configured private HF dataset
   repo and restore it.

If download or restore cannot complete, fail explicitly and stop the workflow.
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def load_csv(path: Path) -> list[dict]:
    csv.field_size_limit(100 * 1024 * 1024)
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


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


def expected_review_paths(csv_path: Path, conf_years: set[str] | None = None) -> set[str]:
    rows = load_csv(csv_path)
    expected = set()
    for row in rows:
        if row.get("review_available", "").strip() != "yes":
            continue
        rel = reviews_relative_path(row.get("review_detail_path", ""), row)
        if not rel:
            continue
        if conf_years is not None:
            parts = Path(rel).parts
            if not parts or parts[0] not in conf_years:
                continue
        expected.add(rel)
    return expected


def missing_reviews(expected: set[str], reviews_dir: Path) -> list[str]:
    return sorted(rel for rel in expected if not (reviews_dir / rel).exists())


def package_exists(package_dir: Path) -> bool:
    required = [
        package_dir / "reviews_manifest.json",
        package_dir / "reviews_index.csv",
        package_dir / "checksums.sha256",
        package_dir / "archives",
    ]
    return all(p.exists() for p in required)


def run_restore(
    *,
    package_dir: Path,
    reviews_dir: Path,
    csv_path: Path,
    conf_years: set[str] | None,
    allow_csv_hash_mismatch: bool,
) -> int:
    script = Path(__file__).resolve().parent / "restore_reviews_from_hf.py"
    cmd = [
        sys.executable,
        str(script),
        "--package-dir",
        str(package_dir),
        "--out-dir",
        str(reviews_dir),
        "--csv",
        str(csv_path),
    ]
    if conf_years:
        cmd.extend(["--conf-years", *sorted(conf_years)])
    if allow_csv_hash_mismatch:
        cmd.append("--allow-csv-hash-mismatch")
    return subprocess.run(cmd, check=False).returncode


def download_from_hf(
    *,
    repo_id: str,
    repo_type: str,
    path_in_repo: str,
    package_dir: Path,
) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required to download review packages. "
            "Install .agents/skills/resmax-database/scripts/requirements.txt "
            "or install huggingface_hub, then retry."
        ) from exc

    path_in_repo = path_in_repo.strip("/")
    if not path_in_repo:
        raise ValueError("--hf-reviews-path must not be empty")

    local_root = package_dir.parent
    local_root.mkdir(parents=True, exist_ok=True)
    print(f"[download] repo={repo_id}, repo_type={repo_type}, path={path_in_repo}", flush=True)
    snapshot_path = snapshot_download(
        repo_id=repo_id,
        repo_type=repo_type,
        allow_patterns=[
            f"{path_in_repo}/README.md",
            f"{path_in_repo}/checksums.sha256",
            f"{path_in_repo}/reviews_manifest.json",
            f"{path_in_repo}/reviews_index.csv",
            f"{path_in_repo}/reviews_index.parquet",
            f"{path_in_repo}/archives/*.tar.zst",
        ],
        local_dir=local_root,
    )
    source_dir = Path(snapshot_path) / path_in_repo
    if not source_dir.exists():
        source_dir = local_root / path_in_repo
    if not source_dir.exists():
        raise FileNotFoundError(
            f"download completed but review package path was not found: {path_in_repo}"
        )
    if source_dir.resolve() != package_dir.resolve():
        if package_dir.exists():
            shutil.rmtree(package_dir)
        shutil.copytree(source_dir, package_dir)
    print(f"[download] package available at {package_dir}", flush=True)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", default="paper_database/accepted_index.csv")
    p.add_argument("--reviews-dir", default="paper_database/reviews")
    p.add_argument("--package-dir", default="paper_database/hf_export/reviews")
    p.add_argument("--conf-years", nargs="*", default=None)
    p.add_argument("--hf-repo-id", default=os.environ.get("RESMAX_HF_DATASET_REPO", ""))
    p.add_argument("--hf-repo-type", default=os.environ.get("RESMAX_HF_REPO_TYPE", "dataset"))
    p.add_argument("--hf-reviews-path", default=os.environ.get("RESMAX_HF_REVIEWS_PATH", "reviews"))
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--allow-csv-hash-mismatch", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    csv_path = Path(args.csv)
    reviews_dir = Path(args.reviews_dir)
    package_dir = Path(args.package_dir)
    conf_years = set(args.conf_years) if args.conf_years else None

    if not csv_path.exists():
        print(f"[ERROR] accepted_index.csv not found: {csv_path}", file=sys.stderr)
        return 1

    expected = expected_review_paths(csv_path, conf_years)
    if not expected:
        print("[reviews] no review_available=yes rows in selected scope", flush=True)
        return 0

    missing = missing_reviews(expected, reviews_dir)
    if not missing:
        print(f"[reviews] raw review JSON already available ({len(expected)} files)", flush=True)
        return 0

    print(
        f"[reviews] raw review JSON incomplete: missing {len(missing)}/{len(expected)} "
        f"(sample={missing[:5]})",
        flush=True,
    )

    if package_exists(package_dir):
        print(f"[reviews] local review package found: {package_dir}; restoring", flush=True)
        rc = run_restore(
            package_dir=package_dir,
            reviews_dir=reviews_dir,
            csv_path=csv_path,
            conf_years=conf_years,
            allow_csv_hash_mismatch=args.allow_csv_hash_mismatch,
        )
        if rc != 0:
            print("[ERROR] local review package restore failed", file=sys.stderr)
            return rc
    else:
        if args.skip_download:
            print(
                f"[ERROR] review package not found at {package_dir} and --skip-download was set",
                file=sys.stderr,
            )
            return 1
        if not args.hf_repo_id:
            print(
                "[ERROR] review JSON is missing and no local review package exists. "
                "Set RESMAX_HF_DATASET_REPO or pass --hf-repo-id so the package can "
                "be downloaded automatically.",
                file=sys.stderr,
            )
            return 1
        try:
            download_from_hf(
                repo_id=args.hf_repo_id,
                repo_type=args.hf_repo_type,
                path_in_repo=args.hf_reviews_path,
                package_dir=package_dir,
            )
        except Exception as exc:
            print(f"[ERROR] failed to download review package from Hugging Face: {exc}", file=sys.stderr)
            return 1
        if not package_exists(package_dir):
            print(
                f"[ERROR] downloaded review package is incomplete: {package_dir}",
                file=sys.stderr,
            )
            return 1
        rc = run_restore(
            package_dir=package_dir,
            reviews_dir=reviews_dir,
            csv_path=csv_path,
            conf_years=conf_years,
            allow_csv_hash_mismatch=args.allow_csv_hash_mismatch,
        )
        if rc != 0:
            print("[ERROR] downloaded review package restore failed", file=sys.stderr)
            return rc

    remaining = missing_reviews(expected, reviews_dir)
    if remaining:
        print(
            f"[ERROR] review JSON still missing after restore/download: "
            f"{len(remaining)}/{len(expected)} (sample={remaining[:5]})",
            file=sys.stderr,
        )
        return 1
    print(f"[reviews] review JSON ready ({len(expected)} files)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
