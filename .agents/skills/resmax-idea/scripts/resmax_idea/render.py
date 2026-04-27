from __future__ import annotations

from pathlib import Path
from typing import Any


def render_reports(out_dir: Path, ideas: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    _write_strongest_rejections(out_dir / "strongest_rejection_cases.md", ideas)
    _write_cheapest_falsification(out_dir / "cheapest_falsification.md", ideas)
    _write_idea_report(out_dir / "idea_report.md", ideas, checks)


def _write_strongest_rejections(path: Path, ideas: list[dict[str, Any]]) -> None:
    lines = [
        "# Strongest Rejection Cases",
        "",
        "This Markdown file is rendered from `idea_cards.jsonl`.",
        "",
    ]
    for idea in ideas:
        lines.extend(
            [
                f"## {idea['idea_id']}",
                "",
                f"- Status: `{idea['status']}`",
                f"- Strongest rejection: {idea['strongest_rejection_case']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_cheapest_falsification(path: Path, ideas: list[dict[str, Any]]) -> None:
    lines = [
        "# Cheapest Falsification Notes",
        "",
        "This Markdown file is rendered from `idea_cards.jsonl`.",
        "",
    ]
    for idea in ideas:
        falsification = idea["cheapest_falsification"]
        lines.extend(
            [
                f"## {idea['idea_id']}",
                "",
                f"- Claim to falsify: {falsification['claim_to_falsify']}",
                f"- Minimal test: {falsification['minimal_test']}",
                f"- Falsifies if: {falsification['falsifies_if']}",
                f"- Required baselines: `{', '.join(falsification['required_baseline_ids']) or 'none'}`",
                f"- Expected cost: `{falsification['expected_cost']}`",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_idea_report(path: Path, ideas: list[dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    check_by_idea = {check["idea_id"]: check for check in checks}
    lines = [
        "# Resmax Idea Portfolio",
        "",
        "This Markdown file is rendered from structured artifacts only: `idea_cards.jsonl`, `closest_work_checks.jsonl`, and `idea_lineage.json`.",
        "",
        "## Portfolio Summary",
        "",
        f"- Candidate ideas: {len(ideas)}",
        f"- Phase 6 ready: {sum(1 for idea in ideas if idea.get('readiness', {}).get('phase6_review_ready'))}",
        f"- Experiment blueprint ready: {sum(1 for idea in ideas if idea.get('readiness', {}).get('experiment_blueprint_ready'))}",
        "",
    ]
    for idea in ideas:
        check = check_by_idea.get(idea["idea_id"], {})
        lines.extend(
            [
                f"## {idea['idea_id']} — {idea['title']}",
                "",
                f"- Status: `{idea['status']}`",
                f"- Source gaps: `{', '.join(idea['source_gap_ids']) or 'none'}`",
                f"- Evidence: `{', '.join(idea['evidence_ids']) or 'none'}`",
                f"- Closest work: `{', '.join(idea['closest_work_ids']) or 'none'}`",
                f"- Core delta: {idea['core_delta']}",
                f"- Primary claim: {idea['primary_claim']}",
                f"- Phase 6 ready: `{str(idea['readiness']['phase6_review_ready']).lower()}`",
                f"- Experiment blueprint ready: `{str(idea['readiness']['experiment_blueprint_ready']).lower()}`",
                f"- Novelty proximity: `{check.get('novelty_proximity', 'unknown')}`",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")
