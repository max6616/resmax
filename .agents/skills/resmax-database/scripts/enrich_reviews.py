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
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Any

# Auto-load .secrets/*.env and .localconfig/*.env into os.environ.
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
from secrets_loader import MissingSecretError, require_secret  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from review_quality import assess_review_doc, clean_reviews, review_has_payload, summarize_docs  # noqa: E402

OPENREVIEW_BASEURL = "https://api2.openreview.net"

_client: Any | None = None


def _init_client(username: str, password: str) -> Any:
    try:
        from openreview.api import OpenReviewClient
    except ImportError as exc:
        raise RuntimeError(
            "openreview-py is required only for fetch/repair/backfill modes. "
            "Install with: pip install openreview-py"
        ) from exc
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

TEXT_FIELD_ALIASES = {
    "summary": (
        "summary", "review_summary", "paper_summary", "brief_summary",
        "summary_of_the_paper", "main_review",
    ),
    "strengths": (
        "strengths", "strength", "strong_points", "claims_and_evidence",
        "relation_to_prior_works", "other_aspects", "positive_aspects",
    ),
    "weaknesses": (
        "weaknesses", "weakness", "weak_points", "negative_aspects",
        "concerns", "issues", "requested_changes",
    ),
    "questions": (
        "questions", "questions_for_authors", "questions_for_the_authors",
        "clarifying_questions",
    ),
    "limitations": ("limitations", "limitation"),
    "ethics_review": (
        "ethics_review", "ethical_concerns", "ethical_issues", "ethics",
        "broader_impact", "societal_impact",
    ),
}

RATING_KEYS = (
    "rating", "recommendation", "overall_assessment", "score",
    "overall_recommendation", "soundness",
)
CONFIDENCE_KEYS = ("confidence", "reviewer_confidence")
NON_TEXT_KEYS = {
    "title", "authors", "authorids", "venue", "venueid", "pdf", "html",
    "supplementary_material", "rating", "recommendation",
    "overall_assessment", "score", "overall_recommendation", "soundness",
    "confidence", "reviewer_confidence", "decision", "metareview",
    "meta_review",
}

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
        # ICML 2024 did not expose Official_Review notes via OpenReview v2
        # (Submission / Post_Submission only). Treat as no-public-review.
        # Confirmed 2026-04 via direct API probe.
        "no_public_years": {2024},
    },
}

