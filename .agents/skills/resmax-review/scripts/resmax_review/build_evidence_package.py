from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now

from . import PRODUCER, REPO_ROOT, REVIEWER_ROLES


@dataclass(frozen=True)
class IdeaContext:
    ideas_dir: Path
    manifest: dict[str, Any]
    cards: list[dict[str, Any]]
    closest_checks: dict[str, dict[str, Any]]
    lineage: dict[str, Any]


@dataclass(frozen=True)
class ResearchPackContext:
    pack_dir: Path
    manifest: dict[str, Any]
    research_spec: dict[str, Any]
    selected_subdirection: dict[str, Any]
    gap_map: dict[str, Any]
    claim_graph: dict[str, Any]
    evidence_cards: list[dict[str, Any]]
    evidence_spans: list[dict[str, Any]]
    reviewer_notes: list[dict[str, Any]]
    paper_roles: dict[str, Any]
    roi_lens: dict[str, Any]
    broad_candidates: list[dict[str, str]]


def build_evidence_packages(
    *,
    ideas: Path,
    out: Path,
    pack: Path | None = None,
    max_ideas: int = 1,
    all_ideas: bool = False,
) -> dict[str, Any]:
    idea_ctx = load_idea_context(ideas)
    pack_ctx = load_research_pack(resolve_pack_dir(idea_ctx, pack))
    evidence_dir = out / "evidence_packages"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for stale in evidence_dir.glob("*.json"):
        stale.unlink()

    selected_cards = select_review_cards(idea_ctx.cards, max_ideas=max_ideas, all_ideas=all_ideas)
    packages: list[dict[str, Any]] = []
    artifacts: list[dict[str, str]] = []
    for card in selected_cards:
        package = build_package(card, idea_ctx, pack_ctx)
        path = evidence_dir / f"{card['idea_id']}.json"
        write_json(path, package)
        packages.append(package)
        artifacts.append(_artifact(out, f"evidence_package:{card['idea_id']}", path.relative_to(out)))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id(
            "review_package_manifest",
            {"idea_ids": [card["idea_id"] for card in selected_cards], "artifacts": artifacts},
        ),
        "created_at": utc_now(),
        "input_hash": input_hash({"ideas": str(idea_ctx.ideas_dir), "pack": str(pack_ctx.pack_dir)}),
        "parent_state_ids": [
            value
            for value in (
                idea_ctx.manifest.get("state_id"),
                pack_ctx.manifest.get("state_id"),
            )
            if value
        ],
        "producer": PRODUCER,
        "ideas_path": str(idea_ctx.ideas_dir),
        "research_pack_path": str(pack_ctx.pack_dir),
        "required_reviewer_roles": list(REVIEWER_ROLES),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "idea_ids": [card["idea_id"] for card in selected_cards],
        "review_queue_policy": {
            "default_external_review_idea_count": 1,
            "all_ideas_requested": all_ideas,
            "max_ideas": max_ideas,
            "selection_rule": "phase6_ready_then_experiment_ready_then_evidence_baseline_target_match",
        },
        "review_input_policy": _review_input_policy(),
    }
    write_json(out / "manifest.json", manifest)
    return {"manifest": manifest, "package_count": len(packages), "out": str(out)}


def select_review_cards(cards: list[dict[str, Any]], *, max_ideas: int = 1, all_ideas: bool = False) -> list[dict[str, Any]]:
    if all_ideas:
        return list(cards)
    limit = max(1, int(max_ideas or 1))
    ranked = sorted(cards, key=_review_card_sort_key)
    return ranked[:limit]


