from __future__ import annotations

from pathlib import Path
from typing import Any


def render_blocker_summary(path: Path, decisions: list[dict[str, Any]]) -> None:
    lines = [
        "# Phase 6 Blocker Summary",
        "",
        "This report is rendered from structured review decisions. It is not a facts source.",
        "",
    ]
    for row in decisions:
        blockers = row.get("blockers", [])
        lines.append(f"## {row['idea_id']} - {row['final_status']}")
        lines.append("")
        if not blockers:
            lines.append("- No blockers recorded.")
        for blocker in blockers:
            lines.append(
                "- "
                f"{blocker.get('severity', 'unknown')} / {blocker.get('blocker_type', 'unknown')}: "
                f"{blocker.get('explanation', '')}"
            )
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def render_disagreement_report(path: Path, decisions: list[dict[str, Any]]) -> None:
    lines = [
        "# Phase 6 Disagreement Report",
        "",
        "This report is rendered from raw review traces and aggregation decisions.",
        "",
    ]
    for row in decisions:
        if not row.get("disagreement"):
            continue
        lines.append(f"## {row['idea_id']}")
        lines.append("")
        lines.append(f"- Final status: {row['final_status']}")
        lines.append(f"- Reviewer statuses: {', '.join(row.get('reviewer_statuses', []))}")
        lines.append(f"- Reason: {'; '.join(row.get('decision_reasons', []))}")
        lines.append("")
    if len(lines) == 4:
        lines.append("No unresolved reviewer disagreement recorded.")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
