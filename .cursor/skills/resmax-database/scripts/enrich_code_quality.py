#!/usr/bin/env python3
"""Lightweight GitHub repo probe for global enrichment.

Strategy — one API call per repo (/repos/{owner}/{repo}):
  - code_is_real: yes / 404 / empty / unknown
  - code_stars: star count
  - code_last_commit: pushed_at (last push date, used as activity proxy)
  - code_primary_language: GitHub's detected primary language

Intentionally excludes (moved to resmax-survey/meta_enrich deepcheck):
  - code_quality (full / partial / skeleton) — requires directory walk
  - code_framework — GitHub language tags too coarse; PWC framework field
    is populated separately by PWC dump

Concurrency: uses a ThreadPoolExecutor (default 8 workers) — GitHub's
authenticated rate limit is 5000 req/h, so 8 × 0.3 req/s ≈ 2.4 req/s is safe.

Checkpointing: repo-level JSON cache; resumable across runs.

Usage:
  python3 enrich_code_quality.py --csv paper_database/accepted_index.csv
  python3 enrich_code_quality.py --csv ... --filter ICLR_2026 --workers 8
  python3 enrich_code_quality.py --csv ... --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GITHUB_API = "https://api.github.com"
CHECKPOINT_INTERVAL = 100
DEFAULT_WORKERS = 2
MIN_REQUEST_INTERVAL_SEC = 0.3

PROBE_FIELDS = [
    "code_is_real",
    "code_stars",
    "code_last_commit",
    "code_primary_language",
]

_ckpt_lock = threading.Lock()
_rate_lock = threading.Lock()
_last_request_ts = [0.0]


def _throttle():
    """Ensure a global minimum interval between any two requests across workers."""
    with _rate_lock:
        now = time.time()
        delta = now - _last_request_ts[0]
        if delta < MIN_REQUEST_INTERVAL_SEC:
            time.sleep(MIN_REQUEST_INTERVAL_SEC - delta)
        _last_request_ts[0] = time.time()


def _gh_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "resmax-enrich/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _gh_get(path: str, retries: int = 2) -> Optional[dict]:
    """GET a single GitHub API endpoint with rate-limit handling.

    Returns None on 404. Retries on transient network errors. Raises on
    other HTTP errors so callers can classify.
    """
    url = f"{GITHUB_API}{path}" if path.startswith("/") else path
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        _throttle()
        req = Request(url, headers=_gh_headers())
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429):
                remaining = e.headers.get("X-RateLimit-Remaining", "")
                retry_after = e.headers.get("Retry-After", "")
                reset = e.headers.get("X-RateLimit-Reset", "")
                # Distinguish primary exhausted vs secondary/abuse
                if remaining == "0" and reset:
                    # Primary quota exhausted: sleep until reset (cap 1h)
                    wait = max(int(reset) - int(time.time()) + 5, 5)
                    wait = min(wait, 3600)
                    kind = "primary"
                elif retry_after:
                    try:
                        wait = int(retry_after)
                    except ValueError:
                        wait = 60
                    wait = min(wait, 180)
                    kind = "secondary"
                else:
                    wait = 60
                    kind = "unknown"
                sys.stderr.write(
                    f"  [rate-limit:{kind}] sleeping {wait}s (code={e.code}, remaining={remaining})\n"
                )
                sys.stderr.flush()
                time.sleep(wait)
                continue
            raise
        except (URLError, TimeoutError, ConnectionError) as e:
            last_exc = e
            time.sleep(2 ** attempt)
    if last_exc:
        raise last_exc
    return None


def _parse_owner_repo(code_url: str) -> Optional[tuple[str, str]]:
    m = re.match(
        r"https?://(?:www\.)?github\.com/([a-zA-Z0-9\-_.]+)/([a-zA-Z0-9\-_.]+)",
        code_url,
    )
    if not m:
        return None
    return m.group(1), m.group(2).rstrip(".git")


def _probe_repo(owner: str, repo: str) -> dict:
    """One API call, returns enrichment dict. Never raises on 404."""
    result = {
        "code_is_real": "unknown",
        "code_stars": "",
        "code_last_commit": "",
        "code_primary_language": "",
    }
    try:
        info = _gh_get(f"/repos/{owner}/{repo}")
    except Exception as exc:
        result["code_is_real"] = f"error:{type(exc).__name__}"
        return result

    if info is None:
        result["code_is_real"] = "404"
        return result

    size = info.get("size", 0) or 0
    stars = info.get("stargazers_count", 0) or 0
    pushed_at = info.get("pushed_at", "") or ""
    lang = info.get("language", "") or ""

    result["code_stars"] = str(stars)
    result["code_last_commit"] = pushed_at
    result["code_primary_language"] = lang

    if size == 0 and not pushed_at:
        result["code_is_real"] = "empty"
    else:
        result["code_is_real"] = "yes"
    return result


def _load_checkpoint(path: Path) -> dict[str, dict]:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_checkpoint(path: Path, data: dict[str, dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description="Lightweight GitHub repo probe")
    parser.add_argument("--csv", required=True, help="Path to accepted_index.csv")
    parser.add_argument("--filter", default="", help="conf_year substring filter")
    parser.add_argument(
        "--checkpoint",
        default="",
        help="Checkpoint JSON path (default: <csv>.code_quality_ckpt.json)",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS, help="Concurrent API workers"
    )
    parser.add_argument(
        "--refresh-stale-days",
        type=int,
        default=0,
        help="Re-probe repos whose cached record is older than N days (0 = never)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't write CSV")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[ERROR] CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("GITHUB_TOKEN"):
        print(
            "[WARN] GITHUB_TOKEN not set — rate limit will be 60 req/h",
            file=sys.stderr,
        )

    ckpt_path = (
        Path(args.checkpoint)
        if args.checkpoint
        else csv_path.with_suffix(".code_quality_ckpt.json")
    )
    checkpoint = _load_checkpoint(ckpt_path)
    print(
        f"[code_quality] loaded checkpoint: {len(checkpoint)} cached repos",
        flush=True,
    )

    csv.field_size_limit(10 * 1024 * 1024)
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    for nf in PROBE_FIELDS:
        if nf not in fieldnames:
            fieldnames.append(nf)

    conf_filter = args.filter.strip()
    targets = []
    for i, row in enumerate(rows):
        if conf_filter and conf_filter not in row.get("conf_year", ""):
            continue
        code_url = row.get("code_url", "").strip()
        if not code_url:
            continue
        if row.get("code_is_real", "").strip() and not args.refresh_stale_days:
            continue
        parsed = _parse_owner_repo(code_url)
        if not parsed:
            continue
        targets.append((i, parsed[0], parsed[1]))

    print(
        f"[code_quality] {len(targets)} repos to probe "
        f"(filter={conf_filter or 'all'}, workers={args.workers})",
        flush=True,
    )
    if not targets:
        print("[code_quality] nothing to do", flush=True)
        return 0

    # Split into cached vs needs-probe
    to_probe: list[tuple[int, str, str]] = []
    for row_idx, owner, repo in targets:
        cache_key = f"{owner}/{repo}".lower()
        if cache_key in checkpoint:
            cached = checkpoint[cache_key]
            for field in PROBE_FIELDS:
                rows[row_idx][field] = cached.get(field, "")
        else:
            to_probe.append((row_idx, owner, repo))

    cached_hits = len(targets) - len(to_probe)
    print(
        f"[code_quality] cache hits: {cached_hits}, need to probe: {len(to_probe)}",
        flush=True,
    )

    probed = 0
    errors = 0
    start = time.time()

    def _work(row_idx: int, owner: str, repo: str):
        result = _probe_repo(owner, repo)
        return row_idx, owner, repo, result

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_work, ri, o, r): (ri, o, r) for ri, o, r in to_probe
        }
        for fut in as_completed(futures):
            row_idx, owner, repo = futures[fut]
            try:
                _, _, _, result = fut.result()
            except Exception as exc:
                errors += 1
                result = {
                    "code_is_real": f"error:{type(exc).__name__}",
                    "code_stars": "",
                    "code_last_commit": "",
                    "code_primary_language": "",
                }
            cache_key = f"{owner}/{repo}".lower()
            with _ckpt_lock:
                checkpoint[cache_key] = result
            for field in PROBE_FIELDS:
                rows[row_idx][field] = result.get(field, "")
            probed += 1
            if probed % CHECKPOINT_INTERVAL == 0:
                with _ckpt_lock:
                    _save_checkpoint(ckpt_path, checkpoint)
                elapsed = time.time() - start
                rate = probed / max(elapsed, 0.1)
                eta = (len(to_probe) - probed) / max(rate, 0.01)
                print(
                    f"  [{probed}/{len(to_probe)}] "
                    f"rate={rate:.1f}/s, eta={eta/60:.1f}min",
                    flush=True,
                )

    with _ckpt_lock:
        _save_checkpoint(ckpt_path, checkpoint)

    elapsed = time.time() - start
    print(
        f"\n[code_quality] done: probed={probed}, cached={cached_hits}, "
        f"errors={errors}, elapsed={elapsed/60:.1f}min",
        flush=True,
    )

    # Stats
    stats: dict[str, int] = {}
    for row_idx, _, _ in targets:
        v = rows[row_idx].get("code_is_real", "unknown") or "unknown"
        stats[v] = stats.get(v, 0) + 1
    print(f"[code_quality] results: {stats}", flush=True)

    if args.dry_run:
        print("[code_quality] dry-run, not writing CSV", flush=True)
        return 0

    backup = csv_path.with_suffix(".csv.bak")
    shutil.copy2(csv_path, backup)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[code_quality] wrote CSV: {csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