def _review_card_sort_key(card: dict[str, Any]) -> tuple[float, str]:
    text = " ".join(
        str(card.get(key, ""))
        for key in ("title", "primary_claim", "mechanism", "core_delta")
    ).lower()
    target_terms = ("action", "temporal", "coherence", "4d", "4dgs", "feed-forward", "feedforward", "real-time", "magnitude")
    target_score = sum(1 for term in target_terms if term in text)
    readiness = card.get("readiness", {}) if isinstance(card.get("readiness"), dict) else {}
    score = 0.0
    if card.get("status") == "phase6_ready":
        score += 100.0
    if readiness.get("experiment_blueprint_ready"):
        score += 30.0
    score += min(len(card.get("evidence_ids", [])), 10)
    score += min(len(card.get("direct_baselines", [])), 10)
    score += target_score * 3
    if "action-consistent" in text or ("action" in text and "coherence" in text):
        score += 12.0
    if "feed-forward" in text or "feedforward" in text:
        score += 8.0
    if "benchmark contract" in text or "benchmark/protocol" in text:
        score -= 25.0
    if "unknown_follow_up_required" in str(card.get("estimated_compute", "")):
        score -= 8.0
    if "high_requires_budget_gate" in str(card.get("estimated_compute", "")):
        score -= 15.0
    score -= len(card.get("duplicate_memory_matches", [])) * 50.0
    return (-score, str(card.get("idea_id", "")))


def load_idea_context(path: Path) -> IdeaContext:
    ideas_dir = path.resolve()
    if not ideas_dir.exists():
        raise FileNotFoundError(f"ideas directory does not exist: {ideas_dir}")
    required = (
        "manifest.json",
        "idea_cards.jsonl",
        "idea_lineage.json",
        "closest_work_checks.jsonl",
    )
    missing = [name for name in required if not (ideas_dir / name).exists()]
    if missing:
        raise FileNotFoundError("idea portfolio is incomplete: " + ", ".join(missing))
    checks = read_jsonl(ideas_dir / "closest_work_checks.jsonl")
    return IdeaContext(
        ideas_dir=ideas_dir,
        manifest=read_json(ideas_dir / "manifest.json"),
        cards=read_jsonl(ideas_dir / "idea_cards.jsonl"),
        closest_checks={check.get("idea_id", ""): check for check in checks if check.get("idea_id")},
        lineage=read_json(ideas_dir / "idea_lineage.json"),
    )


def resolve_pack_dir(idea_ctx: IdeaContext, pack: Path | None) -> Path:
    candidate = pack
    if candidate is None:
        raw = idea_ctx.manifest.get("research_pack_path")
        if not raw:
            raise FileNotFoundError("ideas manifest does not contain research_pack_path; pass --pack")
        candidate = Path(str(raw))
    candidate = candidate.resolve()
    return candidate if candidate.name == "research_pack" else candidate / "research_pack"


def load_research_pack(pack_dir: Path) -> ResearchPackContext:
    if not pack_dir.exists():
        raise FileNotFoundError(f"research_pack does not exist: {pack_dir}")
    required = (
        "manifest.json",
        "gap_map.json",
        "claim_graph.json",
        "evidence_cards.jsonl",
        "evidence_spans.jsonl",
        "reviewer_pressure_notes.jsonl",
        "paper_roles.json",
        "roi_lens.json",
    )
    missing = [name for name in required if not (pack_dir / name).exists()]
    if missing:
        raise FileNotFoundError("research_pack is incomplete: " + ", ".join(missing))
    return ResearchPackContext(
        pack_dir=pack_dir,
        manifest=read_json(pack_dir / "manifest.json"),
        research_spec=read_optional_json(pack_dir / "research_spec.json"),
        selected_subdirection=read_optional_json(pack_dir / "selected_subdirection.json"),
        gap_map=read_json(pack_dir / "gap_map.json"),
        claim_graph=read_json(pack_dir / "claim_graph.json"),
        evidence_cards=read_jsonl(pack_dir / "evidence_cards.jsonl"),
        evidence_spans=read_jsonl(pack_dir / "evidence_spans.jsonl"),
        reviewer_notes=read_jsonl(pack_dir / "reviewer_pressure_notes.jsonl"),
        paper_roles=read_json(pack_dir / "paper_roles.json"),
        roi_lens=read_json(pack_dir / "roi_lens.json"),
        broad_candidates=read_csv(pack_dir / "broad_candidates.csv"),
    )


