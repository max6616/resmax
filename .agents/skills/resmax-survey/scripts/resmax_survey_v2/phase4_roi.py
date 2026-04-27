from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now

from .phase3_pack import resolve_pack_dir


PRODUCER = {"name": "resmax_survey_v2.phase4_roi", "version": SCHEMA_VERSION, "run_id": "phase4"}

POSITIVE_DIMENSIONS = (
    "publication_upside",
    "novelty_headroom",
    "evidence_confidence",
    "benchmark_leverage",
    "implementation_reuse",
    "story_clarity",
    "information_gap",
)

DIFFICULTY_DIMENSIONS = (
    "sota_pressure",
    "baseline_burden",
    "compute_cost",
    "data_friction",
    "engineering_risk",
    "timeline_risk",
    "review_risk",
)

OBJECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "novelty": ("novelty", "novel", "incremental", "original", "contribution", "similar", "prior work"),
    "baseline": ("baseline", "comparison", "compare", "sota", "state-of-the-art", "stronger baseline"),
    "theory": ("theory", "theorem", "proof", "bound", "assumption", "mathematical", "rigor", "guarantee"),
    "clarity": ("unclear", "clarity", "presentation", "hard to follow", "confusing", "missing reference", "not clear"),
    "ablation": ("ablation", "sensitivity", "analysis", "component", "isolate"),
    "dataset": ("dataset", "data", "benchmark", "evaluation", "experiment", "empirical"),
    "efficiency": ("efficient", "efficiency", "runtime", "compute", "cost", "scalability", "complexity", "expensive"),
    "reproducibility": ("reproduc", "code", "implementation", "details", "algorithm", "pseudocode", "hyperparameter"),
}

ROLE_TAXONOMY = (
    "direct_baseline",
    "method_donor",
    "benchmark_opportunity",
    "dataset_source",
    "implementation_reference",
    "negative_evidence",
    "survey_or_taxonomy",
    "theory_or_mechanism",
    "visualization_reference",
    "reviewer_expectation_reference",
)


def extract_reviewer_pressure(
    *,
    pack: Path,
    reviews: Path | None = None,
    accepted: Path | None = None,
    out: Path | None = None,
    max_notes_per_paper: int = 4,
) -> dict[str, Any]:
    pack_dir = _prepare_pack(pack, out)
    context = _load_pack_context(pack_dir)
    review_index = _ReviewIndex(reviews, accepted)

    notes: list[dict[str, Any]] = []
    missing_review_targets: list[dict[str, str]] = []
    for paper_id in context.paper_ids:
        row = {**context.paper_rows.get(paper_id, {}), **review_index.row_for(paper_id)}
        review = review_index.find(paper_id, row)
        if review is None:
            if _review_expected(row):
                raise FileNotFoundError(
                    "expected review cache is missing for "
                    f"{paper_id}; run resmax-database/scripts/ensure_reviews_available.py before Phase 4"
                )
            missing_review_targets.append(
                {
                    "paper_id": paper_id,
                    "target": f"retrieve peer review cache for {paper_id}",
                    "reason": "review_cache_missing_or_unavailable",
                }
            )
            continue
        paper_notes = _notes_from_review(
            paper_id=paper_id,
            review=review,
            context=context,
            max_notes=max_notes_per_paper,
        )
        notes.extend(paper_notes)

    _write_jsonl(pack_dir / "reviewer_pressure_notes.jsonl", notes)
    _update_manifest(
        pack_dir,
        source_counts={
            "reviewer_pressure_notes": len(notes),
            "real_review_notes": len([note for note in notes if not note.get("inferred")]),
            "inferred_review_notes": len([note for note in notes if note.get("inferred")]),
            "missing_review_follow_up_targets": len(missing_review_targets),
        },
        mechanical_checks={
            "reviewer_pressure_uses_real_review_cache": bool(notes),
            "reviewer_pressure_marks_inferred_items": all(
                (not note.get("inferred")) or note.get("source_kind") == "inferred" for note in notes
            ),
        },
    )
    return {
        "pack_dir": str(pack_dir),
        "reviewer_pressure_notes": len(notes),
        "missing_review_follow_up_targets": len(missing_review_targets),
    }


def assign_paper_roles(*, pack: Path, out: Path | None = None) -> dict[str, Any]:
    pack_dir = _prepare_pack(pack, out)
    context = _load_pack_context(pack_dir)
    notes = _read_jsonl(pack_dir / "reviewer_pressure_notes.jsonl")

    note_by_paper: dict[str, list[dict[str, Any]]] = {}
    for note in notes:
        note_by_paper.setdefault(note.get("paper_id", ""), []).append(note)

    assignments: list[dict[str, Any]] = []
    for paper_id in context.paper_ids:
        row = context.paper_rows.get(paper_id, {})
        paper_cards = context.cards_by_paper.get(paper_id, [])
        paper_notes = note_by_paper.get(paper_id, [])
        roles = _roles_for_paper(row, paper_cards, paper_notes)
        assignments.append(
            {
                "paper_id": paper_id,
                "title": row.get("title", ""),
                "roles": roles,
                "primary_role": roles[0]["role"] if roles else "benchmark_opportunity",
                "role_evidence": {
                    "query_roles": _split_tokens(row.get("query_roles", "")),
                    "evidence_card_ids": [card["state_id"] for card in paper_cards],
                    "review_note_ids": [note["note_id"] for note in paper_notes],
                    "metadata": {
                        "has_code": row.get("has_code", ""),
                        "has_dataset": row.get("has_dataset", ""),
                        "has_pretrained_weights": row.get("has_pretrained_weights", ""),
                        "source_text_status": row.get("source_text_status", ""),
                        "review_score_status": row.get("review_score_status", ""),
                    },
                },
            }
        )

    paper_roles = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "producer": PRODUCER,
        "role_taxonomy": list(ROLE_TAXONOMY),
        "assignments": assignments,
    }
    _write_json(pack_dir / "paper_roles.json", paper_roles)
    _write_baseline_matrix(pack_dir, assignments, context, note_by_paper)
    _write_benchmark_matrix(pack_dir, assignments, context, note_by_paper)
    _write_implementation_matrix(pack_dir, assignments, context, note_by_paper)

    _update_manifest(
        pack_dir,
        source_counts={
            "paper_role_assignments": len(assignments),
            "assigned_role_count": sum(len(row["roles"]) for row in assignments),
        },
        mechanical_checks={
            "paper_role_taxonomy_complete": set(ROLE_TAXONOMY).issubset(set(paper_roles["role_taxonomy"])),
        },
    )
    return {"pack_dir": str(pack_dir), "paper_role_assignments": len(assignments)}


