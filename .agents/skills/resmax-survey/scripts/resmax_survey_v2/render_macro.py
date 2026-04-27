from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


BROAD_CANDIDATE_FIELDS = [
    "paper_id",
    "title",
    "venue",
    "year",
    "conf_year",
    "abstract_raw",
    "keywords_raw",
    "paper_link",
    "landing_url",
    "pdf_url",
    "doi",
    "arxiv_id",
    "openreview_forum_id",
    "source_tier",
    "source_weight",
    "source_text_status",
    "source_text_url",
    "source_text_source",
    "source_text_evidence",
    "source_text_search_query",
    "review_score_status",
    "query_roles",
    "query_ids",
    "match_count",
    "best_keyword_score",
    "best_embedding_score",
    "candidate_grade",
    "candidate_grade_score",
    "candidate_grade_reasons",
    "has_code",
    "has_dataset",
    "has_pretrained_weights",
    "rough_positive_signal",
    "rough_difficulty_signal",
    "rough_roi_confidence",
    "rough_roi_evidence_status",
    "roi_unknowns",
    "subdirection_id",
]

ROI_FIELDS = [
    "subdirection_id",
    "label",
    "paper_count",
    "positive_signals",
    "difficulty_signals",
    "benchmark_burden",
    "compute_burden",
    "baseline_burden",
    "reviewer_risk",
    "evidence_status",
    "rough_roi_confidence",
    "roi_unknowns",
    "representative_papers",
]


def write_macro_outputs(
    *,
    out_dir: Path,
    research_spec: dict[str, Any],
    source_policy: dict[str, Any],
    candidates: list[dict[str, Any]],
    subdirection_map: dict[str, Any],
    roi_rows: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> None:
    macro_dir = out_dir / "survey_v2" / "macro"
    macro_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(macro_dir / "broad_candidates.csv", BROAD_CANDIDATE_FIELDS, candidates)
    _write_json(macro_dir / "subdirection_map.json", subdirection_map)
    (macro_dir / "subdirection_map.md").write_text(_render_subdirection_map(subdirection_map), encoding="utf-8")
    _write_csv(macro_dir / "subdirection_roi_table.csv", ROI_FIELDS, roi_rows)
    (macro_dir / "macro_survey_report.md").write_text(
        _render_report(research_spec, source_policy, subdirection_map, roi_rows),
        encoding="utf-8",
    )
    _write_json(out_dir / "survey_v2" / "manifest.json", manifest)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_subdirection_map(subdirection_map: dict[str, Any]) -> str:
    lines = [
        "# Survey V2 Subdirection Map",
        "",
        "> Phase 2 macro labels are rough clusters, not idea recommendations.",
        "",
    ]
    for entry in subdirection_map["subdirections"]:
        lines.extend(
            [
                f"## {entry['label']}",
                "",
                f"- ID: `{entry['subdirection_id']}`",
                f"- Papers: {entry['paper_count']}",
                f"- Query roles: {', '.join(entry['query_roles']) or 'unknown'}",
                f"- Evidence status: {entry['evidence_status']}",
                f"- ROI unknowns: {', '.join(entry['roi_unknowns']) or 'unknown'}",
                "",
            ]
        )
    return "\n".join(lines)


def _render_report(
    research_spec: dict[str, Any],
    source_policy: dict[str, Any],
    subdirection_map: dict[str, Any],
    roi_rows: list[dict[str, Any]],
) -> str:
    lines = [
        "# Survey V2 Macro Survey Report",
        "",
        f"- Raw intent: {research_spec['raw_intent']}",
        f"- ResearchSpec: `{research_spec['state_id']}`",
        f"- SourcePolicy: `{source_policy['state_id']}`",
        f"- Subdirections: {len(subdirection_map['subdirections'])}",
        "",
        "## Boundary",
        "",
        "- This report is display-only; JSON/CSV artifacts are the source of truth.",
        "- Phase 2 emits rough ROI signals with low confidence only.",
        "- Unknown benchmark, compute, baseline, and reviewer-risk fields remain unknown.",
        "- No final idea, strong recommendation, full-text extraction, MinerU, Sci-Hub, or experiment plan is produced.",
        "",
        "## Rough ROI Table",
        "",
        "| Subdirection | Positive Signals | Difficulty Signals | Evidence | Unknowns |",
        "|---|---|---|---|---|",
    ]
    for row in roi_rows:
        lines.append(
            f"| {row['label']} | {row['positive_signals']} | {row['difficulty_signals']} | "
            f"{row['evidence_status']} / {row['rough_roi_confidence']} | {row['roi_unknowns']} |"
        )
    lines.append("")
    return "\n".join(lines)
