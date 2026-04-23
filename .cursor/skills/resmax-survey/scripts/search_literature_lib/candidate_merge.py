"""Merge keyword and embedding retrieval results with deduplication.

Takes two candidate lists (keyword hits and embedding hits), deduplicates by
paper_id, and returns a merged list of at most `max_candidates` papers.
Each paper is annotated with its retrieval source.
"""
from __future__ import annotations

from .models import CandidatePaper
from .filter_logger import FilterLog


def merge_candidates(
    keyword_results: list[tuple[CandidatePaper, int]] | None,
    embedding_results: list[tuple[CandidatePaper, float]] | None,
    max_candidates: int = 100,
    log: FilterLog | None = None,
) -> list[CandidatePaper]:
    """Merge and deduplicate candidates from both retrieval paths.

    Returns a list of CandidatePaper with filter_source, keyword_hits,
    and embedding_score populated. Capped at max_candidates.
    """
    seen: dict[str, CandidatePaper] = {}

    kw_ids: set[str] = set()
    emb_ids: set[str] = set()

    if keyword_results:
        for paper, hits in keyword_results:
            pid = paper.paper_id
            kw_ids.add(pid)
            if pid not in seen:
                seen[pid] = paper
            seen[pid].keyword_hits = hits

    if embedding_results:
        for paper, score in embedding_results:
            pid = paper.paper_id
            emb_ids.add(pid)
            if pid not in seen:
                seen[pid] = paper
            seen[pid].embedding_score = score

    for pid, paper in seen.items():
        in_kw = pid in kw_ids
        in_emb = pid in emb_ids
        if in_kw and in_emb:
            paper.filter_source = "both"
        elif in_kw:
            paper.filter_source = "keyword"
        else:
            paper.filter_source = "embedding"

    pre_dedup = (len(keyword_results) if keyword_results else 0) + \
                (len(embedding_results) if embedding_results else 0)
    merged = list(seen.values())

    # Sort: "both" first, then by keyword_hits + embedding_score as tiebreaker
    def sort_key(p: CandidatePaper) -> tuple:
        source_priority = {"both": 0, "keyword": 1, "embedding": 1}
        return (
            source_priority.get(p.filter_source, 2),
            -p.keyword_hits,
            -p.embedding_score,
        )

    merged.sort(key=sort_key)
    result = merged[:max_candidates]

    source_both = sum(1 for p in result if p.filter_source == "both")
    source_kw = sum(1 for p in result if p.filter_source == "keyword")
    source_emb = sum(1 for p in result if p.filter_source == "embedding")

    print(f"[merge] {pre_dedup} pre-dedup → {len(merged)} unique → {len(result)} kept "
          f"(both={source_both}, keyword={source_kw}, embedding={source_emb})")

    if log:
        log.pre_dedup_total = pre_dedup
        log.duplicates_removed = pre_dedup - len(merged)
        log.merged_total = len(result)
        log.source_both = source_both
        log.source_keyword_only = source_kw
        log.source_embedding_only = source_emb

    return result