def build_roi_lens(
    *,
    pack: Path,
    reviews: Path | None = None,
    accepted: Path | None = None,
    out: Path | None = None,
    max_notes_per_paper: int = 4,
) -> dict[str, Any]:
    pressure = extract_reviewer_pressure(
        pack=pack,
        reviews=reviews,
        accepted=accepted,
        out=out,
        max_notes_per_paper=max_notes_per_paper,
    )
    pack_dir = Path(pressure["pack_dir"])
    roles = assign_paper_roles(pack=pack_dir)
    context = _load_pack_context(pack_dir)
    notes = _read_jsonl(pack_dir / "reviewer_pressure_notes.jsonl")
    role_payload = _load_json(pack_dir / "paper_roles.json")
    role_by_paper = {row["paper_id"]: row for row in role_payload.get("assignments", [])}

    gap_entries: list[dict[str, Any]] = []
    table_rows: list[dict[str, str]] = []
    for gap in context.gaps:
        gap_notes = [note for note in notes if note.get("gap_id") == gap.get("gap_id")]
        gap_papers = context.paper_ids_for_gap(gap)
        positive = _positive_signals(gap, gap_papers, context, role_by_paper)
        difficulty = _difficulty_signals(gap, gap_papers, context, gap_notes, role_by_paper)
        unknowns = _unknowns_for_gap(gap, gap_papers, context, gap_notes)
        confidence = _roi_confidence(gap, unknowns, gap_notes)
        entry = {
            "gap_id": gap.get("gap_id", ""),
            "gap_type": gap.get("gap_type", ""),
            "description": gap.get("description", ""),
            "scope": gap.get("scope", ""),
            "positive_signals": positive,
            "difficulty_signals": difficulty,
            "unknowns": unknowns,
            "reviewer_blockers": [
                {
                    "note_id": note["note_id"],
                    "objection_type": note["objection_type"],
                    "severity": note["severity"],
                    "source_review_id": note["source_review_id"],
                }
                for note in gap_notes
            ],
            "confidence": confidence,
            "decision_support": {
                "rank_basis": "dimension_vector_with_blockers_and_unknowns",
                "single_roi_score": None,
                "dominant_decision_reason": "not_applicable",
            },
        }
        gap_entries.append(entry)
        table_rows.append(_gap_roi_row(entry))

    roi_lens = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("roi_lens", {"gaps": [entry["gap_id"] for entry in gap_entries]}),
        "created_at": utc_now(),
        "input_hash": input_hash({"gap_entries": gap_entries}),
        "parent_state_ids": [context.gap_map.get("state_id", "")],
        "producer": PRODUCER,
        "positive_dimensions": list(POSITIVE_DIMENSIONS),
        "difficulty_dimensions": list(DIFFICULTY_DIMENSIONS),
        "gap_roi": gap_entries,
        "decision_policy": {
            "single_roi_score_allowed": False,
            "unknown_policy": "unknowns reduce confidence and emit follow-up retrieval targets",
            "reviewer_policy": "reviewers detect blockers; notes do not become ideas directly",
        },
    }
    _write_csv(pack_dir / "gap_roi_table.csv", table_rows, _gap_roi_fields())
    _write_json(pack_dir / "roi_lens.json", roi_lens)
    _write_risk_register(pack_dir, gap_entries)
    _write_idea_seed_constraints(pack_dir, gap_entries)

    unknown_target_count = sum(len(entry["unknowns"]) for entry in gap_entries)
    reviewer_blocker_count = sum(len(entry["reviewer_blockers"]) for entry in gap_entries)
    _update_manifest(
        pack_dir,
        source_counts={
            "gap_roi_rows": len(gap_entries),
            "unknown_follow_up_targets": unknown_target_count,
            "reviewer_blockers": reviewer_blocker_count,
        },
        mechanical_checks={
            "single_black_box_roi_score_absent": True,
            "unknowns_emit_follow_up_targets": all(
                unknown.get("follow_up_retrieval_target") for entry in gap_entries for unknown in entry["unknowns"]
            ),
            "risk_register_references_structured_artifacts": True,
            "idea_seed_constraints_are_constraints_not_ideas": True,
        },
    )
    return {
        "pack_dir": str(pack_dir),
        "reviewer_pressure_notes": pressure["reviewer_pressure_notes"],
        "paper_role_assignments": roles["paper_role_assignments"],
        "gap_roi_rows": len(gap_entries),
        "unknown_follow_up_targets": unknown_target_count,
    }


