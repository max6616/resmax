from __future__ import annotations

from pathlib import Path


def write_report(path: Path, sections: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["# accepted index coverage report", ""]
    for section in sections:
        lines.append(f"## {section['conf_year']}")
        lines.append("")
        lines.append(f"- status: {section['status']}")
        if section.get("skip_reason"):
            lines.append(f"- skip_reason: {section['skip_reason']}")
        if section.get("primary_url"):
            lines.append(f"- primary_source: {section['primary_url']}")
        if section.get("expected_count") is not None:
            lines.append(f"- expected_count: {section['expected_count']}")
        lines.append(f"- primary_records: {section.get('primary_records', 0)}")
        lines.append(f"- auxiliary_records: {section.get('auxiliary_records', 0)}")
        lines.append(f"- merged_records: {section.get('merged_records', 0)}")
        if section.get("coverage_gap") is not None:
            lines.append(f"- coverage_gap: {section['coverage_gap']}")
        errors = section.get("errors", [])
        if errors:
            lines.append("- errors:")
            for err in errors:
                lines.append(f"  - {err}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
