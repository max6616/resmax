from __future__ import annotations

import csv
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional


@dataclass
class CandidatePaper:
    """A paper candidate from accepted_index with relevance scoring."""
    paper_id: str = ""
    short_id: str = ""
    title: str = ""
    venue: str = ""
    year: int = 0
    conf_year: str = ""
    authors: str = ""
    abstract_raw: str = ""
    paper_link: str = ""
    arxiv_id: str = ""
    arxiv_url: str = ""
    keywords_raw: str = ""
    source_type: str = ""
    source_url: str = ""
    openreview_forum_id: str = ""
    has_pdf_camera_ready: str = ""

    # --- fields added by research-index-init ---
    state: str = "Wait"
    filter_source: str = ""       # "keyword" / "embedding" / "both"
    keyword_hits: int = 0
    embedding_score: float = 0.0  # raw cosine similarity

    # --- subagent scoring ---
    ai_score: str = ""            # S / A / B / C
    ai_reason: str = ""
    review_adjusted: str = ""     # "" if not adjusted, else new grade
    review_adjust_reason: str = ""
    final_score: str = ""         # = review_adjusted if adjusted, else ai_score

    # --- downstream fields (populated by later skills) ---
    importance: str = ""          # alias for final_score, kept for compatibility
    core_or_edge: str = ""
    tags: str = ""
    topic_bucket: str = ""
    pdf_path: str = ""

    # --- meta enrichment ---
    has_abstract: bool = False
    has_pdf_link: bool = False
    pdf_url: str = ""
    openreview_rating_mean: str = ""
    openreview_confidence_mean: str = ""
    openreview_decision: str = ""
    presentation_type: str = ""
    citation_count: str = ""

    # --- openness passthrough (from accepted_index, enriched by resmax-database) ---
    code_url: str = ""
    code_is_real: str = ""
    code_stars: str = ""
    code_last_commit: str = ""
    code_primary_language: str = ""
    has_pretrained_weights: str = ""
    has_dataset: str = ""

    # --- openness deepcheck (populated in Stage 3.5) ---
    code_quality: str = ""              # full / partial / skeleton / dead (agent verdict)
    hf_models: str = ""                  # comma-separated HF model IDs
    hf_datasets: str = ""                # comma-separated HF dataset IDs
    reproduction_readiness: int = 0     # 0-5 integer from agent review


RESEARCH_INDEX_FIELDS = [f.name for f in fields(CandidatePaper)]


def load_accepted_index(path: Path) -> list[CandidatePaper]:
    records: list[CandidatePaper] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(CandidatePaper(
                paper_id=row.get("paper_id", ""),
                short_id=row.get("short_id", ""),
                title=row.get("title", ""),
                venue=row.get("venue", ""),
                year=int(row.get("year", 0) or 0),
                conf_year=row.get("conf_year", ""),
                authors=row.get("authors", ""),
                abstract_raw=row.get("abstract_raw", ""),
                paper_link=row.get("paper_link", ""),
                arxiv_id=row.get("arxiv_id", ""),
                arxiv_url=row.get("arxiv_url", ""),
                keywords_raw=row.get("keywords_raw", ""),
                source_type=row.get("source_type", ""),
                source_url=row.get("source_url", ""),
                openreview_forum_id=row.get("openreview_forum_id", ""),
                has_pdf_camera_ready=row.get("has_pdf_camera_ready", ""),
                openreview_rating_mean=row.get("review_score_mean", ""),
                openreview_confidence_mean=row.get("review_confidence_mean", ""),
                openreview_decision=row.get("decision", ""),
                code_url=row.get("code_url", ""),
                code_is_real=row.get("code_is_real", ""),
                code_stars=row.get("code_stars", ""),
                code_last_commit=row.get("code_last_commit", ""),
                code_primary_language=row.get("code_primary_language", ""),
                has_pretrained_weights=row.get("has_pretrained_weights", ""),
                has_dataset=row.get("has_dataset", ""),
            ))
    return records


def write_research_index(path: Path, records: list[CandidatePaper]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESEARCH_INDEX_FIELDS)
        writer.writeheader()
        for r in records:
            row = {}
            for fn in RESEARCH_INDEX_FIELDS:
                val = getattr(r, fn)
                if isinstance(val, bool):
                    val = "1" if val else "0"
                row[fn] = val
            writer.writerow(row)


def load_research_index(path: Path) -> list[CandidatePaper]:
    """Load an existing research index CSV back into CandidatePaper objects."""
    records: list[CandidatePaper] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            p = CandidatePaper()
            for fn in RESEARCH_INDEX_FIELDS:
                if fn not in row:
                    continue
                val = row[fn]
                fld = next(fd for fd in fields(CandidatePaper) if fd.name == fn)
                if fld.type == "int":
                    setattr(p, fn, int(val or 0))
                elif fld.type == "float":
                    setattr(p, fn, float(val or 0.0))
                elif fld.type == "bool":
                    setattr(p, fn, val in ("1", "True", "true"))
                else:
                    setattr(p, fn, val)
            records.append(p)
    return records


def direction_slug(direction: str) -> str:
    """Convert a research direction string to a filesystem-safe slug."""
    import re
    slug = direction.strip().lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '_', slug)
    return slug[:80].rstrip('_')