class _ReviewIndex:
    def __init__(self, reviews: Path | None, accepted: Path | None) -> None:
        self.reviews = reviews.resolve() if reviews else None
        self.accepted = accepted.resolve() if accepted else None
        self.accepted_rows = _read_rows_by_paper(self.accepted) if self.accepted and self.accepted.exists() else {}
        self.by_paper_id: dict[str, dict[str, Any]] = {}
        self.by_forum_id: dict[str, dict[str, Any]] = {}
        self._scanned = False

    def row_for(self, paper_id: str) -> dict[str, str]:
        return dict(self.accepted_rows.get(paper_id, {}))

    def find(self, paper_id: str, row: dict[str, str]) -> dict[str, Any] | None:
        if self.reviews:
            candidates = _review_candidates(self.reviews, row)
            for path in candidates:
                if path.exists():
                    return self._load_review_file(path)
        if paper_id in self.by_paper_id:
            return self.by_paper_id[paper_id]
        forum_id = row.get("openreview_forum_id", "") or row.get("forum_id", "")
        if forum_id and forum_id in self.by_forum_id:
            return self.by_forum_id[forum_id]
        if self.reviews and self.reviews.exists() and not self._scanned:
            self._scan_reviews(self.reviews)
            self._scanned = True
            if paper_id in self.by_paper_id:
                return self.by_paper_id[paper_id]
            if forum_id and forum_id in self.by_forum_id:
                return self.by_forum_id[forum_id]
        return None

    def _scan_reviews(self, root: Path) -> None:
        for path in sorted(root.rglob("*.json")):
            review = self._load_review_file(path)
            paper_id = str(review.get("paper_id", "") or "")
            forum_id = str(review.get("forum_id", "") or review.get("openreview_forum_id", "") or "")
            if paper_id:
                self.by_paper_id.setdefault(paper_id, review)
            if forum_id:
                self.by_forum_id.setdefault(forum_id, review)

    def _load_review_file(self, path: Path) -> dict[str, Any]:
        data = _load_json(path)
        if isinstance(data, dict):
            data = dict(data)
            data["_source_path"] = str(path)
            return data
        return {"_source_path": str(path), "reviews": []}


class _PackContext:
    def __init__(self, pack_dir: Path) -> None:
        self.pack_dir = pack_dir
        self.research_spec = _load_optional_json(pack_dir / "research_spec.json")
        self.selected = _load_optional_json(pack_dir / "selected_subdirection.json")
        self.spans = _read_jsonl(pack_dir / "evidence_spans.jsonl")
        self.cards = _read_jsonl(pack_dir / "evidence_cards.jsonl")
        self.gap_map = _load_json(pack_dir / "gap_map.json")
        self.gaps = self.gap_map.get("gaps", [])
        self.paper_rows = _read_rows_by_paper(pack_dir / "broad_candidates.csv")
        self.spans_by_id = {span.get("state_id", ""): span for span in self.spans}
        self.cards_by_id = {card.get("state_id", ""): card for card in self.cards}
        self.cards_by_paper: dict[str, list[dict[str, Any]]] = {}
        for card in self.cards:
            paper_id = self.paper_id_from_card(card)
            if paper_id:
                self.cards_by_paper.setdefault(paper_id, []).append(card)
        self.gap_by_card: dict[str, list[dict[str, Any]]] = {}
        for gap in self.gaps:
            for card_id in gap.get("evidence_card_ids", []):
                self.gap_by_card.setdefault(card_id, []).append(gap)
        selected_ids = self.selected.get("selected_candidate_ids", [])
        self.paper_ids = list(selected_ids) or sorted(set(self.paper_rows) | set(self.cards_by_paper))

    def gaps_for_paper(self, paper_id: str) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        for card in self.cards_by_paper.get(paper_id, []):
            gaps.extend(self.gap_by_card.get(card.get("state_id", ""), []))
        if gaps:
            return _dedupe_dicts(gaps, "gap_id")
        missing = [gap for gap in self.gaps if gap.get("gap_type") == "missing_evidence"]
        return missing or self.gaps[:1]

    def evidence_ids_for_gap_and_paper(self, gap: dict[str, Any], paper_id: str) -> list[str]:
        paper_card_ids = {card.get("state_id", "") for card in self.cards_by_paper.get(paper_id, [])}
        return [card_id for card_id in gap.get("evidence_card_ids", []) if card_id in paper_card_ids]

    def paper_ids_for_gap(self, gap: dict[str, Any]) -> list[str]:
        paper_ids: list[str] = []
        for card_id in gap.get("evidence_card_ids", []):
            card = self.cards_by_id.get(card_id)
            if card:
                paper_id = self.paper_id_from_card(card)
                if paper_id:
                    paper_ids.append(paper_id)
        return _dedupe(paper_ids) or self.paper_ids

    def paper_id_from_card(self, card: dict[str, Any]) -> str:
        if card.get("paper_id"):
            return str(card["paper_id"])
        for span_id in card.get("evidence_span_ids", []):
            span = self.spans_by_id.get(span_id, {})
            if span.get("paper_id"):
                return str(span["paper_id"])
        return ""


def _load_pack_context(pack_dir: Path) -> _PackContext:
    return _PackContext(pack_dir)


def _prepare_pack(pack: Path, out: Path | None) -> Path:
    source = resolve_pack_dir(pack)
    if out is None:
        return source
    target = resolve_pack_dir(out)
    if source.resolve() == target.resolve():
        return source
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    return target


