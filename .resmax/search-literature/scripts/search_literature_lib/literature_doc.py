"""Generate and update the literature list Markdown document.

Produces a human-readable Markdown file with PDF hyperlinks, sorted by
AI relevance score. Supports two modes:

  1. generate_unscored(): Initial document without scores (after meta enrichment)
  2. generate_scored(): Final document with AI scores and reasons (after scoring)
"""
from __future__ import annotations

from pathlib import Path

from .models import CandidatePaper


_SCORE_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "": 4}


def _paper_entry(p: CandidatePaper, idx: int, scored: bool = False) -> list[str]:
    """Format a single paper as Markdown lines."""
    lines = []

    title_display = p.title or "(untitled)"
    if scored and p.final_score:
        lines.append(f"### {idx}. [{p.final_score}] {title_display}")
    else:
        lines.append(f"### {idx}. {title_display}")

    meta_parts = []
    if p.venue and p.year:
        meta_parts.append(f"{p.venue} {p.year}")
    elif p.conf_year:
        meta_parts.append(p.conf_year)
    if p.authors:
        authors_short = p.authors if len(p.authors) <= 80 else p.authors[:77] + "..."
        meta_parts.append(authors_short)
    if meta_parts:
        lines.append(f"**{' | '.join(meta_parts)}**")

    links = []
    if p.pdf_url:
        links.append(f"[PDF]({p.pdf_url})")
    if p.paper_link and p.paper_link != p.pdf_url:
        links.append(f"[Paper]({p.paper_link})")
    if p.arxiv_url:
        links.append(f"[arXiv]({p.arxiv_url})")
    if links:
        lines.append(" | ".join(links))

    lines.append(f"Source: {p.filter_source}")

    if scored:
        if p.ai_reason:
            lines.append(f"**AI Assessment**: {p.ai_reason}")
        if p.review_adjusted:
            lines.append(
                f"**Review Adjusted**: {p.ai_score} → {p.review_adjusted} "
                f"({p.review_adjust_reason})"
            )

    if p.abstract_raw:
        abstract_display = p.abstract_raw[:300]
        if len(p.abstract_raw) > 300:
            abstract_display += "..."
        lines.append(f"> {abstract_display}")

    lines.append("")
    return lines


def generate_unscored(
    candidates: list[CandidatePaper],
    direction: str,
    out_path: Path,
) -> None:
    """Generate the initial literature list without scores."""
    lines = [
        f"# Literature List: {direction}",
        "",
        f"**Candidates**: {len(candidates)}",
        "",
        "---",
        "",
    ]

    for i, p in enumerate(candidates, 1):
        lines.extend(_paper_entry(p, i, scored=False))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[literature-doc] wrote unscored document: {out_path} ({len(candidates)} papers)")


def generate_scored(
    candidates: list[CandidatePaper],
    direction: str,
    out_path: Path,
) -> None:
    """Generate the final scored literature list, sorted by grade."""
    sorted_papers = sorted(
        candidates,
        key=lambda p: (
            _SCORE_ORDER.get(p.final_score, 4),
            -p.embedding_score,
            -p.keyword_hits,
        ),
    )

    grade_counts = {}
    for p in sorted_papers:
        g = p.final_score or "unscored"
        grade_counts[g] = grade_counts.get(g, 0) + 1

    lines = [
        f"# Literature List: {direction}",
        "",
        f"**Total**: {len(sorted_papers)}",
        "",
        "**Distribution**: " + ", ".join(
            f"{g}={c}" for g, c in sorted(grade_counts.items(),
                                           key=lambda x: _SCORE_ORDER.get(x[0], 4))
        ),
        "",
        "---",
        "",
    ]

    current_grade = None
    idx = 1
    for p in sorted_papers:
        grade = p.final_score or "Unscored"
        if grade != current_grade:
            current_grade = grade
            lines.append(f"## Grade {current_grade}")
            lines.append("")

        lines.extend(_paper_entry(p, idx, scored=True))
        idx += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[literature-doc] wrote scored document: {out_path} ({len(sorted_papers)} papers)")
