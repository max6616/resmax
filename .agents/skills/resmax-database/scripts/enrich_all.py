#!/usr/bin/env python3
"""Unified entry point for all global meta-enrichment stages.

This script sequences the standard enrichment pipeline after a successful
build_accepted_index.py run (whether full rebuild, per-conference add, or
incremental refresh). Every stage writes back to the same accepted_index.csv.

Pipeline order (each stage may be skipped independently):
  1. abstracts          — enrich_abstracts.py (S2 batch + arXiv batch)
  2. abstracts_fallback — enrich_abstracts_fallback.py (CVF/AAAI/ACM/OpenAlex/CrossRef/S2/arXiv/SerpAPI)
  3. acceptance_type    — enrich_acceptance_type.py (A-E venue mapping rules)
  4. reviews            — enrich_reviews.py (OpenReview fetch or rehydrate)
  5. code_urls          — enrich_code_urls.py (PWC + S2 + abstract regex)
  6. code_quality       — enrich_code_quality.py (lightweight /repos probe)
  7. openness           — enrich_openness.py (abstract-based weights/dataset scan)

  The third-round abstract fallback (orchestrator subagent web-search) is
  NOT handled here — it requires the main agent. See SKILL.md 子能力 2.

Design rules:
  - The --filter flag propagates to every stage as a conf_year substring
    filter, so per-conference runs only touch the new rows.
  - Each stage is a separate subprocess. A failure in one stage logs but
    does not abort the rest (unless --strict is set).
  - The CSV is the single source of truth. Each stage reads the latest
    version and writes back with a .bak backup.

Usage:
  # Global full run (called from "全量重建" flow)
  python3 enrich_all.py --csv paper_database/accepted_index.csv

  # Per-conference run (called from "新增会议" flow)
  python3 enrich_all.py --csv ... --filter ICLR_2026

  # Incremental refresh (everything but slow GitHub probing)
  python3 enrich_all.py --csv ... --skip-code-quality

  # Rebuild openness (refresh keyword lexicon)
  python3 enrich_all.py --csv ... --only openness --refresh
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Auto-load .secrets/*.env and .localconfig/*.env so every sub-stage sees
# the same environment (OPENREVIEW_USERNAME/PASSWORD, GITHUB_TOKEN, etc.).
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
import secrets_loader  # noqa: E402,F401


SCRIPT_DIR = Path(__file__).resolve().parent

STAGES = [
    # (name, script_name, skip_flag, requires_env, extra_args_fn, supports_dry_run)
    ("abstracts", "enrich_abstracts.py", "skip_abstracts", None, None, True),
    ("abstracts_fallback", "enrich_abstracts_fallback.py", "skip_abstracts_fallback", None, None, True),
    ("acceptance_type", "enrich_acceptance_type.py", "skip_acceptance_type", None, None, True),
    ("reviews", "enrich_reviews.py", "skip_reviews", None, "_reviews_args", False),
    ("code_urls", "enrich_code_urls.py", "skip_code_urls", None, None, True),
    ("code_quality", "enrich_code_quality.py", "skip_code_quality", "GITHUB_TOKEN", "_quality_args", True),
    ("openness", "enrich_openness.py", "skip_openness", None, "_openness_args", True),
]


def _reviews_args(args) -> list[str]:
    """Decide which review mode to run based on available credentials.

    Without OpenReview credentials we cannot fetch new reviews, but we still
    want review_* columns populated: rehydrate from cached JSON files and
    auto-mark no-public-review venues. This lets a fresh CSV rebuild recover
    the review columns with zero network cost.

    When credentials ARE provided, run the full fetch with --skip-existing so
    already-cached papers are not refetched.
    """
    reviews_dir = args.reviews_dir or str(Path(args.csv).parent / "reviews")
    quality_report = str(Path(args.csv).parent / "review_quality_report.json")
    has_creds = bool(os.environ.get("OPENREVIEW_USERNAME") and os.environ.get("OPENREVIEW_PASSWORD"))
    if has_creds:
        return [
            "--reviews-dir", reviews_dir,
            "--skip-existing",
            "--quality-report", quality_report,
        ]
    # Rehydrate mode: read cached JSONs, mark unsupported venues, no network.
    return ["--reviews-dir", reviews_dir, "--rehydrate", "--quality-report", quality_report]


def _quality_args(args) -> list[str]:
    extra = []
    if args.workers:
        extra += ["--workers", str(args.workers)]
    return extra


def _openness_args(args) -> list[str]:
    extra = []
    if args.refresh:
        extra += ["--refresh"]
    return extra


EXTRA_ARGS_FNS = {
    "_reviews_args": _reviews_args,
    "_quality_args": _quality_args,
    "_openness_args": _openness_args,
}


def _run_stage(
    name: str,
    script: str,
    args,
    extra_args: list[str] | None = None,
    supports_dry_run: bool = True,
) -> tuple[int, float]:
    script_path = SCRIPT_DIR / script
    if not script_path.exists():
        print(f"[enrich_all] SKIP {name}: script not found ({script_path})", flush=True)
        return 127, 0.0

    if args.dry_run and not supports_dry_run:
        print(
            f"\n[enrich_all] STAGE: {name} (SKIPPED in --dry-run: script has no --dry-run support)",
            flush=True,
        )
        return 0, 0.0

    cmd = [sys.executable, str(script_path), "--csv", args.csv]
    if args.filter:
        cmd += ["--filter", args.filter]
    if extra_args:
        cmd += extra_args
    if args.dry_run:
        cmd += ["--dry-run"]

    print(f"\n{'=' * 60}", flush=True)
    print(f"[enrich_all] STAGE: {name}", flush=True)
    print(f"[enrich_all] CMD: {' '.join(cmd)}", flush=True)
    print(f"{'=' * 60}", flush=True)

    start = time.time()
    try:
        rc = subprocess.call(cmd)
    except KeyboardInterrupt:
        print(f"[enrich_all] interrupted during {name}", flush=True)
        raise
    elapsed = time.time() - start
    print(
        f"\n[enrich_all] {name} finished: rc={rc}, elapsed={elapsed:.1f}s",
        flush=True,
    )
    return rc, elapsed


def main():
    parser = argparse.ArgumentParser(
        description="Unified meta-enrichment pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--csv", required=True, help="Path to accepted_index.csv")
    parser.add_argument(
        "--filter",
        default="",
        help="conf_year substring filter (applied to every stage)",
    )
    parser.add_argument(
        "--reviews-dir", default="", help="Directory for OpenReview review JSONs"
    )
    parser.add_argument(
        "--workers", type=int, default=8, help="Workers for GitHub probe stage"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-scan in openness stage (even if values exist)",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated stage names to run (e.g. 'code_urls,openness'). "
        "Overrides skip flags.",
    )
    parser.add_argument("--skip-abstracts", action="store_true")
    parser.add_argument("--skip-abstracts-fallback", action="store_true")
    parser.add_argument("--skip-acceptance-type", action="store_true")
    parser.add_argument("--skip-reviews", action="store_true")
    parser.add_argument("--skip-code-urls", action="store_true")
    parser.add_argument("--skip-code-quality", action="store_true")
    parser.add_argument("--skip-openness", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort on first stage non-zero exit (default: continue)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass --dry-run to every stage (no CSV writes)",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[enrich_all] ERROR: CSV not found: {csv_path}", file=sys.stderr)
        return 1

    only_set = {s.strip() for s in args.only.split(",") if s.strip()}

    summary: list[tuple[str, int, float]] = []
    total_start = time.time()

    for name, script, skip_flag, env_req, extra_fn_name, supports_dry_run in STAGES:
        if only_set:
            if name not in only_set:
                print(f"[enrich_all] SKIP {name}: not in --only", flush=True)
                continue
        else:
            if getattr(args, skip_flag):
                print(f"[enrich_all] SKIP {name}: --{skip_flag.replace('_', '-')}", flush=True)
                continue

        if env_req and not os.environ.get(env_req):
            print(
                f"[enrich_all] SKIP {name}: env var {env_req} not set",
                flush=True,
            )
            continue

        extra_args: list[str] | None = None
        if extra_fn_name:
            extra_args = EXTRA_ARGS_FNS[extra_fn_name](args)

        rc, elapsed = _run_stage(name, script, args, extra_args, supports_dry_run)
        summary.append((name, rc, elapsed))

        if rc != 0 and args.strict:
            print(
                f"[enrich_all] STRICT MODE: aborting on {name} failure",
                file=sys.stderr,
                flush=True,
            )
            break

    total = time.time() - total_start
    print(f"\n{'=' * 60}", flush=True)
    print(f"[enrich_all] SUMMARY (total {total:.1f}s, filter={args.filter or 'all'})", flush=True)
    print(f"{'=' * 60}", flush=True)
    for name, rc, elapsed in summary:
        tag = "OK" if rc == 0 else f"FAIL(rc={rc})"
        print(f"  {name:<15} {tag:<12} {elapsed:>8.1f}s", flush=True)

    failed = [s for s in summary if s[1] != 0]
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