def _notes_from_review(
    *,
    paper_id: str,
    review: dict[str, Any],
    context: _PackContext,
    max_notes: int,
) -> list[dict[str, Any]]:
    raw_items = _review_text_items(review)
    candidates: list[dict[str, Any]] = []
    for item in raw_items:
        objection_type, match_count = _classify_objection(item["text"])
        if match_count <= 0:
            continue
        candidates.append(
            {
                **item,
                "objection_type": objection_type,
                "match_count": match_count,
                "severity": _severity(item["text"], item.get("rating")),
            }
        )
    candidates.sort(key=lambda item: (_severity_rank(item["severity"]), item["match_count"], len(item["text"])), reverse=True)

    notes: list[dict[str, Any]] = []
    gaps = context.gaps_for_paper(paper_id)
    for item in candidates[:max_notes]:
        for gap in gaps[:3]:
            evidence_ids = context.evidence_ids_for_gap_and_paper(gap, paper_id) or [
                card.get("state_id", "") for card in context.cards_by_paper.get(paper_id, []) if card.get("state_id")
            ]
            note_input = {
                "paper_id": paper_id,
                "gap_id": gap.get("gap_id", ""),
                "reviewer": item.get("reviewer_id", ""),
                "field": item.get("field", ""),
                "objection_type": item["objection_type"],
                "text_hash": _stable_hash(item["text"]),
            }
            notes.append(
                {
                    "note_id": make_state_id("reviewer_pressure_note", note_input),
                    "schema_version": SCHEMA_VERSION,
                    "created_at": utc_now(),
                    "paper_id": paper_id,
                    "gap_id": gap.get("gap_id", ""),
                    "objection_type": item["objection_type"],
                    "objection_text": _clip(item["text"], 900),
                    "severity": item["severity"],
                    "resolved_by_authors": _resolved_by_authors(review, item["objection_type"]),
                    "source_review_id": item.get("source_review_id", ""),
                    "source_kind": "review_cache",
                    "source_path": review.get("_source_path", ""),
                    "inferred": False,
                    "evidence_ids": evidence_ids,
                    "implication_for_new_idea": _implication(item["objection_type"], gap),
                }
            )
    return notes


def _review_text_items(review: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    forum_id = str(review.get("forum_id", "") or review.get("openreview_forum_id", ""))
    for index, entry in enumerate(review.get("reviews", []) if isinstance(review.get("reviews"), list) else []):
        if not isinstance(entry, dict):
            continue
        reviewer_id = str(entry.get("reviewer_id", "") or entry.get("signature", "") or f"reviewer_{index + 1}")
        rating = _to_float(entry.get("rating"))
        for field in ("weaknesses", "questions", "limitations", "summary"):
            text = _normalize_text(entry.get(field, ""))
            if len(text) < 30:
                continue
            items.append(
                {
                    "field": field,
                    "text": text,
                    "rating": rating,
                    "reviewer_id": reviewer_id,
                    "source_review_id": f"{forum_id}:{reviewer_id}:{field}" if forum_id else f"{reviewer_id}:{field}",
                }
            )
    return items


def _classify_objection(text: str) -> tuple[str, int]:
    lowered = text.lower()
    scores = {
        label: sum(1 for keyword in keywords if keyword in lowered)
        for label, keywords in OBJECTION_KEYWORDS.items()
    }
    label, score = max(scores.items(), key=lambda item: (item[1], item[0]))
    return label, score


def _severity(text: str, rating: float) -> str:
    lowered = text.lower()
    if rating and rating <= 4.5:
        return "high"
    if any(term in lowered for term in ("main criticism", "serious", "major concern", "severe", "fatal")):
        return "high"
    if rating and rating <= 6.0:
        return "medium"
    if any(term in lowered for term in ("lack", "missing", "unclear", "weak", "limited", "concern")):
        return "medium"
    return "low"


def _severity_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value, 0)


def _resolved_by_authors(review: dict[str, Any], objection_type: str) -> str:
    rebuttals = review.get("rebuttals", [])
    if not isinstance(rebuttals, list) or not rebuttals:
        return "unknown"
    terms = OBJECTION_KEYWORDS.get(objection_type, ())
    text = " ".join(_normalize_text(item.get("content", "")) for item in rebuttals if isinstance(item, dict)).lower()
    if any(term in text for term in terms):
        return "claimed_resolved"
    return "rebuttal_present"


def _implication(objection_type: str, gap: dict[str, Any]) -> str:
    return (
        f"Treat {objection_type} as a blocker constraint for gap {gap.get('gap_id', '')}; "
        "do not convert this review objection directly into an idea."
    )


