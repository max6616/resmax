#!/usr/bin/env python3
"""Enrich accepted_index.csv with peer review data from OpenReview API v2.

Requires: openreview-py (pip install openreview-py)
Auth: set OPENREVIEW_USERNAME and OPENREVIEW_PASSWORD env vars, or pass --username/--password.

Capabilities:
- Backfill missing openreview_forum_id via title matching
- Fetch reviews, scores, confidence, meta-reviews, rebuttals
- Write per-paper JSON detail files to reviews/{conf_year}/{forum_id}.json
- Update CSV with structured score columns
- Mark venues with no public reviews as review_available=no
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    import openreview
    from openreview.api import OpenReviewClient
except ImportError:
    raise SystemExit(
        "[FATAL] openreview-py is required. Install with: pip install openreview-py"
    )

OPENREVIEW_BASEURL = "https://api2.openreview.net"

_client: OpenReviewClient | None = None


def _init_client(username: str, password: str) -> OpenReviewClient:
    global _client
    _client = OpenReviewClient(
        baseurl=OPENREVIEW_BASEURL,
        username=username,
        password=password,
    )
    print(f"[reviews] authenticated as {username}")
    return _client


REVIEW_FIELDS = [
    "review_available", "review_source", "review_num_reviewers",
    "review_score_scale", "review_scores", "review_score_mean",
    "review_confidence_scores", "review_confidence_mean",
    "review_detail_path",
]

VENUE_REVIEW_CONFIG: dict[str, dict] = {
    "ICLR": {
        "group": "ICLR.cc/{year}/Conference",
        "score_scale": "1-10",
        "platform": "openreview_v2",
    },
    "NeurIPS": {
        "group": "NeurIPS.cc/{year}/Conference",
        "score_scale": "1-10",
        "score_scale_overrides": {2025: "1-6"},
        "platform": "openreview_v2",
    },
    "ICML": {
        "group": "ICML.cc/{year}/Conference",
        "score_scale": "1-10",
        "platform": "openreview_v2",
    },
}

VENUES_NO_REVIEWS = {
    "CVPR", "ECCV", "ICCV", "AAAI", "KDD",
    "SIGGRAPH", "SIGGRAPH_Asia", "ACMMM",
}


def _normalize_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Backfill openreview_forum_id via title matching
# ---------------------------------------------------------------------------

def backfill_forum_ids(
    rows: list[dict], venue: str, year: int, group: str,
) -> tuple[int, int]:
    need = [r for r in rows if not r.get("openreview_forum_id", "").strip()]
    if not need:
        return 0, 0

    print(f"[reviews] backfilling forum_id for {len(need)} papers...")
    invitation = f"{group}/-/Submission"
    all_subs = _client.get_all_notes(invitation=invitation)
    if not all_subs:
        print(f"  [WARN] no submissions found for {invitation}")
        return 0, len(need)

    title_map: dict[str, str] = {}
    for note in all_subs:
        content = note.content or {}
        title_val = content.get("title", {})
        if isinstance(title_val, dict):
            title_val = title_val.get("value", "")
        if title_val:
            title_map[_normalize_title(str(title_val))] = note.id

    matched = 0
    for r in need:
        norm = _normalize_title(r.get("title", ""))
        if norm in title_map:
            r["openreview_forum_id"] = title_map[norm]
            matched += 1

    unmatched = len(need) - matched
    print(f"[reviews] backfill done: matched={matched}, unmatched={unmatched}")
    return matched, unmatched


# ---------------------------------------------------------------------------
# Fetch reviews from OpenReview
# ---------------------------------------------------------------------------

def _extract_rating(content: dict) -> float | None:
    for key in ("rating", "recommendation", "overall_assessment", "score",
                 "overall_recommendation", "soundness"):
        val = content.get(key, {})
        if isinstance(val, dict):
            val = val.get("value", "")
        if val is None:
            continue
        match = re.match(r"^(\d+(?:\.\d+)?)", str(val).strip())
        if match:
            return float(match.group(1))
    return None


def _extract_confidence(content: dict) -> float | None:
    val = content.get("confidence", {})
    if isinstance(val, dict):
        val = val.get("value", "")
    if val is None:
        return None
    match = re.match(r"^(\d+(?:\.\d+)?)", str(val).strip())
    return float(match.group(1)) if match else None


def fetch_paper_reviews(
    forum_id: str, group: str, scores_only: bool = False,
) -> dict | None:
    try:
        notes = _client.get_notes(forum=forum_id)
    except Exception as exc:
        print(f"  [ERR] {exc} for forum {forum_id}")
        return None

    if not notes:
        return None

    reviews = []
    meta_review = None
    rebuttals = []
    decision_note = None

    for note in notes:
        invs = ";".join(note.invitations or [])
        content = note.content or {}

        if "Official_Review" in invs:
            sigs = note.signatures or [""]
            sig_tail = sigs[0].split("/")[-1] if sigs else ""
            if sig_tail == "Authors":
                continue
            rating = _extract_rating(content)
            confidence = _extract_confidence(content)
            review_entry: dict = {
                "reviewer_id": sig_tail,
                "rating": rating,
                "confidence": confidence,
            }
            if not scores_only:
                for fn in ("summary", "strengths", "weaknesses",
                           "questions", "limitations", "ethics_review"):
                    fval = content.get(fn, {})
                    if isinstance(fval, dict):
                        fval = fval.get("value", "")
                    review_entry[fn] = str(fval) if fval else ""
            reviews.append(review_entry)

        elif "Meta_Review" in invs or "Decision" in invs:
            rec = content.get("recommendation",
                              content.get("decision", {}))
            if isinstance(rec, dict):
                rec = rec.get("value", "")
            mc = content.get("metareview",
                             content.get("content", {}))
            if isinstance(mc, dict):
                mc = mc.get("value", "")
            if "Meta_Review" in invs:
                meta_review = {
                    "recommendation": str(rec) if rec else "",
                    "content": str(mc) if mc and not scores_only else "",
                }
            if "Decision" in invs:
                decision_note = str(rec) if rec else ""

        elif "Rebuttal" in invs or "Official_Comment" in invs:
            sigs = note.signatures or [""]
            if sigs[0].endswith("/Authors"):
                rc = content.get("rebuttal", content.get("comment", {}))
                if isinstance(rc, dict):
                    rc = rc.get("value", "")
                if rc and not scores_only:
                    rebuttals.append({
                        "round": len(rebuttals) + 1,
                        "content": str(rc),
                    })

    if not reviews:
        return None

    return {
        "reviews": reviews,
        "meta_review": meta_review,
        "rebuttals": rebuttals,
        "decision_from_note": decision_note,
    }


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def load_csv(csv_path: str) -> tuple[list[str], list[dict]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def save_csv(csv_path: str, fieldnames: list[str], rows: list[dict]) -> None:
    for fn in REVIEW_FIELDS:
        if fn not in fieldnames:
            fieldnames.append(fn)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def save_review_json(
    reviews_dir: Path, conf_year: str, forum_id: str,
    paper_id: str, venue: str, year: int, score_scale: str,
    review_data: dict,
) -> str:
    out_dir = reviews_dir / conf_year
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", forum_id)
    out_path = out_dir / f"{safe_id}.json"
    doc = {
        "paper_id": paper_id,
        "forum_id": forum_id,
        "venue": venue,
        "year": year,
        "score_scale": score_scale,
        "reviews": review_data["reviews"],
        "meta_review": review_data.get("meta_review"),
        "rebuttals": review_data.get("rebuttals", []),
        "decision": review_data.get("decision_from_note", ""),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(out_path.relative_to(reviews_dir.parent.parent))


# ---------------------------------------------------------------------------
# Main enrichment logic
# ---------------------------------------------------------------------------

def enrich_conf_year(
    rows: list[dict], conf_year: str, reviews_dir: Path,
    batch_size: int, delay: float,
    skip_existing: bool, scores_only: bool, backfill_ids: bool,
) -> tuple[int, int, int]:
    target = [r for r in rows if r.get("conf_year", "") == conf_year]
    if not target:
        print(f"[reviews] no rows for {conf_year}")
        return 0, 0, 0

    parts = conf_year.rsplit("_", 1)
    venue = parts[0] if len(parts) == 2 else conf_year
    year = int(parts[1]) if len(parts) == 2 else 0

    config = VENUE_REVIEW_CONFIG.get(venue)
    if not config:
        print(f"[reviews] no review config for venue {venue}, skipping")
        return 0, len(target), 0

    group = config["group"].format(year=year)
    overrides = config.get("score_scale_overrides", {})
    score_scale = overrides.get(year, config["score_scale"])

    print(f"[reviews] loaded {len(target)} rows for {conf_year}")

    if backfill_ids:
        backfill_forum_ids(target, venue, year, group)

    have_id = [r for r in target if r.get("openreview_forum_id", "").strip()]
    print(f"[reviews] {len(have_id)} papers have openreview_forum_id")

    enriched = 0
    skipped = 0
    errors = 0

    for i in range(0, len(have_id), batch_size):
        batch = have_id[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(have_id) + batch_size - 1) // batch_size
        print(f"[reviews] fetching reviews: batch {batch_num}/{total_batches}...")

        for row in batch:
            forum_id = row["openreview_forum_id"].strip()
            if skip_existing:
                safe = re.sub(r"[^a-zA-Z0-9_-]", "_", forum_id)
                if (reviews_dir / conf_year / f"{safe}.json").exists():
                    skipped += 1
                    continue

            review_data = fetch_paper_reviews(forum_id, group, scores_only)
            if not review_data:
                errors += 1
                continue

            rel_path = save_review_json(
                reviews_dir, conf_year, forum_id,
                row.get("paper_id", ""), venue, year, score_scale,
                review_data,
            )
            ratings = [r["rating"] for r in review_data["reviews"] if r.get("rating") is not None]
            confs = [r["confidence"] for r in review_data["reviews"] if r.get("confidence") is not None]

            row["review_available"] = "yes"
            row["review_source"] = config["platform"]
            row["review_num_reviewers"] = str(len(review_data["reviews"]))
            row["review_score_scale"] = score_scale
            row["review_scores"] = ";".join(str(r) for r in ratings)
            row["review_score_mean"] = f"{sum(ratings)/len(ratings):.2f}" if ratings else ""
            row["review_confidence_scores"] = ";".join(str(c) for c in confs)
            row["review_confidence_mean"] = f"{sum(confs)/len(confs):.2f}" if confs else ""
            row["review_detail_path"] = rel_path
            time.sleep(delay)

    no_id = [r for r in target if not r.get("openreview_forum_id", "").strip()]
    for r in no_id:
        if not r.get("review_available"):
            r["review_available"] = "no"
            r["review_source"] = ""

    print(f"[reviews] done: enriched={enriched}, skipped={skipped}, errors={errors}")
    return enriched, skipped, errors


def mark_unavailable(rows: list[dict], conf_year_filter: str) -> int:
    count = 0
    for r in rows:
        if conf_year_filter and conf_year_filter not in r.get("conf_year", ""):
            continue
        venue = r.get("venue", "")
        if venue in VENUES_NO_REVIEWS or venue not in VENUE_REVIEW_CONFIG:
            r["review_available"] = "no"
            for fn in REVIEW_FIELDS:
                if fn != "review_available":
                    r.setdefault(fn, "")
            count += 1
    print(f"[reviews] marked {count} papers as review_available=no")
    return count


def repair_failed(
    rows: list[dict], conf_year: str, reviews_dir: Path,
    batch_size: int, delay: float, scores_only: bool,
) -> tuple[int, int, int]:
    """Re-process papers with empty review_available: backfill invalid forum_ids, then retry."""
    target = [r for r in rows if r.get("conf_year", "") == conf_year]
    failed = [r for r in target if not r.get("review_available", "").strip()]
    if not failed:
        print(f"[repair] no failed papers for {conf_year}")
        return 0, 0, 0

    parts = conf_year.rsplit("_", 1)
    venue = parts[0] if len(parts) == 2 else conf_year
    year = int(parts[1]) if len(parts) == 2 else 0
    config = VENUE_REVIEW_CONFIG.get(venue)
    if not config:
        return 0, 0, 0

    group = config["group"].format(year=year)
    overrides = config.get("score_scale_overrides", {})
    score_scale = overrides.get(year, config["score_scale"])

    print(f"[repair] {conf_year}: {len(failed)} papers to repair")

    # Step 1: clear invalid forum_ids so backfill can replace them
    for r in failed:
        r["openreview_forum_id"] = ""

    # Step 2: backfill via title matching
    backfill_forum_ids(failed, venue, year, group)

    have_id = [r for r in failed if r.get("openreview_forum_id", "").strip()]
    no_id = [r for r in failed if not r.get("openreview_forum_id", "").strip()]
    print(f"[repair] after backfill: {len(have_id)} with forum_id, {len(no_id)} without")

    # Step 3: fetch reviews for backfilled papers
    enriched = 0
    errors = 0
    for i in range(0, len(have_id), batch_size):
        batch = have_id[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(have_id) + batch_size - 1) // batch_size
        print(f"[repair] fetching: batch {batch_num}/{total_batches}...")
        for row in batch:
            forum_id = row["openreview_forum_id"].strip()
            review_data = fetch_paper_reviews(forum_id, group, scores_only)
            if not review_data:
                errors += 1
                continue
            rel_path = save_review_json(
                reviews_dir, conf_year, forum_id,
                row.get("paper_id", ""), venue, year, score_scale,
                review_data,
            )
            ratings = [rv["rating"] for rv in review_data["reviews"] if rv.get("rating") is not None]
            confs = [rv["confidence"] for rv in review_data["reviews"] if rv.get("confidence") is not None]
            row["review_available"] = "yes"
            row["review_source"] = config["platform"]
            row["review_num_reviewers"] = str(len(review_data["reviews"]))
            row["review_score_scale"] = score_scale
            row["review_scores"] = ";".join(str(x) for x in ratings)
            row["review_score_mean"] = f"{sum(ratings)/len(ratings):.2f}" if ratings else ""
            row["review_confidence_scores"] = ";".join(str(x) for x in confs)
            row["review_confidence_mean"] = f"{sum(confs)/len(confs):.2f}" if confs else ""
            row["review_detail_path"] = rel_path
            enriched += 1
        if i + batch_size < len(have_id):
            time.sleep(delay)

    # Step 4: mark remaining as no
    still_empty = [r for r in failed if not r.get("review_available", "").strip()]
    for r in still_empty:
        r["review_available"] = "no"

    print(f"[repair] done: enriched={enriched}, errors={errors}, marked_no={len(still_empty)}")
    return enriched, errors, len(still_empty)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Enrich accepted_index.csv with review data from OpenReview."
    )
    p.add_argument("--csv", required=True)
    p.add_argument("--reviews-dir", required=True)
    p.add_argument("--filter", default="")
    p.add_argument("--batch-size", type=int, default=50)
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--scores-only", action="store_true")
    p.add_argument("--backfill-ids", action="store_true")
    p.add_argument("--mark-unavailable", action="store_true")
    p.add_argument("--repair", action="store_true",
                   help="Re-process papers with empty review_available: backfill invalid forum_ids and retry")
    p.add_argument("--username", default=os.environ.get("OPENREVIEW_USERNAME", ""))
    p.add_argument("--password", default=os.environ.get("OPENREVIEW_PASSWORD", ""))
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    csv_path = args.csv
    reviews_dir = Path(args.reviews_dir).resolve()
    reviews_dir.mkdir(parents=True, exist_ok=True)

    fieldnames, rows = load_csv(csv_path)

    if args.mark_unavailable:
        mark_unavailable(rows, args.filter)
        save_csv(csv_path, fieldnames, rows)
        print(f"[reviews] updated CSV: {csv_path}")
        return 0

    if not args.username or not args.password:
        raise SystemExit(
            "[FATAL] OpenReview credentials required. "
            "Set OPENREVIEW_USERNAME/OPENREVIEW_PASSWORD or use --username/--password."
        )
    _init_client(args.username, args.password)

    if args.repair:
        conf_years = sorted({
            r["conf_year"] for r in rows
            if (not args.filter or args.filter in r.get("conf_year", ""))
            and not r.get("review_available", "").strip()
            and r.get("venue", "") in VENUE_REVIEW_CONFIG
        })
        if not conf_years:
            print("[repair] no conf_years with empty review_available")
            return 0
        for cy in conf_years:
            repair_failed(rows, cy, reviews_dir,
                          args.batch_size, args.delay, args.scores_only)
        save_csv(csv_path, fieldnames, rows)
        print(f"[repair] updated CSV: {csv_path}")
        return 0

    if args.filter:
        conf_years = sorted({
            r["conf_year"] for r in rows
            if args.filter in r.get("conf_year", "")
        })
    else:
        conf_years = sorted({
            r["conf_year"] for r in rows
            if r.get("venue", "") in VENUE_REVIEW_CONFIG
        })

    if not conf_years:
        print("[reviews] no matching conf_years with review config")
        return 0

    total_enriched = 0
    total_skipped = 0
    total_errors = 0

    for cy in conf_years:
        e, s, err = enrich_conf_year(
            rows, cy, reviews_dir,
            args.batch_size, args.delay,
            args.skip_existing, args.scores_only, args.backfill_ids,
        )
        total_enriched += e
        total_skipped += s
        total_errors += err

    save_csv(csv_path, fieldnames, rows)
    print(f"[reviews] updated CSV: {csv_path}")
    print(f"[reviews] total: enriched={total_enriched}, skipped={total_skipped}, errors={total_errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
