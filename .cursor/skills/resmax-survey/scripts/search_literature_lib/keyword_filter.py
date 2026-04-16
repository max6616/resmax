"""Keyword-based paper retrieval from accepted index.

Pure keyword matching — no LLM involved. Returns candidate papers sorted by
keyword hit count. The LLM-based scoring has been moved to the subagent
scoring stage (subagent_scorer.py).
"""
from __future__ import annotations

from .models import CandidatePaper


def _normalize(text: str) -> str:
    return text.lower().strip()


def keyword_retrieve(
    papers: list[CandidatePaper],
    keywords: list[str],
    top_k: int = 50,
) -> list[tuple[CandidatePaper, int]]:
    """Retrieve papers whose title or abstract matches any keyword.

    Returns up to `top_k` papers as (paper, hit_count) sorted by hits desc.
    """
    kw_lower = [_normalize(k) for k in keywords if k.strip()]
    if not kw_lower:
        raise ValueError("At least one keyword is required for keyword retrieval")

    scored: list[tuple[CandidatePaper, int]] = []
    for p in papers:
        text = _normalize(p.title + " " + p.abstract_raw)
        hits = sum(1 for kw in kw_lower if kw in text)
        if hits > 0:
            scored.append((p, hits))

    scored.sort(key=lambda x: -x[1])
    result = scored[:top_k]
    print(f"[keyword-retrieval] {len(scored)} total matches, kept top {len(result)}")
    return result


# Keep old name as alias for backward compatibility
keyword_filter = keyword_retrieve