def _roles_for_paper(
    row: dict[str, str],
    cards: list[dict[str, Any]],
    notes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = " ".join(
        [
            row.get("title", ""),
            row.get("query_roles", ""),
            row.get("rough_positive_signal", ""),
            row.get("rough_difficulty_signal", ""),
            " ".join(card.get("claim_text", "") + " " + card.get("interpretation", "") for card in cards),
            " ".join(note.get("objection_type", "") + " " + note.get("objection_text", "") for note in notes),
        ]
    ).lower()
    roles: list[dict[str, Any]] = []

    def add(role: str, reason: str, strength: str = "medium") -> None:
        if role not in {item["role"] for item in roles}:
            roles.append({"role": role, "strength": strength, "reason": reason})

    if "direct_baseline" in row.get("query_roles", "") or "baseline" in text:
        add("direct_baseline", "baseline or comparison signal appears in metadata/evidence/review")
    if any(term in text for term in ("method", "diffusion", "transformer", "planning", "mechanism", "algorithm")):
        add("method_donor", "method or mechanism signal appears in title/evidence")
    if "benchmark_opportunity" in row.get("query_roles", "") or any(term in text for term in ("benchmark", "evaluation", "dataset")):
        add("benchmark_opportunity", "benchmark/evaluation signal appears in query roles or evidence", "high")
    if _is_yes(row.get("has_dataset", "")) or "dataset" in text:
        add("dataset_source", "dataset signal is available or discussed")
    if _is_yes(row.get("has_code", "")) or row.get("code_url", ""):
        add("implementation_reference", "code metadata is available", "high")
    if notes or any(card.get("relation") == "motivates" for card in cards):
        add("negative_evidence", "reviewer objections or motivating evidence mark constraints")
    if any(term in text for term in ("survey", "taxonomy", "overview")):
        add("survey_or_taxonomy", "survey/taxonomy signal appears")
    if any(term in text for term in ("theory", "theorem", "mechanism", "proof", "bound")):
        add("theory_or_mechanism", "theory or mechanism signal appears")
    if any(term in text for term in ("visual", "scene", "figure", "visualization")):
        add("visualization_reference", "visual or visualization signal appears")
    if notes:
        add("reviewer_expectation_reference", "real reviewer objections are linked", "high")
    if not roles:
        add("benchmark_opportunity", "default role from selected research pack candidate context", "low")
    return roles


def _write_baseline_matrix(
    pack_dir: Path,
    assignments: list[dict[str, Any]],
    context: _PackContext,
    note_by_paper: dict[str, list[dict[str, Any]]],
) -> None:
    rows = []
    for assignment in assignments:
        paper_id = assignment["paper_id"]
        rows.append(
            {
                "paper_id": paper_id,
                "title": assignment.get("title", ""),
                "is_direct_baseline": _role_strength(assignment, "direct_baseline"),
                "baseline_burden": _baseline_burden(context.paper_rows.get(paper_id, {}), note_by_paper.get(paper_id, [])),
                "reviewer_blockers": "|".join(note["objection_type"] for note in note_by_paper.get(paper_id, [])),
                "evidence_card_ids": "|".join(card["state_id"] for card in context.cards_by_paper.get(paper_id, [])),
                "review_note_ids": "|".join(note["note_id"] for note in note_by_paper.get(paper_id, [])),
                "follow_up_targets": _follow_up_for_unknown(context.paper_rows.get(paper_id, {}), "baseline_burden"),
            }
        )
    _write_csv(pack_dir / "baseline_matrix.csv", rows, list(rows[0]) if rows else [])


def _write_benchmark_matrix(
    pack_dir: Path,
    assignments: list[dict[str, Any]],
    context: _PackContext,
    note_by_paper: dict[str, list[dict[str, Any]]],
) -> None:
    rows = []
    for assignment in assignments:
        paper_id = assignment["paper_id"]
        row = context.paper_rows.get(paper_id, {})
        rows.append(
            {
                "paper_id": paper_id,
                "title": assignment.get("title", ""),
                "benchmark_role": _role_strength(assignment, "benchmark_opportunity"),
                "dataset_source_role": _role_strength(assignment, "dataset_source"),
                "has_dataset": row.get("has_dataset", "unknown") or "unknown",
                "benchmark_leverage": _benchmark_leverage(row, context.cards_by_paper.get(paper_id, [])),
                "reviewer_dataset_objections": "|".join(
                    note["note_id"] for note in note_by_paper.get(paper_id, []) if note["objection_type"] == "dataset"
                ),
                "follow_up_targets": _follow_up_for_unknown(row, "benchmark_burden"),
            }
        )
    _write_csv(pack_dir / "benchmark_matrix.csv", rows, list(rows[0]) if rows else [])


def _write_implementation_matrix(
    pack_dir: Path,
    assignments: list[dict[str, Any]],
    context: _PackContext,
    note_by_paper: dict[str, list[dict[str, Any]]],
) -> None:
    rows = []
    for assignment in assignments:
        paper_id = assignment["paper_id"]
        row = context.paper_rows.get(paper_id, {})
        rows.append(
            {
                "paper_id": paper_id,
                "title": assignment.get("title", ""),
                "implementation_role": _role_strength(assignment, "implementation_reference"),
                "has_code": row.get("has_code", "unknown") or "unknown",
                "has_pretrained_weights": row.get("has_pretrained_weights", "unknown") or "unknown",
                "implementation_reuse": _implementation_reuse(row, assignment),
                "engineering_risk": _engineering_risk(row, note_by_paper.get(paper_id, [])),
                "follow_up_targets": _follow_up_for_unknown(row, "implementation_reference"),
            }
        )
    _write_csv(pack_dir / "implementation_matrix.csv", rows, list(rows[0]) if rows else [])


def _positive_signals(
    gap: dict[str, Any],
    paper_ids: list[str],
    context: _PackContext,
    role_by_paper: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    roi = gap.get("roi_signals", {})
    positive_tokens = set(roi.get("positive", []))
    paper_rows = [context.paper_rows.get(pid, {}) for pid in paper_ids]
    roles = [role["role"] for pid in paper_ids for role in role_by_paper.get(pid, {}).get("roles", [])]
    return {
        "publication_upside": _dimension("medium" if any(_recent_top_venue(row) for row in paper_rows) else "unknown", list(positive_tokens)),
        "novelty_headroom": _dimension(
            "medium"
            if gap.get("gap_type")
            in {
                "method_transfer",
                "resource_arbitrage",
                "benchmark_blind_spot",
                "benchmark_protocol_gap",
                "temporal_action_coherence",
                "feedforward_native_gaussian_editing",
                "large_magnitude_editing",
            }
            else "unknown",
            [gap.get("gap_type", "")],
        ),
        "evidence_confidence": _dimension(_evidence_confidence_value(gap), gap.get("evidence_card_ids", [])),
        "benchmark_leverage": _dimension("medium" if "benchmark_opportunity" in roles or "benchmark_mentions" in positive_tokens else "unknown", roles),
        "implementation_reuse": _dimension("medium" if "implementation_reference" in roles or "implementation_reuse" in positive_tokens else "unknown", roles),
        "story_clarity": _dimension("low" if gap.get("evidence_status") == "insufficient_evidence" else "medium", [gap.get("description", "")]),
        "information_gap": _dimension("high" if roi.get("unknowns") else "medium", roi.get("unknowns", [])),
    }


def _difficulty_signals(
    gap: dict[str, Any],
    paper_ids: list[str],
    context: _PackContext,
    notes: list[dict[str, Any]],
    role_by_paper: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    roi = gap.get("roi_signals", {})
    difficulty_tokens = set(roi.get("difficulty", []))
    rows = [context.paper_rows.get(pid, {}) for pid in paper_ids]
    roles = [role["role"] for pid in paper_ids for role in role_by_paper.get(pid, {}).get("roles", [])]
    note_types = {note["objection_type"] for note in notes}
    compute_value = _compute_cost_value(gap, context, notes, difficulty_tokens)
    return {
        "sota_pressure": _dimension("medium" if any(_recent_top_venue(row) for row in rows) else "unknown", [row.get("venue", "") for row in rows]),
        "baseline_burden": _dimension("high" if "baseline" in note_types else _unknown_or_medium(difficulty_tokens, "baseline_burden"), list(note_types)),
        "compute_cost": _dimension(compute_value, list(difficulty_tokens) + [context.research_spec.get("compute_budget", "")]),
        "data_friction": _dimension("medium" if "dataset" in note_types or "dataset_source" not in roles else "low", list(note_types)),
        "engineering_risk": _dimension("medium" if "implementation_reference" not in roles else "low", roles),
        "timeline_risk": _dimension("medium" if gap.get("evidence_status") == "insufficient_evidence" else "low", [gap.get("evidence_status", "")]),
        "review_risk": _dimension(_review_risk_value(notes, roi), [note["note_id"] for note in notes]),
    }


def _unknowns_for_gap(
    gap: dict[str, Any],
    paper_ids: list[str],
    context: _PackContext,
    notes: list[dict[str, Any]],
) -> list[dict[str, str]]:
    raw_unknowns = list(gap.get("roi_signals", {}).get("unknowns", []))
    if _known_compute_budget(context):
        raw_unknowns = [item for item in raw_unknowns if item not in {"compute_burden", "compute_cost"}]
    for paper_id in paper_ids:
        row = context.paper_rows.get(paper_id, {})
        raw_unknowns.extend(_split_tokens(row.get("roi_unknowns", "")))
        if row.get("review_score_status", "") in {"", "unknown", "unavailable"}:
            raw_unknowns.append("reviewer_risk")
        if row.get("has_code", "") in {"", "unknown"}:
            raw_unknowns.append("implementation_reference")
    if not notes:
        raw_unknowns.append("reviewer_pressure")
    return [
        {
            "field": field,
            "reason": "unknown preserved as uncertainty, not converted to zero",
            "follow_up_retrieval_target": _retrieval_target_for_unknown(field, paper_ids),
            "confidence_impact": "lowers_gap_roi_confidence",
        }
        for field in _dedupe(raw_unknowns)
        if field
    ]


def _compute_cost_value(
    gap: dict[str, Any],
    context: _PackContext,
    notes: list[dict[str, Any]],
    difficulty_tokens: set[str],
) -> str:
    if _known_compute_budget(context) and gap.get("gap_type") in {
        "temporal_action_coherence",
        "feedforward_native_gaussian_editing",
        "large_magnitude_editing",
        "resource_arbitrage",
    }:
        return "medium" if any(note["objection_type"] == "efficiency" for note in notes) else "low"
    if any(note["objection_type"] == "efficiency" for note in notes):
        return "high"
    return _unknown_or_medium(difficulty_tokens, "compute_burden")


def _known_compute_budget(context: _PackContext) -> bool:
    value = str(context.research_spec.get("compute_budget", "")).strip().lower()
    return bool(value and value != "unknown")


def _gap_roi_row(entry: dict[str, Any]) -> dict[str, str]:
    return {
        "gap_id": entry["gap_id"],
        "gap_type": entry["gap_type"],
        "confidence": entry["confidence"],
        "positive_signals": "|".join(f"{name}:{payload['value']}" for name, payload in entry["positive_signals"].items()),
        "difficulty_signals": "|".join(f"{name}:{payload['value']}" for name, payload in entry["difficulty_signals"].items()),
        "unknowns": "|".join(item["field"] for item in entry["unknowns"]),
        "follow_up_retrieval_targets": "|".join(item["follow_up_retrieval_target"] for item in entry["unknowns"]),
        "reviewer_blockers": "|".join(item["note_id"] for item in entry["reviewer_blockers"]),
        "single_roi_score": "",
    }


def _gap_roi_fields() -> list[str]:
    return [
        "gap_id",
        "gap_type",
        "confidence",
        "positive_signals",
        "difficulty_signals",
        "unknowns",
        "follow_up_retrieval_targets",
        "reviewer_blockers",
        "single_roi_score",
    ]


def _write_risk_register(pack_dir: Path, gap_entries: list[dict[str, Any]]) -> None:
    lines = [
        "# Phase 4 Risk Register",
        "",
        "Generated from `roi_lens.json`, `reviewer_pressure_notes.jsonl`, and `gap_roi_table.csv`.",
        "",
        "| Gap | Review blockers | Unknowns | Highest difficulty | Structured refs |",
        "|---|---:|---:|---|---|",
    ]
    for entry in gap_entries:
        difficulties = entry["difficulty_signals"]
        highest = _highest_dimension(difficulties)
        lines.append(
            "| {gap} | {blockers} | {unknowns} | {highest} | `roi_lens.json#{gap}`, `gap_roi_table.csv` |".format(
                gap=entry["gap_id"],
                blockers=len(entry["reviewer_blockers"]),
                unknowns=len(entry["unknowns"]),
                highest=highest,
            )
        )
    lines.extend(
        [
            "",
            "Boundary: this register identifies blocker surfaces only. It does not promote ideas or replace Phase 6 review.",
            "",
        ]
    )
    (pack_dir / "risk_register.md").write_text("\n".join(lines), encoding="utf-8")


def _write_idea_seed_constraints(pack_dir: Path, gap_entries: list[dict[str, Any]]) -> None:
    lines = [
        "# Phase 4 Idea Seed Constraints",
        "",
        "These are constraints for Phase 5 idea generation, not ideas.",
        "",
    ]
    for entry in gap_entries:
        blocker_types = sorted({blocker["objection_type"] for blocker in entry["reviewer_blockers"]})
        unknown_fields = [item["field"] for item in entry["unknowns"]]
        lines.extend(
            [
                f"## {entry['gap_id']}",
                "",
                f"- Gap type: `{entry['gap_type']}`",
                f"- Must address reviewer blockers: {', '.join(blocker_types) if blocker_types else 'none recorded'}",
                f"- Must retrieve before strong promotion: {', '.join(unknown_fields) if unknown_fields else 'none'}",
                "- Do not treat review objections as idea text; use them as acceptance constraints.",
                "",
            ]
        )
    (pack_dir / "idea_seed_constraints.md").write_text("\n".join(lines), encoding="utf-8")


def _update_manifest(
    pack_dir: Path,
    *,
    source_counts: dict[str, int] | None = None,
    mechanical_checks: dict[str, bool] | None = None,
) -> None:
    manifest_path = pack_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    existing_by_path = {
        artifact["path"]: artifact
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict) and artifact.get("path")
    }
    for kind, rel_path in _phase4_artifacts():
        path = pack_dir / rel_path
        if path.exists():
            existing_by_path[rel_path] = {"kind": kind, "path": rel_path, "sha256": _sha256_file(path)}
    for artifact in list(existing_by_path.values()):
        path = pack_dir / artifact["path"]
        if path.exists():
            artifact["sha256"] = _sha256_file(path)
    manifest["artifacts"] = list(existing_by_path.values())
    manifest["artifact_count"] = len(manifest["artifacts"])
    manifest["producer"] = PRODUCER
    manifest.setdefault("source_counts", {}).update(source_counts or {})
    manifest.setdefault("mechanical_checks", {}).update(mechanical_checks or {})
    manifest_input = {
        "research_spec_id": manifest.get("research_spec_id", ""),
        "artifact_hashes": [artifact.get("sha256", "") for artifact in manifest["artifacts"]],
        "source_counts": manifest.get("source_counts", {}),
        "mechanical_checks": manifest.get("mechanical_checks", {}),
    }
    manifest["input_hash"] = input_hash(manifest_input)
    manifest["state_id"] = make_state_id("research_pack", manifest_input)
    _write_json(manifest_path, manifest)


def _phase4_artifacts() -> tuple[tuple[str, str], ...]:
    return (
        ("reviewer_pressure_notes", "reviewer_pressure_notes.jsonl"),
        ("paper_roles", "paper_roles.json"),
        ("baseline_matrix", "baseline_matrix.csv"),
        ("benchmark_matrix", "benchmark_matrix.csv"),
        ("implementation_matrix", "implementation_matrix.csv"),
        ("gap_roi_table", "gap_roi_table.csv"),
        ("roi_lens", "roi_lens.json"),
        ("risk_register", "risk_register.md"),
        ("idea_seed_constraints", "idea_seed_constraints.md"),
    )


def _review_candidates(reviews_dir: Path, row: dict[str, str]) -> list[Path]:
    candidates: list[Path] = []
    detail = row.get("review_detail_path", "")
    if detail:
        raw = Path(detail)
        candidates.extend([raw, reviews_dir / raw, reviews_dir.parent / raw])
        if "reviews" in raw.parts:
            idx = raw.parts.index("reviews")
            candidates.append(reviews_dir / Path(*raw.parts[idx + 1 :]))
    forum_id = row.get("openreview_forum_id", "") or row.get("forum_id", "")
    conf_year = row.get("conf_year", "")
    if forum_id:
        if conf_year:
            candidates.append(reviews_dir / conf_year / f"{forum_id}.json")
        candidates.append(reviews_dir / f"{forum_id}.json")
    return candidates


def _review_expected(row: dict[str, str]) -> bool:
    if (row.get("review_available", "") or "").strip().lower() == "yes":
        return True
    return (row.get("review_score_status", "") or "").strip().lower() in {"complete", "partial", "no_scores"}


def _dimension(value: str, refs: Iterable[str]) -> dict[str, Any]:
    clean = value if value in {"low", "medium", "high", "unknown"} else "unknown"
    return {"value": clean, "refs": [ref for ref in refs if ref], "inferred": clean == "unknown"}


def _evidence_confidence_value(gap: dict[str, Any]) -> str:
    if gap.get("evidence_status") == "supported" and len(gap.get("evidence_card_ids", [])) >= 2:
        return "medium"
    if gap.get("evidence_status") == "supported":
        return "low"
    return "unknown"


def _unknown_or_medium(tokens: set[str], token: str) -> str:
    return "unknown" if token in tokens or f"{token}_unknown" in tokens else "medium"


def _review_risk_value(notes: list[dict[str, Any]], roi: dict[str, Any]) -> str:
    if any(note["severity"] == "high" for note in notes):
        return "high"
    if notes:
        return "medium"
    if "reviewer_risk" in roi.get("unknowns", []):
        return "unknown"
    return "low"


def _roi_confidence(gap: dict[str, Any], unknowns: list[dict[str, str]], notes: list[dict[str, Any]]) -> str:
    if len(unknowns) >= 3 or gap.get("evidence_status") == "insufficient_evidence":
        return "low"
    if any(note["severity"] == "high" for note in notes):
        return "low"
    if unknowns:
        return "medium"
    return "medium"


def _baseline_burden(row: dict[str, str], notes: list[dict[str, Any]]) -> str:
    if any(note["objection_type"] == "baseline" for note in notes):
        return "high"
    if "baseline_burden" in row.get("roi_unknowns", ""):
        return "unknown"
    return "medium"


def _benchmark_leverage(row: dict[str, str], cards: list[dict[str, Any]]) -> str:
    if "benchmark_mentions" in row.get("rough_positive_signal", "") or any(card.get("relation") == "supports" for card in cards):
        return "medium"
    if "benchmark_burden" in row.get("roi_unknowns", ""):
        return "unknown"
    return "low"


def _implementation_reuse(row: dict[str, str], assignment: dict[str, Any]) -> str:
    if _role_strength(assignment, "implementation_reference") in {"medium", "high"}:
        return "medium"
    if row.get("has_code", "") in {"", "unknown"}:
        return "unknown"
    return "low"


def _engineering_risk(row: dict[str, str], notes: list[dict[str, Any]]) -> str:
    if any(note["objection_type"] in {"efficiency", "reproducibility"} for note in notes):
        return "high"
    if _is_yes(row.get("has_code", "")):
        return "low"
    return "medium"


def _follow_up_for_unknown(row: dict[str, str], field: str) -> str:
    unknowns = set(_split_tokens(row.get("roi_unknowns", "")))
    if field in unknowns or f"{field}_unknown" in unknowns or row.get(field, "") in {"", "unknown"}:
        return _retrieval_target_for_unknown(field, [row.get("paper_id", "")])
    return ""


def _retrieval_target_for_unknown(field: str, paper_ids: list[str]) -> str:
    joined = ",".join(pid for pid in paper_ids if pid)
    if field in {"reviewer_risk", "reviewer_pressure"}:
        return f"fetch review cache and meta-review objections for {joined}"
    if "baseline" in field:
        return f"extract compared baselines and missing SOTA checks for {joined}"
    if "compute" in field:
        return f"extract compute budget, runtime, and hardware cost for {joined}"
    if "benchmark" in field:
        return f"extract benchmark datasets, metrics, and evaluation protocol for {joined}"
    if "implementation" in field:
        return f"verify code, weights, dependencies, and reproduction path for {joined}"
    return f"retrieve missing ROI evidence field {field} for {joined}"


def _role_strength(assignment: dict[str, Any], role: str) -> str:
    for item in assignment.get("roles", []):
        if item.get("role") == role:
            return item.get("strength", "medium")
    return "none"


def _highest_dimension(dimensions: dict[str, dict[str, Any]]) -> str:
    ranked = sorted(
        dimensions.items(),
        key=lambda item: {"unknown": 0, "low": 1, "medium": 2, "high": 3}.get(item[1].get("value", "unknown"), 0),
        reverse=True,
    )
    if not ranked:
        return "unknown"
    return f"{ranked[0][0]}:{ranked[0][1].get('value', 'unknown')}"


def _recent_top_venue(row: dict[str, str]) -> bool:
    return row.get("venue", "") in {"ICLR", "ICML", "NeurIPS", "CVPR", "ICCV"} and _to_float(row.get("year")) >= 2024


def _read_rows_by_paper(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as f:
        return {row.get("paper_id", ""): row for row in csv.DictReader(f) if row.get("paper_id", "")}


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load_json(path)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                rows.append(json.loads(raw))
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _stable_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_text(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    if not isinstance(value, str):
        value = str(value or "")
    return re.sub(r"\s+", " ", value).strip()


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 3].rstrip() + "..."


def _split_tokens(value: str) -> list[str]:
    return _dedupe([part.strip() for part in re.split(r"[|,;]+", value or "") if part.strip() and part.strip() != "unknown"])


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _dedupe_dicts(values: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for value in values:
        marker = value.get(key, "")
        if marker not in seen:
            seen.add(marker)
            out.append(value)
    return out


def _is_yes(value: str) -> bool:
    return (value or "").strip().lower() in {"yes", "true", "1", "y"}


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
