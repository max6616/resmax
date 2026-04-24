"""Structured logging for the literature filtering pipeline.

Produces a human-readable Markdown log file that records every meaningful
event: retrieval counts, dedup stats, meta completeness, scoring decisions,
review adjustments, timing, and errors.

Supports JSON serialization/deserialization so that stages 1-4 (script mode)
can persist the log, and stages 5-7 (agent mode) can restore and continue.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class ScoreAdjustment:
    paper_id: str
    title: str
    original_score: str
    adjusted_score: str
    reason: str


@dataclass
class FilterLog:
    """Accumulates log entries throughout the filtering pipeline."""

    direction: str = ""
    keywords: list[str] = field(default_factory=list)
    start_time: float = 0.0

    # Stage 1: retrieval
    keyword_total_matches: int = 0
    keyword_kept: int = 0
    embedding_candidates: int = 0
    embedding_cache_size: int = 0
    embedding_top_sim: float = 0.0
    embedding_bottom_sim: float = 0.0

    # Stage 2: merge
    pre_dedup_total: int = 0
    duplicates_removed: int = 0
    merged_total: int = 0
    source_keyword_only: int = 0
    source_embedding_only: int = 0
    source_both: int = 0

    # Stage 3: meta enrichment
    meta_has_abstract: int = 0
    meta_has_pdf: int = 0
    meta_missing_abstract: int = 0
    meta_missing_pdf: int = 0
    meta_errors: list[str] = field(default_factory=list)
    meta_enriched_by_arxiv_id: int = 0
    meta_enriched_by_arxiv_search: int = 0
    meta_enriched_by_s2_search: int = 0

    # Stage 5: subagent scoring
    scoring_results: list[dict] = field(default_factory=list)

    # Stage 6: review adjustments
    adjustments: list[ScoreAdjustment] = field(default_factory=list)

    # Stage 7: final stats
    final_s: int = 0
    final_a: int = 0
    final_b: int = 0
    final_c: int = 0

    # Warnings / errors
    warnings: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # Stage timing
    stage_times: dict[str, float] = field(default_factory=dict)

    # -----------------------------------------------------------------------
    # Logging methods
    # -----------------------------------------------------------------------

    def log_error(self, msg: str) -> None:
        self.errors.append(msg)
        print(f"  [log] ERROR: {msg}")

    def log_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  [log] WARN: {msg}")

    def log_degraded(self, msg: str) -> None:
        self.degraded.append(msg)
        print(f"  [log] DEGRADED: {msg}")

    def log_scoring_result(
        self, paper_id: str, title: str, ai_score: str, ai_reason: str,
    ) -> None:
        self.scoring_results.append({
            "paper_id": paper_id,
            "title": title,
            "ai_score": ai_score,
            "ai_reason": ai_reason,
        })

    def log_adjustment(
        self,
        paper_id: str,
        title: str,
        original: str,
        adjusted: str,
        reason: str,
    ) -> None:
        self.adjustments.append(ScoreAdjustment(
            paper_id=paper_id,
            title=title,
            original_score=original,
            adjusted_score=adjusted,
            reason=reason,
        ))

    def start_stage(self, name: str) -> "_StageTimer":
        return _StageTimer(self, name)

    # -----------------------------------------------------------------------
    # JSON serialization / deserialization
    # -----------------------------------------------------------------------

    def to_json(self) -> str:
        """Serialize to JSON string."""
        d = asdict(self)
        return json.dumps(d, ensure_ascii=False, indent=2)

    def save_json(self, path: Path) -> None:
        """Save log state to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        print(f"[filter-log] saved state to {path}")

    @classmethod
    def load_json(cls, path: Path) -> "FilterLog":
        """Restore log state from a JSON file."""
        d = json.loads(path.read_text(encoding="utf-8"))
        log = cls()
        # Restore simple fields
        for k, v in d.items():
            if k == "adjustments":
                log.adjustments = [ScoreAdjustment(**a) for a in v]
            elif hasattr(log, k):
                setattr(log, k, v)
        print(f"[filter-log] restored state from {path}")
        return log

    # -----------------------------------------------------------------------
    # Markdown output
    # -----------------------------------------------------------------------

    def write(self, path: Path) -> None:
        """Write the complete log as a human-readable Markdown file."""
        total_elapsed = time.time() - self.start_time if self.start_time else 0

        lines = [
            "# Literature Filtering Log",
            "",
            f"**Direction**: {self.direction}",
            f"**Keywords**: {', '.join(self.keywords)}",
            f"**Total elapsed**: {total_elapsed:.1f}s",
            "",
            "---",
            "",
        ]

        # Stage 1
        lines.extend([
            "## Stage 1: Dual-path Retrieval",
            "",
            f"- Keyword search: {self.keyword_total_matches} matches, kept top {self.keyword_kept}",
            f"- Embedding search: {self.embedding_candidates} candidates (cache size: {self.embedding_cache_size})",
        ])
        if self.embedding_top_sim or self.embedding_bottom_sim:
            lines.append(f"- Embedding similarity range: {self.embedding_bottom_sim:.4f} ~ {self.embedding_top_sim:.4f}")
        if self.degraded:
            lines.append("- Degraded mode:")
            for msg in self.degraded:
                lines.append(f"  - {msg}")
        lines.append(f"- Stage time: {self.stage_times.get('retrieval', 0):.1f}s")
        lines.append("")

        # Stage 2
        lines.extend([
            "## Stage 2: Dedup & Merge",
            "",
            f"- Pre-dedup total: {self.pre_dedup_total}",
            f"- Duplicates removed: {self.duplicates_removed}",
            f"- Merged candidates: {self.merged_total}",
            f"  - keyword only: {self.source_keyword_only}",
            f"  - embedding only: {self.source_embedding_only}",
            f"  - both: {self.source_both}",
            f"- Stage time: {self.stage_times.get('merge', 0):.1f}s",
            "",
        ])

        # Stage 3
        lines.extend([
            "## Stage 3: Meta Enrichment",
            "",
            f"- Has abstract: {self.meta_has_abstract}/{self.merged_total}",
            f"- Has PDF link: {self.meta_has_pdf}/{self.merged_total}",
            f"- Missing abstract: {self.meta_missing_abstract}",
            f"- Missing PDF: {self.meta_missing_pdf}",
        ])
        if self.meta_enriched_by_arxiv_id or self.meta_enriched_by_arxiv_search or self.meta_enriched_by_s2_search:
            lines.append(f"- Enriched by arXiv ID: {self.meta_enriched_by_arxiv_id}")
            lines.append(f"- Enriched by arXiv search: {self.meta_enriched_by_arxiv_search}")
            lines.append(f"- Enriched by Semantic Scholar: {self.meta_enriched_by_s2_search}")
        if self.meta_errors:
            lines.append(f"- Errors ({len(self.meta_errors)}):")
            for e in self.meta_errors[:20]:
                lines.append(f"  - {e}")
            if len(self.meta_errors) > 20:
                lines.append(f"  - ... and {len(self.meta_errors) - 20} more")
        lines.append(f"- Stage time: {self.stage_times.get('meta_enrich', 0):.1f}s")
        lines.append("")

        # Stage 5: scoring
        if self.scoring_results:
            lines.extend([
                "## Stage 5: Subagent Scoring",
                "",
                f"- Papers scored: {len(self.scoring_results)}",
                f"- Stage time: {self.stage_times.get('scoring', 0):.1f}s",
                "",
                "| # | Paper ID | Title (truncated) | Score | Reason |",
                "|---|----------|-------------------|-------|--------|",
            ])
            for i, r in enumerate(self.scoring_results, 1):
                pid = r["paper_id"][:20]
                title = r["title"][:50] + ("..." if len(r["title"]) > 50 else "")
                reason = r["ai_reason"][:60] + ("..." if len(r["ai_reason"]) > 60 else "")
                lines.append(f"| {i} | {pid} | {title} | {r['ai_score']} | {reason} |")
            lines.append("")

        # Stage 6: adjustments
        if self.adjustments:
            lines.extend([
                "## Stage 6: Review Adjustments",
                "",
                f"- Total adjustments: {len(self.adjustments)}",
                "",
                "| Paper ID | Title (truncated) | Original | Adjusted | Reason |",
                "|----------|-------------------|----------|----------|--------|",
            ])
            for a in self.adjustments:
                pid = a.paper_id[:20]
                title = a.title[:40] + ("..." if len(a.title) > 40 else "")
                lines.append(f"| {pid} | {title} | {a.original_score} | {a.adjusted_score} | {a.reason} |")
            lines.append("")

        # Stage 7: final distribution
        final_total = self.final_s + self.final_a + self.final_b + self.final_c
        if final_total:
            lines.extend([
                "## Stage 7: Final Distribution",
                "",
                f"- S: {self.final_s}",
                f"- A: {self.final_a}",
                f"- B: {self.final_b}",
                f"- C: {self.final_c}",
                f"- Total: {final_total}",
                "",
            ])

        # Errors
        if self.warnings:
            lines.extend([
                "## Warnings",
                "",
            ])
            for e in self.warnings:
                lines.append(f"- {e}")
            lines.append("")

        if self.errors:
            lines.extend([
                "## Errors",
                "",
            ])
            for e in self.errors:
                lines.append(f"- {e}")
            lines.append("")

        # Timing summary
        lines.extend([
            "## Timing Summary",
            "",
            "| Stage | Time (s) |",
            "|-------|----------|",
        ])
        for stage, t in sorted(self.stage_times.items()):
            lines.append(f"| {stage} | {t:.1f} |")
        lines.append(f"| **total** | **{total_elapsed:.1f}** |")
        lines.append("")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[filter-log] wrote log to {path}")


class _StageTimer:
    """Context manager to time a pipeline stage."""

    def __init__(self, log: FilterLog, name: str):
        self.log = log
        self.name = name
        self.t0 = 0.0

    def __enter__(self) -> "_StageTimer":
        self.t0 = time.time()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.log.stage_times[self.name] = time.time() - self.t0
