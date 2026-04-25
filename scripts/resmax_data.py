#!/usr/bin/env python3
"""Manage Resmax large data artifacts.

The runtime contract stays under paper_database/. The cache/ directory is an
implementation detail used for Hugging Face transfer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_REPO_ID = "max6616/resmax"
DEFAULT_REPO_TYPE = "dataset"
DEFAULT_MIRROR_DIR = "cache/huggingface/resmax"

ROOT_FILES = (
    "accepted_index.csv",
    "manifest.json",
    "qwen3_8b.npz",
)

DOWNLOAD_PATTERNS = (
    "accepted_index.csv",
    "manifest.json",
    "qwen3_8b.npz",
    "reviews/**",
)

ENV_LINE_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def repo_root(start: Path) -> Path:
    current = start.resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists() or (parent / ".agents").is_dir():
            return parent
    raise SystemExit(f"Could not locate resmax repository root from {start}")


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_localconfig_env(root: Path) -> None:
    for path in sorted((root / ".localconfig").glob("*.env")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = ENV_LINE_RE.match(line)
            if not match:
                continue
            key, value = match.groups()
            os.environ.setdefault(key, strip_quotes(value))


def apply_hf_defaults(args: argparse.Namespace) -> None:
    args.repo_id = args.repo_id or os.environ.get("RESMAX_HF_DATASET_REPO") or DEFAULT_REPO_ID
    args.repo_type = args.repo_type or os.environ.get("RESMAX_HF_REPO_TYPE") or DEFAULT_REPO_TYPE


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def same_file_content(a: Path, b: Path) -> bool:
    if not a.exists() or not b.exists():
        return False
    if a.stat().st_size != b.stat().st_size:
        return False
    return sha256_file(a) == sha256_file(b)


def reset_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def link_or_copy(src: Path, dst: Path, *, force: bool, mode: str) -> str:
    if not src.exists():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        if dst.is_file() and same_file_content(src, dst):
            return "existing"
        if not force:
            raise FileExistsError(
                f"{dst} already exists and differs from {src}; rerun with --force to replace it"
            )
        reset_path(dst)
    if mode == "copy":
        shutil.copy2(src, dst)
        return "copied"
    if mode == "symlink":
        os.symlink(src.resolve(), dst)
        return "symlinked"
    try:
        os.link(src, dst)
        return "hardlinked"
    except OSError:
        shutil.copy2(src, dst)
        return "copied"


def link_or_copy_tree(src_dir: Path, dst_dir: Path, *, force: bool, mode: str) -> dict[str, int]:
    if not src_dir.is_dir():
        raise FileNotFoundError(src_dir)
    src_files = sorted(path for path in src_dir.rglob("*") if path.is_file())
    if dst_dir.exists() or dst_dir.is_symlink():
        if dst_dir.is_symlink() or not dst_dir.is_dir() or force:
            reset_path(dst_dir)
        else:
            missing_or_changed = [
                src.relative_to(src_dir)
                for src in src_files
                if not same_file_content(src, dst_dir / src.relative_to(src_dir))
            ]
            dst_files = {
                path.relative_to(dst_dir)
                for path in dst_dir.rglob("*")
                if path.is_file()
            }
            src_rel_files = {src.relative_to(src_dir) for src in src_files}
            extra = sorted(dst_files - src_rel_files)
            if missing_or_changed or extra:
                raise FileExistsError(
                    f"{dst_dir} already exists and differs from {src_dir}; "
                    "rerun with --force to replace it"
                )
            return {
                "files": len(src_files),
                "hardlinked": 0,
                "copied": 0,
                "symlinked": 0,
                "existing": len(src_files),
            }
    counts = {"files": 0, "hardlinked": 0, "copied": 0, "symlinked": 0, "existing": 0}
    for src in src_files:
        rel = src.relative_to(src_dir)
        action = link_or_copy(src, dst_dir / rel, force=force, mode=mode)
        counts["files"] += 1
        counts[action] = counts.get(action, 0) + 1
    return counts


def run_command(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print("[run] " + " ".join(cmd), flush=True)
    completed = subprocess.run(cmd, cwd=cwd, env=env, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with exit code {completed.returncode}: {' '.join(cmd)}")


def download_snapshot(args: argparse.Namespace, root: Path, mirror_dir: Path) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError(
            "huggingface_hub is required for pull. Install requirements.txt, then retry."
        ) from exc

    token = os.environ.get("HF_TOKEN") or None
    mirror_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"[download] repo={args.repo_id}, repo_type={args.repo_type}, local_dir={mirror_dir}",
        flush=True,
    )
    snapshot_download(
        repo_id=args.repo_id,
        repo_type=args.repo_type,
        allow_patterns=list(DOWNLOAD_PATTERNS),
        local_dir=mirror_dir,
        token=token,
        force_download=args.force_download,
        max_workers=args.max_workers,
    )

    missing = [name for name in ROOT_FILES if not (mirror_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"download completed but required files are missing: {missing}")
    if not (mirror_dir / "reviews/reviews_manifest.json").exists():
        raise FileNotFoundError("download completed but reviews/reviews_manifest.json is missing")


def materialize_runtime(args: argparse.Namespace, root: Path, mirror_dir: Path) -> dict[str, object]:
    actions: dict[str, object] = {}
    paper_database = root / "paper_database"
    actions["paper_database/accepted_index.csv"] = link_or_copy(
        mirror_dir / "accepted_index.csv",
        paper_database / "accepted_index.csv",
        force=args.force,
        mode=args.mode,
    )
    actions["paper_database/manifest.json"] = link_or_copy(
        mirror_dir / "manifest.json",
        paper_database / "manifest.json",
        force=args.force,
        mode=args.mode,
    )
    actions["paper_database/embedding_cache/qwen3_8b.npz"] = link_or_copy(
        mirror_dir / "qwen3_8b.npz",
        paper_database / "embedding_cache/qwen3_8b.npz",
        force=args.force,
        mode=args.mode,
    )
    actions["paper_database/hf_export/reviews/"] = link_or_copy_tree(
        mirror_dir / "reviews",
        paper_database / "hf_export/reviews",
        force=args.force,
        mode=args.mode,
    )
    return actions


def ensure_reviews(root: Path, args: argparse.Namespace) -> None:
    if args.skip_reviews:
        print("[reviews] skipped by --skip-reviews", flush=True)
        return
    cmd = [
        sys.executable,
        ".agents/skills/resmax-database/scripts/ensure_reviews_available.py",
        "--csv",
        "paper_database/accepted_index.csv",
        "--reviews-dir",
        "paper_database/reviews",
        "--package-dir",
        "paper_database/hf_export/reviews",
        "--skip-download",
    ]
    run_command(cmd, cwd=root)


def validate_database(root: Path, args: argparse.Namespace) -> None:
    if args.no_validate:
        print("[validate] skipped by --no-validate", flush=True)
        return
    cmd = [
        sys.executable,
        ".agents/skills/resmax-database/scripts/validate_database.py",
        "--csv",
        "paper_database/accepted_index.csv",
        "--cache",
        "paper_database/embedding_cache/qwen3_8b.npz",
        "--manifest",
        "paper_database/manifest.json",
        "--out",
        "paper_database/validate_report.json",
    ]
    run_command(cmd, cwd=root)


def pull(args: argparse.Namespace) -> int:
    root = repo_root(Path(args.repo_root) if args.repo_root else Path.cwd())
    load_localconfig_env(root)
    apply_hf_defaults(args)
    mirror_dir = root / args.mirror_dir
    download_snapshot(args, root, mirror_dir)
    actions = materialize_runtime(args, root, mirror_dir)
    print(json.dumps({"materialized": actions}, ensure_ascii=False, indent=2), flush=True)
    ensure_reviews(root, args)
    validate_database(root, args)
    print("[done] resmax data artifacts are ready under paper_database/", flush=True)
    return 0


def package_reviews(root: Path, args: argparse.Namespace) -> None:
    if args.skip_package_reviews:
        print("[package] skipped by --skip-package-reviews", flush=True)
        return
    cmd = [
        sys.executable,
        ".agents/skills/resmax-database/scripts/package_reviews_for_hf.py",
        "--csv",
        "paper_database/accepted_index.csv",
        "--reviews-dir",
        "paper_database/reviews",
        "--out-dir",
        "paper_database/hf_export/reviews",
    ]
    run_command(cmd, cwd=root)


def prepare_mirror(root: Path, args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        ".agents/skills/resmax-database/scripts/prepare_hf_dataset.py",
        "--out-dir",
        args.mirror_dir,
        "--hf-repo-id",
        args.repo_id,
        "--mode",
        args.mode,
    ]
    run_command(cmd, cwd=root)


def upload_mirror(root: Path, args: argparse.Namespace) -> None:
    if args.prepare_only:
        print("[upload] skipped by --prepare-only", flush=True)
        return
    hf = shutil.which("hf")
    if not hf:
        raise RuntimeError("hf CLI is required for push. Install Hugging Face CLI, then retry.")
    env = os.environ.copy()
    if not args.no_xet_high_performance:
        env.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
    cmd = [
        hf,
        "upload",
        args.repo_id,
        args.mirror_dir,
        ".",
        "--repo-type",
        args.repo_type,
        "--commit-message",
        args.commit_message,
    ]
    run_command(cmd, cwd=root, env=env)


def push(args: argparse.Namespace) -> int:
    root = repo_root(Path(args.repo_root) if args.repo_root else Path.cwd())
    load_localconfig_env(root)
    apply_hf_defaults(args)
    package_reviews(root, args)
    prepare_mirror(root, args)
    upload_mirror(root, args)
    print("[done] resmax data push workflow completed", flush=True)
    return 0


def status(args: argparse.Namespace) -> int:
    root = repo_root(Path(args.repo_root) if args.repo_root else Path.cwd())
    paths = [
        root / "paper_database/accepted_index.csv",
        root / "paper_database/manifest.json",
        root / "paper_database/embedding_cache/qwen3_8b.npz",
        root / "paper_database/hf_export/reviews/reviews_manifest.json",
        root / "paper_database/reviews",
        root / "paper_database/validate_report.json",
    ]
    rows = []
    for path in paths:
        rel = str(path.relative_to(root))
        rows.append(
            {
                "path": rel,
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.is_file() else None,
            }
        )
    print(json.dumps({"repo_root": str(root), "artifacts": rows}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default="", help="Override repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    pull_p = sub.add_parser("pull", help="Download from Hugging Face and restore paper_database/")
    pull_p.add_argument("--repo-id", default="")
    pull_p.add_argument("--repo-type", default="")
    pull_p.add_argument("--mirror-dir", default=DEFAULT_MIRROR_DIR)
    pull_p.add_argument("--mode", choices=["hardlink", "copy", "symlink"], default="hardlink")
    pull_p.add_argument("--force", action="store_true", help="Replace existing runtime artifacts if they differ")
    pull_p.add_argument("--force-download", action="store_true", help="Force Hugging Face re-download")
    pull_p.add_argument("--max-workers", type=int, default=8)
    pull_p.add_argument("--skip-reviews", action="store_true", help="Do not restore raw review JSON from package")
    pull_p.add_argument("--no-validate", action="store_true", help="Skip validate_database.py after restore")
    pull_p.set_defaults(func=pull)

    push_p = sub.add_parser("push", help="Package, mirror, and upload paper_database/ artifacts")
    push_p.add_argument("--repo-id", default="")
    push_p.add_argument("--repo-type", default="")
    push_p.add_argument("--mirror-dir", default=DEFAULT_MIRROR_DIR)
    push_p.add_argument("--mode", choices=["hardlink", "copy", "symlink"], default="hardlink")
    push_p.add_argument("--commit-message", default="upload resmax dataset artifacts")
    push_p.add_argument("--skip-package-reviews", action="store_true")
    push_p.add_argument("--prepare-only", action="store_true", help="Prepare mirror but do not upload")
    push_p.add_argument("--no-xet-high-performance", action="store_true")
    push_p.set_defaults(func=push)

    status_p = sub.add_parser("status", help="Show local large artifact status")
    status_p.set_defaults(func=status)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