def build_package(card: dict[str, Any], idea_ctx: IdeaContext, pack_ctx: ResearchPackContext) -> dict[str, Any]:
    idea_id = card["idea_id"]
    source_gap_ids = set(card.get("source_gap_ids", []))
    source_claim_ids = set(card.get("source_claim_ids", []))
    evidence_ids = set(card.get("evidence_ids", []))
    closest_work_ids = set(card.get("closest_work_ids", []))

    evidence_cards = [row for row in pack_ctx.evidence_cards if row.get("state_id") in evidence_ids]
    span_ids = {
        span_id
        for evidence_card in evidence_cards
        for span_id in evidence_card.get("evidence_span_ids", [])
        if isinstance(span_id, str)
    }
    evidence_spans = [row for row in pack_ctx.evidence_spans if row.get("state_id") in span_ids]
    source_gaps = [row for row in pack_ctx.gap_map.get("gaps", []) if row.get("gap_id") in source_gap_ids]
    source_claims = [row for row in pack_ctx.claim_graph.get("claims", []) if row.get("claim_id") in source_claim_ids]
    reviewer_notes = [row for row in pack_ctx.reviewer_notes if row.get("gap_id") in source_gap_ids]
    role_assignments = [
        row for row in pack_ctx.paper_roles.get("assignments", []) if row.get("paper_id") in closest_work_ids
    ]
    broad_candidates = [row for row in pack_ctx.broad_candidates if row.get("paper_id") in closest_work_ids]
    roi_entries = [row for row in pack_ctx.roi_lens.get("gap_roi", []) if row.get("gap_id") in source_gap_ids]
    package_input = {
        "idea_id": idea_id,
        "idea_hash": input_hash(card),
        "research_pack": pack_ctx.manifest.get("state_id", ""),
        "closest_work_ids": sorted(closest_work_ids),
    }
    package = {
        "schema_version": SCHEMA_VERSION,
        "package_id": make_state_id("evidence_package", package_input),
        "idea_id": idea_id,
        "created_at": card.get("created_at", utc_now()),
        "input_hash": input_hash(package_input),
        "parent_state_ids": [
            value
            for value in (
                card.get("state_id"),
                idea_ctx.manifest.get("state_id"),
                pack_ctx.manifest.get("state_id"),
            )
            if value
        ],
        "producer": PRODUCER,
        "review_input_policy": _review_input_policy(),
        "source_paths": {
            "ideas": _portable_path(idea_ctx.ideas_dir),
            "research_pack": _portable_path(pack_ctx.pack_dir),
        },
        "idea_card": card,
        "closest_work_check": idea_ctx.closest_checks.get(idea_id, {}),
        "research_spec": pack_ctx.research_spec,
        "selected_subdirection": pack_ctx.selected_subdirection,
        "source_gaps": source_gaps,
        "source_claims": source_claims,
        "evidence_cards": evidence_cards,
        "evidence_spans": evidence_spans,
        "roi_lens_entries": roi_entries,
        "reviewer_pressure_notes": reviewer_notes,
        "paper_role_assignments": role_assignments,
        "closest_work_papers": broad_candidates,
    }
    package["evidence_package_hash"] = input_hash(package)
    return package


def _review_input_policy() -> dict[str, Any]:
    return {
        "reviewer_reads_only_standard_evidence_package": True,
        "generator_persuasive_pitch_allowed": False,
        "excluded_inputs": [
            "idea_report.md",
            "strongest_rejection_cases.md",
            "cheapest_falsification.md",
            "chat_transcript",
        ],
        "decision_policy": "blocker_first_not_average_score",
    }


def _portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def read_optional_json(path: Path) -> dict[str, Any]:
    return read_json(path) if path.exists() else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"expected JSON object at {path}:{line_no}")
            rows.append(value)
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _artifact(root: Path, kind: str, rel_path: Path | str, schema: str = "") -> dict[str, str]:
    rel = Path(rel_path)
    payload = {"kind": kind, "path": rel.as_posix(), "sha256": sha256_file(root / rel)}
    if schema:
        payload["schema"] = schema
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build standard evidence packages for Phase 6 review.")
    parser.add_argument("--ideas", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--max-ideas", type=int, default=1)
    parser.add_argument("--all-ideas", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build_evidence_packages(
            ideas=args.ideas,
            out=args.out,
            pack=args.pack,
            max_ideas=args.max_ideas,
            all_ideas=args.all_ideas,
        )
    except Exception as exc:
        print(f"ERROR {exc}")
        return 1
    print(f"[review] built evidence_packages={result['package_count']} out={result['out']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