VENUES_NO_REVIEWS = {
    "CVPR", "ECCV", "ICCV", "AAAI", "KDD",
    "SIGGRAPH", "SIGGRAPH_Asia", "ACMMM",
    "TPAMI", "IJCV", "JMLR", "AIJ", "TNNLS",
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

def _note_attr(note: Any, attr: str, default: Any = None) -> Any:
    if isinstance(note, dict):
        return note.get(attr, default)
    return getattr(note, attr, default)


def _content_value(content: dict, key: str) -> Any:
    val = content.get(key)
    if isinstance(val, dict) and "value" in val:
        return val.get("value")
    return val


def _text_value(content: dict, key: str) -> str:
    val = _content_value(content, key)
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        return "; ".join(str(v) for v in val if v is not None).strip()
    if isinstance(val, dict):
        return json.dumps(val, ensure_ascii=False, sort_keys=True)
    return str(val).strip()


def _first_text(content: dict, keys: Iterable[str]) -> str:
    for key in keys:
        val = _text_value(content, key)
        if val:
            return val
    return ""


def _extract_float(content: dict, keys: Iterable[str]) -> float | None:
    for key in keys:
        val = _text_value(content, key)
        if not val:
            continue
        match = re.match(r"^\s*(\d+(?:\.\d+)?)", val)
        if match:
            return float(match.group(1))
    return None


def _extract_rating(content: dict) -> float | None:
    return _extract_float(content, RATING_KEYS)


def _extract_confidence(content: dict) -> float | None:
    return _extract_float(content, CONFIDENCE_KEYS)


def _is_author_signature(signature: str) -> bool:
    return signature == "Authors" or signature.endswith("/Authors")


def _public_text_fields(content: dict) -> dict[str, str]:
    out = {}
    for key in sorted(content):
        if key in NON_TEXT_KEYS:
            continue
        val = _text_value(content, key)
        if val:
            out[key] = val
    return out


def _combine_text_fields(fields: dict[str, str]) -> str:
    chunks = []
    for key, val in fields.items():
        if val:
            label = key.replace("_", " ").strip().title()
            chunks.append(f"{label}: {val}")
    return "\n\n".join(chunks)


def _reviewer_id(signatures: list[str]) -> str:
    sig = signatures[0] if signatures else ""
    return sig.split("/")[-1] if sig else ""


def _extract_review_entry(note: Any, scores_only: bool = False) -> dict | None:
    content = _note_attr(note, "content", {}) or {}
    sigs = _note_attr(note, "signatures", []) or []
    sig0 = sigs[0] if sigs else ""
    if _is_author_signature(sig0):
        return None

    entry: dict[str, Any] = {
        "reviewer_id": _reviewer_id(sigs),
        "rating": _extract_rating(content),
        "confidence": _extract_confidence(content),
    }
    if not scores_only:
        for out_key, aliases in TEXT_FIELD_ALIASES.items():
            entry[out_key] = _first_text(content, aliases)
        content_fields = _public_text_fields(content)
        entry["content_fields"] = content_fields
        entry["review_text"] = _combine_text_fields(content_fields)
    return entry if review_has_payload(entry) else None


def _extract_meta_review(content: dict, scores_only: bool = False) -> dict | None:
    recommendation = _first_text(
        content, ("recommendation", "decision", "rating", "overall_recommendation")
    )
    content_fields = _public_text_fields(content)
    content_text = "" if scores_only else _combine_text_fields(content_fields)
    if not recommendation and not content_text:
        return None
    return {
        "recommendation": recommendation,
        "content": content_text,
        "content_fields": content_fields,
    }


def _extract_author_comment(content: dict) -> str:
    val = _first_text(content, ("rebuttal", "comment", "response", "reply", "author_response"))
    return val or _combine_text_fields(_public_text_fields(content))


def _fetch_public_notes(forum_id: str, page_size: int = 1000) -> list[dict]:
    notes: list[dict] = []
    offset = 0
    while True:
        params = urllib.parse.urlencode({
            "forum": forum_id,
            "limit": page_size,
            "offset": offset,
        })
        url = f"{OPENREVIEW_BASEURL}/notes?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "resmax-review-enrichment/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        batch = data.get("notes", []) or []
        notes.extend(batch)
        count = int(data.get("count") or len(notes))
        offset += len(batch)
        if not batch or offset >= count:
            break
    return notes


def fetch_paper_reviews(
    forum_id: str, group: str, scores_only: bool = False,
) -> dict | None:
    try:
        notes = _client.get_notes(forum=forum_id) if _client else _fetch_public_notes(forum_id)
    except Exception as exc:
        print(f"  [ERR] {exc} for forum {forum_id}")
        return None

    if not notes:
        return None

    reviews = []
    meta_review = None
    meta_reviews = []
    rebuttals = []
    decision_note = None

    for note in notes:
        invs = ";".join(_note_attr(note, "invitations", []) or [])
        content = _note_attr(note, "content", {}) or {}

        if "Official_Review" in invs:
            review_entry = _extract_review_entry(note, scores_only=scores_only)
            if review_entry:
                reviews.append(review_entry)

        elif "Meta_Review" in invs or "Decision" in invs:
            if "Meta_Review" in invs:
                meta_review = _extract_meta_review(content, scores_only=scores_only)
                if meta_review:
                    meta_reviews.append(meta_review)
            if "Decision" in invs:
                decision_note = _first_text(
                    content, ("decision", "recommendation", "comment", "content")
                )

        elif "Rebuttal" in invs or "Official_Comment" in invs or "Author_Response" in invs:
            sigs = _note_attr(note, "signatures", []) or [""]
            if _is_author_signature(sigs[0]):
                rc = _extract_author_comment(content)
                if rc and not scores_only:
                    rebuttals.append({
                        "round": len(rebuttals) + 1,
                        "content": rc,
                    })

    if not reviews:
        return None

    return {
        "reviews": clean_reviews(reviews),
        "meta_review": meta_review,
        "meta_reviews": meta_reviews,
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
        "schema_version": 2,
        "paper_id": paper_id,
        "forum_id": forum_id,
        "venue": venue,
        "year": year,
        "score_scale": score_scale,
        "reviews": review_data["reviews"],
        "meta_review": review_data.get("meta_review"),
        "meta_reviews": review_data.get("meta_reviews", []),
        "rebuttals": review_data.get("rebuttals", []),
        "decision": review_data.get("decision_from_note", ""),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "openreview_api2_public_notes",
    }
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    # Return a workspace-relative path when possible (CWD assumed to be repo
    # root, per skill contract). Falls back to absolute path in edge cases.
    try:
        return str(out_path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(out_path.resolve())


# ---------------------------------------------------------------------------
# Main enrichment logic
# ---------------------------------------------------------------------------

def _write_row_from_review_data(
    row: dict, review_data: dict, rel_path: str,
    config: dict, score_scale: str,
) -> None:
    """Populate CSV review_* columns on a row from in-memory review data."""
    reviews = review_data.get("reviews", []) or []
    ratings = [r["rating"] for r in reviews if r.get("rating") is not None]
    confs = [r["confidence"] for r in reviews if r.get("confidence") is not None]
    row["review_available"] = "yes"
    row["review_source"] = config["platform"]
    row["review_num_reviewers"] = str(len(reviews))
    row["review_score_scale"] = score_scale
    row["review_scores"] = ";".join(str(r) for r in ratings)
    row["review_score_mean"] = f"{sum(ratings)/len(ratings):.2f}" if ratings else ""
    row["review_confidence_scores"] = ";".join(str(c) for c in confs)
    row["review_confidence_mean"] = f"{sum(confs)/len(confs):.2f}" if confs else ""
    row["review_detail_path"] = rel_path


def _review_doc_needs_refresh(doc: dict, venue: str) -> bool:
    stats = assess_review_doc(doc)
    if stats.get("author_entries", 0):
        return True
    if stats.get("blank_non_author_entries", 0):
        return True
    if venue == "ICML" and int(doc.get("schema_version") or 0) < 2:
        return True
    if stats.get("non_author_entries", 0) and not stats.get("text_chars", 0) and not stats.get("rating_entries", 0):
        return True
    return False


def _load_review_json_as_row_input(json_path: Path) -> tuple[dict, str] | None:
    """Load a cached review JSON and return (review_data_dict, score_scale)."""
    try:
        doc = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  [WARN] cannot parse {json_path}: {exc}")
        return None
    review_data = {
        "reviews": clean_reviews(doc.get("reviews", []) or []),
        "meta_review": doc.get("meta_review"),
        "meta_reviews": doc.get("meta_reviews", []) or [],
        "rebuttals": doc.get("rebuttals", []) or [],
        "decision_from_note": doc.get("decision", ""),
    }
    return review_data, doc.get("score_scale", "")


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
        # Venue has no public reviews (CVPR/ECCV/ICCV/AAAI/KDD/SIGGRAPH/journals/…).
        # Mark every target row as review_available=no so downstream queries
        # have an explicit "known-unavailable" signal. The mark is idempotent.
        print(
            f"[reviews] {conf_year}: venue {venue!r} has no public reviews, "
            f"marking {len(target)} rows as review_available=no"
        )
        for row in target:
            row["review_available"] = "no"
            for fn in REVIEW_FIELDS:
                if fn != "review_available":
                    row.setdefault(fn, "")
        return 0, len(target), 0

    no_public_years = config.get("no_public_years") or set()
    if year in no_public_years:
        print(
            f"[reviews] {conf_year}: venue declares no public reviews for this year, "
            f"marking {len(target)} rows as review_available=no"
        )
        for row in target:
            row["review_available"] = "no"
            for fn in REVIEW_FIELDS:
                if fn != "review_available":
                    row.setdefault(fn, "")
        return 0, len(target), 0

    group = config["group"].format(year=year)
    overrides = config.get("score_scale_overrides", {})
    score_scale_default = overrides.get(year, config["score_scale"])

    print(f"[reviews] loaded {len(target)} rows for {conf_year}")

    if backfill_ids:
        backfill_forum_ids(target, venue, year, group)

    have_id = [r for r in target if r.get("openreview_forum_id", "").strip()]
    print(f"[reviews] {len(have_id)} papers have openreview_forum_id")

    enriched = 0      # papers newly fetched from API
    rehydrated = 0    # papers whose CSV columns were repopulated from cached JSON
    skipped = 0       # papers already complete (skip_existing AND row already has review_available=yes)
    errors = 0

    for i in range(0, len(have_id), batch_size):
        batch = have_id[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(have_id) + batch_size - 1) // batch_size
        print(f"[reviews] processing batch {batch_num}/{total_batches}...")

        for row in batch:
            forum_id = row["openreview_forum_id"].strip()
            safe = re.sub(r"[^a-zA-Z0-9_-]", "_", forum_id)
            json_path = reviews_dir / conf_year / f"{safe}.json"

            # If JSON exists, always rehydrate the CSV row from it. This makes
            # the stage idempotent: a CSV rebuild that dropped review_* columns
            # is fixed on the next run without any network traffic.
            if json_path.exists():
                try:
                    cached_doc = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception as exc:
                    print(f"  [WARN] cannot parse {json_path}: {exc}")
                    cached_doc = {}
                if cached_doc and not _review_doc_needs_refresh(cached_doc, venue):
                    if skip_existing and row.get("review_available") == "yes":
                        skipped += 1
                        continue
                else:
                    print(f"  [reviews] refresh stale/incomplete cache: {json_path}")
                    review_data = fetch_paper_reviews(forum_id, group, scores_only)
                    if not review_data:
                        errors += 1
                        continue
                    rel_path = save_review_json(
                        reviews_dir, conf_year, forum_id,
                        row.get("paper_id", ""), venue, year, score_scale_default,
                        review_data,
                    )
                    _write_row_from_review_data(row, review_data, rel_path, config, score_scale_default)
                    enriched += 1
                    time.sleep(delay)
                    continue
                loaded = _load_review_json_as_row_input(json_path)
                if loaded is None:
                    errors += 1
                    continue
                review_data, json_scale = loaded
                try:
                    rel_path = str(json_path.resolve().relative_to(Path.cwd()))
                except ValueError:
                    rel_path = str(json_path.resolve())
                _write_row_from_review_data(
                    row, review_data, rel_path, config,
                    json_scale or score_scale_default,
                )
                rehydrated += 1
                continue

            # No cached JSON — fetch from API.
            review_data = fetch_paper_reviews(forum_id, group, scores_only)
            if not review_data:
                errors += 1
                continue

            rel_path = save_review_json(
                reviews_dir, conf_year, forum_id,
                row.get("paper_id", ""), venue, year, score_scale_default,
                review_data,
            )
            _write_row_from_review_data(row, review_data, rel_path, config, score_scale_default)
            enriched += 1
            time.sleep(delay)

    no_id = [r for r in target if not r.get("openreview_forum_id", "").strip()]
    for r in no_id:
        if not r.get("review_available"):
            r["review_available"] = "no"
            r["review_source"] = ""

    print(
        f"[reviews] done: fetched={enriched}, rehydrated_from_json={rehydrated}, "
        f"skipped={skipped}, errors={errors}"
    )
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


def write_quality_report(
    rows: list[dict],
    reviews_dir: Path,
    conf_years: list[str],
    report_path: Path,
    min_files_with_text_pct: float,
    max_blank_non_author_entry_pct: float,
) -> tuple[dict, list[str]]:
    docs_by_cy: dict[str, list[dict]] = {}
    missing: list[str] = []
    parse_errors: list[str] = []

    for row in rows:
        cy = row.get("conf_year", "")
        if cy not in conf_years:
            continue
        if row.get("review_available") != "yes":
            continue
        forum_id = row.get("openreview_forum_id", "").strip()
        if not forum_id:
            continue
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", forum_id)
        json_path = reviews_dir / cy / f"{safe}.json"
        if not json_path.exists():
            missing.append(f"{row.get('paper_id', '?')} -> {json_path}")
            continue
        try:
            docs_by_cy.setdefault(cy, []).append(json.loads(json_path.read_text(encoding="utf-8")))
        except Exception as exc:
            parse_errors.append(f"{row.get('paper_id', '?')}: {type(exc).__name__}: {exc}")

    by_conf_year = summarize_docs(docs_by_cy)
    violations = []
    for cy, stats in by_conf_year.items():
        if stats["files_with_text_pct"] < min_files_with_text_pct:
            violations.append(
                f"{cy}: files_with_text_pct {stats['files_with_text_pct']} < {min_files_with_text_pct}"
            )
        if stats["author_entries"]:
            violations.append(
                f"{cy}: author_entries {stats['author_entries']} should be filtered from reviews"
            )
        if stats["blank_non_author_entry_pct"] > max_blank_non_author_entry_pct:
            violations.append(
                f"{cy}: blank_non_author_entry_pct {stats['blank_non_author_entry_pct']} > "
                f"{max_blank_non_author_entry_pct}"
            )
    if missing:
        violations.append(f"missing review JSON files: {len(missing)}")
    if parse_errors:
        violations.append(f"review JSON parse errors: {len(parse_errors)}")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "conf_years": conf_years,
        "by_conf_year": by_conf_year,
        "missing_json_count": len(missing),
        "missing_json_sample": missing[:20],
        "parse_error_count": len(parse_errors),
        "parse_error_sample": parse_errors[:20],
        "quality_violations": violations,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[quality] wrote {report_path}")
    for cy, stats in by_conf_year.items():
        print(
            f"[quality] {cy}: files={stats['files']} text_pct={stats['files_with_text_pct']} "
            f"blank_non_author_pct={stats['blank_non_author_entry_pct']} "
            f"ratings_pct={stats['files_with_ratings_pct']}"
        )
    if violations:
        print("[quality] violations:")
        for item in violations:
            print(f"  - {item}")
    return report, violations


def rehydrate_from_json(
    rows: list[dict], reviews_dir: Path, conf_year_filter: str
) -> tuple[int, int]:
    """Repopulate review_* columns on the CSV by reading cached JSON files.

    Use case: the CSV was rebuilt (e.g. full rebuild) and lost the review_*
    columns, but the reviews/ directory still holds the per-paper JSON detail
    files. This mode performs no network I/O and rewrites the review_* columns
    from the files on disk.

    Returns (rehydrated_count, marked_no_count).
    """
    if not reviews_dir.exists():
        print(f"[rehydrate] reviews_dir not found: {reviews_dir}")
        return 0, 0

    target_rows = [
        r for r in rows
        if not conf_year_filter or conf_year_filter in r.get("conf_year", "")
    ]
    print(f"[rehydrate] scanning {len(target_rows)} rows under filter='{conf_year_filter or 'all'}'")

    rehydrated = 0
    marked_no = 0
    not_found = 0

    for row in target_rows:
        venue = row.get("venue", "")
        conf_year = row.get("conf_year", "")
        forum_id = row.get("openreview_forum_id", "").strip()

        # Venues with no public reviews always get marked_no regardless of JSON presence.
        if venue in VENUES_NO_REVIEWS or venue not in VENUE_REVIEW_CONFIG:
            row["review_available"] = "no"
            for fn in REVIEW_FIELDS:
                if fn != "review_available":
                    row.setdefault(fn, "")
            marked_no += 1
            continue

        # Year-specific no-public-review override (e.g. ICML 2024).
        try:
            _y = int(conf_year.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            _y = 0
        if _y in (VENUE_REVIEW_CONFIG[venue].get("no_public_years") or set()):
            row["review_available"] = "no"
            for fn in REVIEW_FIELDS:
                if fn != "review_available":
                    row.setdefault(fn, "")
            marked_no += 1
            continue

        if not forum_id:
            row["review_available"] = "no"
            for fn in REVIEW_FIELDS:
                if fn != "review_available":
                    row.setdefault(fn, "")
            marked_no += 1
            continue

        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", forum_id)
        json_path = reviews_dir / conf_year / f"{safe}.json"
        if not json_path.exists():
            # Keep previous values (if any), but flag the row so caller can
            # see how many are still missing.
            not_found += 1
            continue

        try:
            doc = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  [WARN] cannot parse {json_path}: {exc}")
            continue

        original_reviews = doc.get("reviews", []) or []
        reviews = clean_reviews(original_reviews)
        if len(reviews) != len(original_reviews):
            doc["reviews"] = reviews
            doc["cleaned_at"] = datetime.now(timezone.utc).isoformat()
            doc["cleaning"] = "removed author and blank review shell entries; no text was synthesized"
            json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        ratings = [
            r.get("rating") for r in reviews
            if isinstance(r.get("rating"), (int, float))
        ]
        confs = [
            r.get("confidence") for r in reviews
            if isinstance(r.get("confidence"), (int, float))
        ]
        try:
            rel_path = str(json_path.resolve().relative_to(Path.cwd()))
        except ValueError:
            rel_path = str(json_path.resolve())

        config = VENUE_REVIEW_CONFIG[venue]
        parts = conf_year.rsplit("_", 1)
        year = int(parts[1]) if len(parts) == 2 else 0
        overrides = config.get("score_scale_overrides", {})
        score_scale = doc.get("score_scale") or overrides.get(year, config["score_scale"])

        row["review_available"] = "yes"
        row["review_source"] = config["platform"]
        row["review_num_reviewers"] = str(len(reviews))
        row["review_score_scale"] = score_scale
        row["review_scores"] = ";".join(str(r) for r in ratings)
        row["review_score_mean"] = f"{sum(ratings)/len(ratings):.2f}" if ratings else ""
        row["review_confidence_scores"] = ";".join(str(c) for c in confs)
        row["review_confidence_mean"] = f"{sum(confs)/len(confs):.2f}" if confs else ""
        row["review_detail_path"] = rel_path
        rehydrated += 1

    print(
        f"[rehydrate] rehydrated={rehydrated}, marked_no={marked_no}, "
        f"json_missing={not_found}"
    )
    return rehydrated, marked_no


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
    p.add_argument("--rehydrate", action="store_true",
                   help="Repopulate CSV review_* columns from existing JSON files "
                        "(no network). Use after a CSV rebuild that dropped the columns.")
    p.add_argument("--repair", action="store_true",
                   help="Re-process papers with empty review_available: backfill invalid forum_ids and retry")
    p.add_argument("--quality-report", default="",
                   help="Write review content quality audit JSON after enrichment/rehydrate")
    p.add_argument("--allow-quality-warnings", action="store_true",
                   help="Do not fail when the review quality audit finds content issues")
    p.add_argument("--min-files-with-text-pct", type=float, default=95.0)
    p.add_argument("--max-blank-non-author-entry-pct", type=float, default=1.0)
    # CLI overrides; values from .secrets/openreview.env are picked up by
    # the loader at runtime (see main()).
    p.add_argument("--username", default="")
    p.add_argument("--password", default="")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    csv_path = args.csv
    reviews_dir = Path(args.reviews_dir).resolve()
    reviews_dir.mkdir(parents=True, exist_ok=True)

    fieldnames, rows = load_csv(csv_path)

    if args.rehydrate:
        rehydrate_from_json(rows, reviews_dir, args.filter)
        save_csv(csv_path, fieldnames, rows)
        if args.quality_report:
            conf_years = sorted({
                r["conf_year"] for r in rows
                if (not args.filter or args.filter in r.get("conf_year", ""))
                and r.get("venue", "") in VENUE_REVIEW_CONFIG
            })
            _, violations = write_quality_report(
                rows, reviews_dir, conf_years, Path(args.quality_report),
                args.min_files_with_text_pct, args.max_blank_non_author_entry_pct,
            )
            if violations and not args.allow_quality_warnings:
                print("[quality] FAIL", file=sys.stderr)
                return 1
        print(f"[reviews] updated CSV: {csv_path}")
        return 0

    if args.mark_unavailable:
        mark_unavailable(rows, args.filter)
        save_csv(csv_path, fieldnames, rows)
        print(f"[reviews] updated CSV: {csv_path}")
        return 0

    # Fetching known forum_ids can use OpenReview's public notes API. Backfill
    # and repair still need the OpenReview client because they search
    # submissions by invitation/group.
    if args.username:
        os.environ["OPENREVIEW_USERNAME"] = args.username
    if args.password:
        os.environ["OPENREVIEW_PASSWORD"] = args.password
    username = os.environ.get("OPENREVIEW_USERNAME", "")
    password = os.environ.get("OPENREVIEW_PASSWORD", "")
    if username and password:
        try:
            _init_client(username, password)
        except RuntimeError as exc:
            print(f"[FATAL] {exc}", file=sys.stderr)
            return 2
    elif args.backfill_ids or args.repair:
        try:
            username = require_secret(
                "OPENREVIEW_USERNAME",
                env_file=".secrets/openreview.env",
                purpose="Authenticate to OpenReview API v2 to backfill review forum ids",
                extra_vars=["OPENREVIEW_PASSWORD"],
            )
            password = os.environ["OPENREVIEW_PASSWORD"]
        except MissingSecretError as err:
            print(str(err), file=sys.stderr, flush=True)
            return 2
        try:
            _init_client(username, password)
        except RuntimeError as exc:
            print(f"[FATAL] {exc}", file=sys.stderr)
            return 2
    else:
        print("[reviews] OPENREVIEW credentials not set; using public notes API")

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
        if args.quality_report:
            _, violations = write_quality_report(
                rows, reviews_dir, conf_years, Path(args.quality_report),
                args.min_files_with_text_pct, args.max_blank_non_author_entry_pct,
            )
            if violations and not args.allow_quality_warnings:
                print("[quality] FAIL", file=sys.stderr)
                return 1
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
    if args.quality_report:
        _, violations = write_quality_report(
            rows, reviews_dir, conf_years, Path(args.quality_report),
            args.min_files_with_text_pct, args.max_blank_non_author_entry_pct,
        )
        if violations and not args.allow_quality_warnings:
            print("[quality] FAIL", file=sys.stderr)
            return 1
    print(f"[reviews] updated CSV: {csv_path}")
    print(f"[reviews] total: enriched={total_enriched}, skipped={total_skipped}, errors={total_errors}")
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
