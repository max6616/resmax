from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import REQUIRED_PHASE4_ARTIFACTS


def resolve_pack_dir(path: Path) -> Path:
    path = path.resolve()
    return path if path.name == "research_pack" else path / "research_pack"


@dataclass(frozen=True)
class PackContext:
    pack_dir: Path
    manifest: dict[str, Any]
    research_spec: dict[str, Any]
    gap_map: dict[str, Any]
    claim_graph: dict[str, Any]
    evidence_cards: list[dict[str, Any]]
    evidence_spans: list[dict[str, Any]]
    reviewer_notes: list[dict[str, Any]]
    paper_roles: dict[str, Any]
    roi_lens: dict[str, Any]
    broad_candidates: list[dict[str, str]]
    selected_subdirection: dict[str, Any]

    @classmethod
    def load(cls, pack: Path) -> "PackContext":
        pack_dir = resolve_pack_dir(pack)
        if not pack_dir.exists():
            raise FileNotFoundError(f"research_pack does not exist: {pack_dir}")
        missing = [rel for rel in REQUIRED_PHASE4_ARTIFACTS if not (pack_dir / rel).exists()]
        if missing:
            raise FileNotFoundError("Phase 4 ROI-aware research_pack is incomplete: " + ", ".join(missing))
        return cls(
            pack_dir=pack_dir,
            manifest=_read_json(pack_dir / "manifest.json"),
            research_spec=_read_optional_json(pack_dir / "research_spec.json"),
            gap_map=_read_json(pack_dir / "gap_map.json"),
            claim_graph=_read_json(pack_dir / "claim_graph.json"),
            evidence_cards=_read_jsonl(pack_dir / "evidence_cards.jsonl"),
            evidence_spans=_read_jsonl(pack_dir / "evidence_spans.jsonl"),
            reviewer_notes=_read_jsonl(pack_dir / "reviewer_pressure_notes.jsonl"),
            paper_roles=_read_json(pack_dir / "paper_roles.json"),
            roi_lens=_read_json(pack_dir / "roi_lens.json"),
            broad_candidates=_read_csv(pack_dir / "broad_candidates.csv"),
            selected_subdirection=_read_optional_json(pack_dir / "selected_subdirection.json"),
        )

    @property
    def gaps(self) -> list[dict[str, Any]]:
        return [gap for gap in self.gap_map.get("gaps", []) if isinstance(gap, dict)]

    @property
    def gap_ids(self) -> set[str]:
        return {gap.get("gap_id", "") for gap in self.gaps if gap.get("gap_id")}

    @property
    def claim_ids(self) -> set[str]:
        return {
            claim.get("claim_id", "")
            for claim in self.claim_graph.get("claims", [])
            if isinstance(claim, dict) and claim.get("claim_id")
        }

    @property
    def evidence_ids(self) -> set[str]:
        return {card.get("state_id", "") for card in self.evidence_cards if card.get("state_id")}

    @property
    def paper_ids(self) -> set[str]:
        ids = {row.get("paper_id", "") for row in self.broad_candidates if row.get("paper_id")}
        ids.update({assignment.get("paper_id", "") for assignment in self.role_assignments if assignment.get("paper_id")})
        return ids

    @property
    def role_assignments(self) -> list[dict[str, Any]]:
        return [
            row
            for row in self.paper_roles.get("assignments", [])
            if isinstance(row, dict) and row.get("paper_id")
        ]

    @property
    def source_index(self) -> dict[str, list[str]]:
        return {
            "gap_ids": sorted(self.gap_ids),
            "claim_ids": sorted(self.claim_ids),
            "evidence_ids": sorted(self.evidence_ids),
            "paper_ids": sorted(self.paper_ids),
            "research_pack_state_ids": [
                item
                for item in (self.manifest.get("state_id"), self.gap_map.get("state_id"), self.claim_graph.get("state_id"))
                if item
            ],
        }

    def roi_for_gap(self, gap_id: str) -> dict[str, Any]:
        for entry in self.roi_lens.get("gap_roi", []):
            if isinstance(entry, dict) and entry.get("gap_id") == gap_id:
                return entry
        return {}

    def reviewer_notes_for_gap(self, gap_id: str) -> list[dict[str, Any]]:
        return [note for note in self.reviewer_notes if note.get("gap_id") == gap_id]

    def title_for_paper(self, paper_id: str) -> str:
        for row in self.broad_candidates:
            if row.get("paper_id") == paper_id:
                return row.get("title", paper_id) or paper_id
        for assignment in self.role_assignments:
            if assignment.get("paper_id") == paper_id:
                return assignment.get("title", paper_id) or paper_id
        return paper_id

    def roles_for_paper(self, paper_id: str) -> set[str]:
        for assignment in self.role_assignments:
            if assignment.get("paper_id") == paper_id:
                return {role.get("role", "") for role in assignment.get("roles", []) if isinstance(role, dict)}
        return set()

    def paper_ids_for_gap(self, gap: dict[str, Any]) -> list[str]:
        paper_ids: list[str] = []
        for card_id in gap.get("evidence_card_ids", []):
            paper_id = self.paper_id_for_card(card_id)
            if paper_id:
                paper_ids.append(paper_id)
        return _dedupe(paper_ids)

    def paper_id_for_card(self, card_id: str) -> str:
        card = next((row for row in self.evidence_cards if row.get("state_id") == card_id), {})
        if card.get("paper_id"):
            return str(card["paper_id"])
        spans = {row.get("state_id"): row for row in self.evidence_spans if row.get("state_id")}
        for span_id in card.get("evidence_span_ids", []):
            span = spans.get(span_id, {})
            if span.get("paper_id"):
                return str(span["paper_id"])
        return ""

    def paper_ids_with_role(self, gap: dict[str, Any], role: str) -> list[str]:
        candidates = self.paper_ids_for_gap(gap)
        if not candidates and gap.get("evidence_card_ids"):
            candidates = sorted(self.paper_ids)
        out = [paper_id for paper_id in candidates if role in self.roles_for_paper(paper_id)]
        return _dedupe(out)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"expected JSON object at {path}:{line_no}")
            rows.append(row)
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
