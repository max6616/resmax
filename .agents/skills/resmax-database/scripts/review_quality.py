from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping


REVIEW_TEXT_FIELDS = (
    "summary",
    "strengths",
    "weaknesses",
    "questions",
    "limitations",
    "ethics_review",
    "review_text",
)


def is_author_reviewer(reviewer_id: str) -> bool:
    value = (reviewer_id or "").strip()
    return value == "Authors" or value.endswith("/Authors")


def review_text_chars(review: Mapping[str, Any]) -> int:
    total = sum(len(str(review.get(field) or "")) for field in REVIEW_TEXT_FIELDS)
    content_fields = review.get("content_fields")
    if isinstance(content_fields, Mapping):
        total += sum(len(str(v or "")) for v in content_fields.values())
    return total


def review_has_payload(review: Mapping[str, Any]) -> bool:
    if review.get("rating") is not None or review.get("confidence") is not None:
        return True
    return review_text_chars(review) > 0


def clean_reviews(reviews: list[Any]) -> list[dict]:
    cleaned = []
    for review in reviews or []:
        if not isinstance(review, Mapping):
            continue
        reviewer_id = str(review.get("reviewer_id") or "")
        if is_author_reviewer(reviewer_id):
            continue
        if not review_has_payload(review):
            continue
        cleaned.append(dict(review))
    return cleaned


def assess_review_doc(doc: Mapping[str, Any]) -> dict[str, Any]:
    reviews = doc.get("reviews", []) or []
    if not isinstance(reviews, list):
        reviews = []

    stats: defaultdict[str, int] = defaultdict(int)
    field_nonempty = Counter()
    for review in reviews:
        if not isinstance(review, Mapping):
            continue
        stats["review_entries"] += 1
        reviewer_id = str(review.get("reviewer_id") or "")
        is_author = is_author_reviewer(reviewer_id)
        if is_author:
            stats["author_entries"] += 1
        else:
            stats["non_author_entries"] += 1

        chars = review_text_chars(review)
        stats["text_chars"] += chars
        if chars:
            stats["nonempty_entries"] += 1
        else:
            stats["blank_entries"] += 1
            if not is_author:
                stats["blank_non_author_entries"] += 1
        if review.get("rating") is not None:
            stats["rating_entries"] += 1
        if review.get("confidence") is not None:
            stats["confidence_entries"] += 1
        for field in REVIEW_TEXT_FIELDS:
            if review.get(field):
                field_nonempty[field] += 1
        content_fields = review.get("content_fields")
        if isinstance(content_fields, Mapping):
            for key, value in content_fields.items():
                if value:
                    field_nonempty[f"content_fields.{key}"] += 1

    meta_review = doc.get("meta_review")
    if isinstance(meta_review, Mapping):
        stats["meta_review_chars"] = sum(len(str(v or "")) for v in meta_review.values())
    elif meta_review:
        stats["meta_review_chars"] = len(str(meta_review))

    rebuttals = doc.get("rebuttals", []) or []
    stats["rebuttal_items"] = len(rebuttals) if isinstance(rebuttals, list) else 0
    return {
        "schema_version": int(doc.get("schema_version") or 0),
        "field_nonempty": dict(field_nonempty),
        **dict(stats),
    }


def summarize_docs(docs_by_conf_year: Mapping[str, list[Mapping[str, Any]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for conf_year, docs in sorted(docs_by_conf_year.items()):
        files = len(docs)
        counters: defaultdict[str, int] = defaultdict(int)
        field_counts = Counter()
        files_with_text = 0
        files_with_ratings = 0
        files_with_confidence = 0
        files_with_meta = 0
        files_with_rebuttals = 0
        for doc in docs:
            stats = assess_review_doc(doc)
            for key, value in stats.items():
                if isinstance(value, int):
                    counters[key] += value
            field_counts.update(stats.get("field_nonempty", {}))
            if stats.get("text_chars", 0) > 0:
                files_with_text += 1
            if stats.get("rating_entries", 0) > 0:
                files_with_ratings += 1
            if stats.get("confidence_entries", 0) > 0:
                files_with_confidence += 1
            if stats.get("meta_review_chars", 0) > 0:
                files_with_meta += 1
            if stats.get("rebuttal_items", 0) > 0:
                files_with_rebuttals += 1
        out[conf_year] = {
            "files": files,
            "files_with_text": files_with_text,
            "files_with_text_pct": pct(files_with_text, files),
            "files_with_ratings": files_with_ratings,
            "files_with_ratings_pct": pct(files_with_ratings, files),
            "files_with_confidence": files_with_confidence,
            "files_with_confidence_pct": pct(files_with_confidence, files),
            "files_with_meta_review": files_with_meta,
            "files_with_rebuttals": files_with_rebuttals,
            "review_entries": counters["review_entries"],
            "author_entries": counters["author_entries"],
            "non_author_entries": counters["non_author_entries"],
            "blank_entries": counters["blank_entries"],
            "blank_non_author_entries": counters["blank_non_author_entries"],
            "blank_non_author_entry_pct": pct(
                counters["blank_non_author_entries"],
                counters["non_author_entries"],
            ),
            "rating_entries": counters["rating_entries"],
            "confidence_entries": counters["confidence_entries"],
            "total_text_chars": counters["text_chars"],
            "avg_text_chars_per_file": round(counters["text_chars"] / files, 1) if files else 0.0,
            "field_nonempty": dict(sorted(field_counts.items())),
        }
    return out


def pct(num: int, den: int) -> float:
    return round(num / den * 100.0, 2) if den else 0.0

