from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now
from resmax_core.validators.validate_research_pack import run as validate_research_pack

from . import ALLOWED_GENERATION_SOURCES, PORTFOLIO_ARTIFACTS, PRODUCER, REPO_ROOT
from .closest_work_check import build_closest_work_check
from .lineage import build_lineage_graph, lineage_for_gap
from .load_pack import PackContext, resolve_pack_dir
from .render import render_reports


def generate_portfolio(*, pack: Path, out: Path, negative_memory: Path | None = None) -> dict[str, Any]:
    pack_dir = resolve_pack_dir(pack)
    validation_code = validate_research_pack(pack_dir / "manifest.json")
    if validation_code != 0:
        raise ValueError(f"input research_pack validator failed: {pack_dir}")
    ctx = PackContext.load(pack_dir)
    memory_path = negative_memory or REPO_ROOT / "resmax_memory" / "negative_memory.jsonl"
    memory_status, memories = _read_negative_memory(memory_path)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    trace: list[dict[str, Any]] = [
        _trace("generation_start", {"pack": str(pack_dir), "negative_memory": str(memory_path), "memory_status": memory_status})
    ]
    ideas = [_idea_from_gap(ctx, gap, memories) for gap in ctx.gaps]
    composite = _composite_benchmark_gated_idea(ctx, memories)
    if composite:
        ideas.insert(0, composite)
    checks = [build_closest_work_check(ctx, idea) for idea in ideas]
    lineage = build_lineage_graph(ideas)

    _write_jsonl(out / "idea_cards.jsonl", ideas)
    _write_jsonl(out / "closest_work_checks.jsonl", checks)
    _write_json(out / "idea_lineage.json", lineage)
    for idea in ideas:
        trace.append(_trace("candidate_created", {"idea_id": idea["idea_id"], "status": idea["status"]}))
    render_reports(out, ideas, checks)
    _write_jsonl(out / "generation_trace.jsonl", trace)

    manifest = _write_manifest(out, ctx, ideas, memory_status, memory_path)
    return {"ideas_dir": str(out), "idea_count": len(ideas), "phase6_ready": sum(1 for idea in ideas if idea["readiness"]["phase6_review_ready"]), "manifest": manifest}


def _idea_from_gap(ctx: PackContext, gap: dict[str, Any], memories: list[dict[str, Any]]) -> dict[str, Any]:
    gap_id = gap.get("gap_id", "")
    roi = ctx.roi_for_gap(gap_id)
    notes = ctx.reviewer_notes_for_gap(gap_id)
    source_claim_ids = [claim_id for claim_id in gap.get("supporting_claim_ids", []) if claim_id]
    evidence_ids = [card_id for card_id in gap.get("evidence_card_ids", []) if card_id]
    closest_work_ids = ctx.paper_ids_for_gap(gap) if evidence_ids else []
    direct_baselines = [paper_id for paper_id in closest_work_ids if "direct_baseline" in ctx.roles_for_paper(paper_id)]
    if not direct_baselines:
        direct_baselines = ctx.paper_ids_with_role(gap, "direct_baseline")[:6]
    direct_baselines = _relevant_editing_papers(ctx, direct_baselines)
    method_donors = [paper_id for paper_id in closest_work_ids if "method_donor" in ctx.roles_for_paper(paper_id)]
    if not method_donors:
        method_donors = ctx.paper_ids_with_role(gap, "method_donor")[:6]
    method_donors = _relevant_editing_papers(ctx, method_donors)
    benchmark_opportunities = [paper_id for paper_id in closest_work_ids if "benchmark_opportunity" in ctx.roles_for_paper(paper_id)]
    if not benchmark_opportunities:
        benchmark_opportunities = ctx.paper_ids_with_role(gap, "benchmark_opportunity")[:6]
    benchmark_opportunities = _relevant_editing_papers(ctx, benchmark_opportunities)
    generation_sources = _generation_sources(gap, notes, method_donors, benchmark_opportunities)
    reviewer_attack_points = _reviewer_attack_points(notes, roi)
    duplicate_matches = _duplicate_matches(gap, roi, memories)

    status, readiness = _status_and_readiness(
        source_gap_ids=[gap_id] if gap_id else [],
        evidence_ids=evidence_ids,
        closest_work_ids=closest_work_ids,
        direct_baselines=direct_baselines,
        duplicate_matches=duplicate_matches,
    )
    title = _title(ctx, gap)
    primary_claim = _primary_claim(ctx, gap, roi, status, direct_baselines, benchmark_opportunities)
    idea_input = {
        "gap_id": gap_id,
        "claim_ids": source_claim_ids,
        "evidence_ids": evidence_ids,
        "closest_work_ids": closest_work_ids,
        "status": status,
        "generation_sources": generation_sources,
    }
    idea_id = make_state_id("idea", idea_input)
    lineage = lineage_for_gap(gap, status)
    if duplicate_matches:
        lineage["parent_idea_ids"] = [match.get("subject_id", "") for match in duplicate_matches if match.get("subject_id")]

    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("idea_card", idea_input),
        "created_at": utc_now(),
        "input_hash": input_hash(idea_input),
        "parent_state_ids": [item for item in [ctx.gap_map.get("state_id"), ctx.roi_lens.get("state_id"), gap_id] if item],
        "producer": PRODUCER,
        "idea_id": idea_id,
        "title": title,
        "source_gap_ids": [gap_id] if gap_id else [],
        "source_claim_ids": source_claim_ids,
        "evidence_ids": evidence_ids,
        "closest_work_ids": closest_work_ids,
        "generation_sources": generation_sources,
        "core_delta": _core_delta(ctx, gap, closest_work_ids),
        "primary_claim": primary_claim,
        "mechanism": _mechanism(ctx, gap, method_donors, benchmark_opportunities, direct_baselines),
        "why_now": _why_now(roi),
        "direct_baselines": direct_baselines,
        "method_donors": method_donors,
        "benchmark_opportunities": benchmark_opportunities,
        "estimated_compute": _estimate_compute(ctx, roi),
        "estimated_timeline": _estimate_timeline(ctx, roi, evidence_ids),
        "expected_failure_modes": _expected_failure_modes(gap, roi, reviewer_attack_points, duplicate_matches),
        "reviewer_attack_points": reviewer_attack_points,
        "strongest_rejection_case": _strongest_rejection_case(gap, roi, reviewer_attack_points, evidence_ids, closest_work_ids),
        "cheapest_falsification": _cheapest_falsification(ctx, gap, primary_claim, direct_baselines, benchmark_opportunities, roi),
        "lineage": lineage,
        "roi": _compact_roi(roi),
        "duplicate_memory_matches": _memory_refs(duplicate_matches),
        "readiness": readiness,
        "status": status,
    }


def _composite_benchmark_gated_idea(ctx: PackContext, memories: list[dict[str, Any]]) -> dict[str, Any] | None:
    method_gap = _first_gap(ctx, ("temporal_action_coherence", "feedforward_native_gaussian_editing"))
    benchmark_gap = _first_gap(ctx, ("benchmark_protocol_gap",))
    if not method_gap or not benchmark_gap:
        return None
    gaps = [method_gap]
    feedforward_gap = _first_gap(ctx, ("feedforward_native_gaussian_editing",))
    if feedforward_gap and feedforward_gap.get("gap_id") != method_gap.get("gap_id"):
        gaps.append(feedforward_gap)
    gaps.append(benchmark_gap)

    source_gap_ids = _dedupe([gap.get("gap_id", "") for gap in gaps if gap.get("gap_id")])
    source_claim_ids = _dedupe([claim_id for gap in gaps for claim_id in gap.get("supporting_claim_ids", []) if claim_id])
    raw_evidence_ids = _dedupe([card_id for gap in gaps for card_id in gap.get("evidence_card_ids", []) if card_id])
    closest_work_ids = _dedupe([paper_id for gap in gaps for paper_id in ctx.paper_ids_for_gap(gap)])
    closest_work_ids = _relevant_editing_papers(ctx, closest_work_ids)[:12]
    evidence_ids = [card_id for card_id in raw_evidence_ids if ctx.paper_id_for_card(card_id) in set(closest_work_ids)][:16]
    direct_fallback = _relevant_editing_papers(
        ctx,
        [paper_id for paper_id in closest_work_ids if "direct_baseline" in ctx.roles_for_paper(paper_id)]
        or ctx.paper_ids_with_role(method_gap, "direct_baseline"),
    )
    direct_baselines = _preferred_papers(
        ctx,
        [
            "efficient dynamic scene editing",
            "dreammotion",
            "chronoedit",
            "adapedit",
            "learning action and reasoning-centric image editing",
            "splatflow",
        ],
        [],
    ) or direct_fallback
    direct_baselines = direct_baselines[:8]
    method_donors = _preferred_papers(
        ctx,
        [
            "dynamic-editor",
            "dynamic-editor:",
            "dynamic-editor training-free",
            "instruct 4d-to-4d",
            "sketchfacegs",
            "real-time 3d-aware portrait editing",
            "splatflow",
        ],
        _relevant_editing_papers(
            ctx,
            [paper_id for paper_id in closest_work_ids if "method_donor" in ctx.roles_for_paper(paper_id)]
            or ctx.paper_ids_with_role(method_gap, "method_donor"),
        ),
    )[:8]
    benchmark_opportunities = _preferred_papers(
        ctx,
        [
            "egoedit",
            "chronoedit",
            "dynamic-editor",
            "instruct 4d-to-4d",
            "learning action and reasoning-centric image editing",
        ],
        _relevant_editing_papers(
            ctx,
            [paper_id for paper_id in closest_work_ids if "benchmark_opportunity" in ctx.roles_for_paper(paper_id)]
            or ctx.paper_ids_with_role(benchmark_gap, "benchmark_opportunity"),
        ),
    )[:8]
    roi = _merge_roi_entries([ctx.roi_for_gap(gap_id) for gap_id in source_gap_ids])
    roi = _scope_roi_to_papers(roi, _dedupe(direct_baselines + benchmark_opportunities + method_donors))
    notes = [note for gap_id in source_gap_ids for note in ctx.reviewer_notes_for_gap(gap_id)]
    reviewer_attack_points = _reviewer_attack_points(notes, roi)
    synthetic_gap = {
        "gap_id": "+".join(source_gap_ids),
        "gap_type": "protocol_locked_action_basis_method",
        "description": (
            "Lock a concrete action-edit benchmark contract, then test a feed-forward low-rank action-basis editor over native "
            "4D Gaussian trajectories instead of relying on unconstrained per-frame diffusion pseudo-pairs."
        ),
        "roi_signals": {
            "unknowns": [item.get("field", "") for item in roi.get("unknowns", []) if isinstance(item, dict)],
        },
    }
    duplicate_matches = _duplicate_matches(synthetic_gap, roi, memories)
    status, readiness = _status_and_readiness(
        source_gap_ids=source_gap_ids,
        evidence_ids=evidence_ids,
        closest_work_ids=closest_work_ids,
        direct_baselines=direct_baselines,
        duplicate_matches=duplicate_matches,
    )
    idea_input = {
        "gap_ids": source_gap_ids,
        "claim_ids": source_claim_ids,
        "evidence_ids": evidence_ids,
        "closest_work_ids": closest_work_ids,
        "status": status,
        "variant": "protocol_locked_action_basis_method",
    }
    primary_claim = (
        f"Under {_constraint_text(ctx)}, a protocol-locked feed-forward 4D Gaussian action-basis editor can test whether native "
        "Gaussian trajectory bases improve action-edit success and temporal/multi-view coherence over the reproducible baselines "
        f"{_paper_title_list(ctx, direct_baselines, limit=8) or 'the closest runnable 4D/video editing baselines'} on a fixed 36-case action-edit suite."
    )
    lineage = {
        "parent_gap_ids": source_gap_ids,
        "parent_idea_ids": [match.get("subject_id", "") for match in duplicate_matches if match.get("subject_id")],
        "mutation_operator": "replace_bare_feedforward_with_protocol_locked_action_basis",
        "mutation_reason": "Phase 6 blockers require a concrete assay and a sharper technical delta than generic feed-forward Gaussian deltas.",
        "status": "proceed" if status == "phase6_ready" else "refine",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("idea_card", idea_input),
        "created_at": utc_now(),
        "input_hash": input_hash(idea_input),
        "parent_state_ids": [item for item in [ctx.gap_map.get("state_id"), ctx.roi_lens.get("state_id"), *source_gap_ids] if item],
        "producer": PRODUCER,
        "idea_id": make_state_id("idea", idea_input),
        "title": "Protocol-locked action-basis 4D Gaussian editing",
        "source_gap_ids": source_gap_ids,
        "source_claim_ids": source_claim_ids,
        "evidence_ids": evidence_ids,
        "closest_work_ids": closest_work_ids,
        "generation_sources": _dedupe(["gap_driven", "reviewer_pressure_driven", "benchmark_blindspot_driven", "method_transfer_driven"]),
        "core_delta": (
            "Replace an unconstrained feed-forward Gaussian delta field with a low-rank action basis learned from native 4DGS "
            "temporal trajectories. The method predicts basis coefficients and masked residuals, so the edit is tied to persistent "
            "Gaussian motion modes rather than frame-wise diffusion artifacts."
        ),
        "primary_claim": primary_claim,
        "mechanism": (
            "Stage A freezes a 36-case protocol before training: six scene ids (coffee_martini, cook_spinach, cut_roasted_beef, "
            "flame_salmon, flame_steak, sear_steak), two action families per scene (pose/contact change and trajectory/magnitude "
            "change), and small/medium/large magnitude bins. Required metric formulas are fixed: action_success is normalized "
            "video-text action score against the target prompt, temporal_lpips is mean LPIPS between frame t and optical-flow-warped "
            "frame t-1, xview_error is mean depth/feature reprojection error across camera pairs, gaussian_identity_drift is median "
            "canonical per-Gaussian displacement outside the edited action mask divided by scene diagonal, and latency is seconds/edit. "
            "Stage B extracts a "
            "low-rank temporal action basis from each source 4DGS by factorizing per-primitive position, scale, rotation, opacity, "
            "and color trajectories. Stage C trains a feed-forward coefficient head plus sparse residual mask; it does not use "
            "diffusion-edited frames as supervised targets. Stage D reports reproducible baseline tiers: runnable baselines are "
            "reproduced, paper-only 2026 systems are used only as stress-test anchors, and promotion is blocked if the protocol audit fails."
        ),
        "why_now": _why_now(roi),
        "direct_baselines": direct_baselines,
        "method_donors": method_donors,
        "benchmark_opportunities": benchmark_opportunities,
        "estimated_compute": _estimate_compute(ctx, roi),
        "estimated_timeline": _estimate_timeline(ctx, roi, evidence_ids),
        "expected_failure_modes": _expected_failure_modes(synthetic_gap, roi, reviewer_attack_points, duplicate_matches),
        "reviewer_attack_points": reviewer_attack_points,
        "strongest_rejection_case": (
            "Reject if the 36-case protocol cannot name runnable baselines, scene ids, formulas for all metrics, and stop conditions before "
            "the action-basis coefficient head is trained."
        ),
        "cheapest_falsification": {
            "claim_to_falsify": primary_claim,
            "minimal_test": (
                "Day 1 locks the 36-case suite and verifies runnable baselines. Day 2 implements metric scripts: action success, "
                "warped temporal LPIPS, cross-view reprojection error, Gaussian identity drift, and latency. Days 3-5 train only "
                "the coefficient head on 4 scenes and compare against the runnable baseline tier."
            ),
            "falsifies_if": (
                "The audit cannot reproduce at least three relevant baselines, any metric lacks a deterministic script, or the "
                "action-basis editor fails to improve action success without temporal/multi-view coherence regression."
            ),
            "required_baseline_ids": direct_baselines,
            "expected_cost": _estimate_compute(ctx, roi),
        },
        "lineage": lineage,
        "roi": _compact_roi(roi),
        "duplicate_memory_matches": _memory_refs(duplicate_matches),
        "readiness": readiness,
        "status": status,
    }


def _first_gap(ctx: PackContext, gap_types: tuple[str, ...]) -> dict[str, Any] | None:
    wanted = set(gap_types)
    return next((gap for gap in ctx.gaps if gap.get("gap_type") in wanted), None)


def _merge_roi_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    entries = [entry for entry in entries if isinstance(entry, dict) and entry]
    if not entries:
        return {}
    positive: dict[str, Any] = {}
    difficulty: dict[str, Any] = {}
    unknowns: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for entry in entries:
        positive.update(entry.get("positive_signals", {}))
        difficulty.update(entry.get("difficulty_signals", {}))
        unknowns.extend(item for item in entry.get("unknowns", []) if isinstance(item, dict))
        blockers.extend(item for item in entry.get("reviewer_blockers", []) if isinstance(item, dict))
    return {
        "positive_signals": positive,
        "difficulty_signals": difficulty,
        "unknowns": _dedupe_dicts(unknowns, "field"),
        "reviewer_blockers": _dedupe_dicts(blockers, "note_id"),
        "confidence": "low" if any(entry.get("confidence") == "low" for entry in entries) else entries[0].get("confidence", "unknown"),
    }


def _scope_roi_to_papers(roi: dict[str, Any], paper_ids: list[str]) -> dict[str, Any]:
    scoped = dict(roi)
    target = ",".join(paper_ids[:10])
    unknowns: list[dict[str, Any]] = []
    for item in roi.get("unknowns", []):
        if not isinstance(item, dict):
            continue
        value = dict(item)
        field = value.get("field", "unknown")
        if target:
            value["follow_up_retrieval_target"] = f"resolve {field} for scoped idea papers: {target}"
        unknowns.append(value)
    scoped["unknowns"] = _dedupe_dicts(unknowns, "field")
    return scoped


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _dedupe_dicts(values: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for value in values:
        token = str(value.get(key, "")) or json.dumps(value, sort_keys=True)
        if token in seen:
            continue
        seen.add(token)
        out.append(value)
    return out


def _preferred_papers(ctx: PackContext, title_phrases: list[str], fallback: list[str]) -> list[str]:
    out: list[str] = []
    all_ids = _dedupe([row.get("paper_id", "") for row in ctx.broad_candidates] + [row.get("paper_id", "") for row in ctx.role_assignments])
    for phrase in title_phrases:
        needle = phrase.lower()
        for paper_id in all_ids:
            if paper_id in out:
                continue
            title = ctx.title_for_paper(paper_id).lower()
            if needle in title:
                out.append(paper_id)
                break
    return _dedupe(out + fallback)


def _relevant_editing_papers(ctx: PackContext, paper_ids: list[str]) -> list[str]:
    out: list[str] = []
    for paper_id in _dedupe(paper_ids):
        title = ctx.title_for_paper(paper_id).lower()
        has_edit = any(term in title for term in ("edit", "editing", "editor", "manipulation", "customization"))
        has_domain = any(term in title for term in ("4d", "gaussian", "splat", "video", "dynamic", "motion", "temporal", "scene", "action", "3d"))
        if has_edit and has_domain:
            out.append(paper_id)
    return out or _dedupe(paper_ids)


def _generation_sources(
    gap: dict[str, Any],
    notes: list[dict[str, Any]],
    method_donors: list[str],
    benchmark_opportunities: list[str],
) -> list[str]:
    sources = ["gap_driven"]
    if notes:
        sources.append("reviewer_pressure_driven")
    if gap.get("gap_type") == "benchmark_blind_spot" or benchmark_opportunities:
        sources.append("benchmark_blindspot_driven")
    if gap.get("gap_type") == "method_transfer" or method_donors:
        sources.append("method_transfer_driven")
    return [source for source in sources if source in ALLOWED_GENERATION_SOURCES]


def _status_and_readiness(
    *,
    source_gap_ids: list[str],
    evidence_ids: list[str],
    closest_work_ids: list[str],
    direct_baselines: list[str],
    duplicate_matches: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    reasons: list[str] = []
    if not source_gap_ids:
        reasons.append("missing_source_gap_ids")
    if not evidence_ids:
        reasons.append("missing_evidence_ids")
    if not closest_work_ids:
        reasons.append("missing_closest_work")
    if not direct_baselines:
        reasons.append("missing_direct_baseline_for_experiment")
    if duplicate_matches:
        reasons.append("duplicate_negative_memory_match")

    phase6_ready = bool(source_gap_ids and evidence_ids and closest_work_ids and not duplicate_matches)
    experiment_ready = bool(phase6_ready and direct_baselines)
    if not source_gap_ids or not evidence_ids:
        status = "insufficient_evidence"
    elif duplicate_matches:
        status = "duplicate_risk"
    elif not closest_work_ids:
        status = "not_ready_for_phase6"
    elif not direct_baselines:
        status = "not_ready_for_experiment"
    else:
        status = "phase6_ready"
    return status, {
        "phase6_review_ready": phase6_ready,
        "experiment_blueprint_ready": experiment_ready,
        "not_ready_reasons": reasons,
    }


def _title(ctx: PackContext, gap: dict[str, Any]) -> str:
    gap_type = gap.get("gap_type", "gap")
    if gap_type == "temporal_action_coherence":
        return "Action-consistent feed-forward 4D Gaussian editing"
    if gap_type == "feedforward_native_gaussian_editing":
        return "Native feed-forward Gaussian edit field for real-time 4DGS changes"
    if gap_type == "large_magnitude_editing":
        return "Magnitude-scaled action editing with explicit failure boundary"
    if gap_type == "benchmark_protocol_gap":
        return "Reviewer-proof action-editing benchmark contract for 4DGS"
    if gap_type == "resource_arbitrage":
        return "Bounded-budget 4DGS editing under explicit runtime and baseline constraints"
    label = gap_type.replace("_", " ")
    scope = ctx.selected_subdirection.get("label") or gap.get("scope", "selected subdirection").replace("_", " ")
    return f"{label.title()} candidate for {scope}"


def _core_delta(ctx: PackContext, gap: dict[str, Any], closest_work_ids: list[str]) -> str:
    if not closest_work_ids:
        return "No closest-work delta is claimed because the gap lacks evidence-grounded closest work."
    titles = _paper_title_list(ctx, closest_work_ids)
    gap_type = gap.get("gap_type", "")
    if gap_type == "temporal_action_coherence":
        return (
            f"Compared with {titles}, claim the delta only if a native 4D Gaussian edit field changes the requested action "
            "while preserving cross-time Gaussian identity and view consistency under the same benchmark budget."
        )
    if gap_type == "feedforward_native_gaussian_editing":
        return (
            f"Compared with {titles}, replace per-scene or per-view optimization with one feed-forward prediction of Gaussian "
            "attribute deltas and require the runtime/quality tradeoff to survive direct baseline reproduction."
        )
    if gap_type == "large_magnitude_editing":
        return (
            f"Compared with {titles}, make edit magnitude an explicit independent variable and report where action success, "
            "identity, geometry, and temporal coherence first fail."
        )
    if gap_type == "benchmark_protocol_gap":
        return (
            f"Compared with {titles}, the contribution is not a new model yet; it is a minimal benchmark and baseline contract "
            "that must close reviewer pressure before any method claim is promoted."
        )
    return (
        f"Compared with {titles}, focus the gap on {gap.get('description', '').rstrip('.')} "
        "and require the remaining difference to be verified by Phase 6 reviewers."
    )


def _primary_claim(
    ctx: PackContext,
    gap: dict[str, Any],
    roi: dict[str, Any],
    status: str,
    direct_baselines: list[str],
    benchmark_opportunities: list[str],
) -> str:
    if status == "insufficient_evidence":
        return "No research claim is recommended until the cited gap has direct evidence_ids."
    constraints = _constraint_text(ctx)
    baselines = _paper_title_list(ctx, direct_baselines, limit=3) or "the closest reproduced baseline"
    benchmarks = _paper_title_list(ctx, benchmark_opportunities, limit=3) or "the selected benchmark anchors"
    gap_type = gap.get("gap_type", "")
    if gap_type == "temporal_action_coherence":
        return (
            f"Under {constraints}, a feed-forward 4D Gaussian edit field can improve action-edit success and temporal/action "
            f"coherence on {benchmarks} over {baselines}, while preserving a bounded runtime budget."
        )
    if gap_type == "feedforward_native_gaussian_editing":
        return (
            f"Under {constraints}, native prediction of per-Gaussian position, rotation, scale, opacity, and color deltas can "
            f"match or beat optimization-based Gaussian editing baselines ({baselines}) with lower edit latency."
        )
    if gap_type == "large_magnitude_editing":
        return (
            f"Under {constraints}, magnitude-conditioned action edits can extend the achievable action-change range over "
            f"{baselines} before temporal or identity collapse, measured on {benchmarks}."
        )
    if gap_type == "benchmark_protocol_gap":
        return (
            f"Under {constraints}, a reviewer-proof 4DGS action-editing protocol can turn known baseline/dataset objections "
            f"into must-run comparisons, metrics, and stop conditions before any model claim is made."
        )
    positive = _dimension_value(roi.get("positive_signals", {}), "information_gap")
    difficulty = _dimension_value(roi.get("difficulty_signals", {}), "compute_cost")
    return (
        f"A candidate built around {gap_type or 'the gap'} may convert the documented gap into a testable contribution "
        f"when information_gap={positive} and compute_cost={difficulty} are explicitly controlled."
    )


def _mechanism(
    ctx: PackContext,
    gap: dict[str, Any],
    method_donors: list[str],
    benchmark_opportunities: list[str],
    direct_baselines: list[str],
) -> str:
    donors = _paper_title_list(ctx, method_donors, limit=4) or "the method donors in the ResearchPack"
    benchmarks = _paper_title_list(ctx, benchmark_opportunities, limit=4) or "the benchmark anchors in the ResearchPack"
    baselines = _paper_title_list(ctx, direct_baselines, limit=4) or "the closest direct baselines"
    gap_type = gap.get("gap_type", "")
    if gap_type == "temporal_action_coherence":
        return (
            "Represent the edit as a sparse action-conditioned Gaussian delta field over persistent primitive ids. "
            "A feed-forward predictor proposes per-primitive deltas, a temporal identity gate suppresses deltas that break "
            "cross-frame correspondence, and a view-consistency loss rejects edits that only work in a single rendered view. "
            f"Method donors: {donors}. Must-run baselines: {baselines}. Benchmark anchors: {benchmarks}."
        )
    if gap_type == "feedforward_native_gaussian_editing":
        return (
            "Train a lightweight variation head that maps instruction/video-action features and current Gaussian attributes "
            "to native Gaussian deltas in one pass, with an optional refinement step only for failed large changes. "
            f"Method donors: {donors}. Must-run baselines: {baselines}. Benchmark anchors: {benchmarks}."
        )
    if gap_type == "large_magnitude_editing":
        return (
            "Expose edit magnitude as a controlled conditioning variable, evaluate small/medium/large action changes, and "
            "use a failure detector for identity drift, geometry collapse, and temporal inconsistency. "
            f"Method donors: {donors}. Must-run baselines: {baselines}. Benchmark anchors: {benchmarks}."
        )
    if gap_type == "benchmark_protocol_gap":
        return (
            "Before model investment, compile a minimal reviewer-pressure protocol: direct baselines, dataset coverage, action "
            "success metrics, temporal coherence metrics, magnitude buckets, and ablations. "
            f"Must-run baselines: {baselines}. Benchmark anchors: {benchmarks}."
        )
    return (
        f"Use the gap type `{gap_type or 'unknown'}` as the design constraint, borrow mechanisms from {donors}, "
        f"and test against benchmark anchors from {benchmarks}."
    )


def _why_now(roi: dict[str, Any]) -> str:
    positives = roi.get("positive_signals", {}) if isinstance(roi, dict) else {}
    parts = [
        f"{name}={payload.get('value', 'unknown')}"
        for name, payload in positives.items()
        if isinstance(payload, dict) and payload.get("value") in {"medium", "high"}
    ]
    return "Phase 4 ROI lens exposes timely positive signals: " + (", ".join(parts) if parts else "none above unknown")


def _estimate_compute(ctx: PackContext, roi: dict[str, Any]) -> str:
    budget = str(ctx.research_spec.get("compute_budget", "") or "").strip()
    timeline = str(ctx.research_spec.get("timeline", "") or "").strip()
    if budget and budget != "unknown":
        suffix = f"{budget}" + (f"_{timeline}" if timeline and timeline != "unknown" else "")
        return "bounded_minimal_falsification_" + _slug(suffix)
    value = _dimension_value(roi.get("difficulty_signals", {}), "compute_cost")
    return {
        "low": "low_existing_code_path",
        "medium": "medium_single_lab_iteration",
        "high": "high_requires_budget_gate",
        "unknown": "unknown_follow_up_required",
    }.get(value, "unknown_follow_up_required")


def _estimate_timeline(ctx: PackContext, roi: dict[str, Any], evidence_ids: list[str]) -> str:
    timeline = str(ctx.research_spec.get("timeline", "") or "").strip()
    if timeline and timeline != "unknown" and evidence_ids:
        return f"bounded_{_slug(timeline)}_minimal_falsification_first"
    value = _dimension_value(roi.get("difficulty_signals", {}), "timeline_risk")
    if not evidence_ids:
        return "blocked_until_evidence_recovered"
    return {
        "low": "short_minimal_falsification_first",
        "medium": "medium_requires_baseline_audit",
        "high": "long_not_phase5_ready",
        "unknown": "unknown_follow_up_required",
    }.get(value, "unknown_follow_up_required")


def _reviewer_attack_points(notes: list[dict[str, Any]], roi: dict[str, Any]) -> list[dict[str, str]]:
    attacks = [
        {
            "note_id": note.get("note_id", ""),
            "objection_type": note.get("objection_type", "unknown"),
            "severity": note.get("severity", "unknown"),
            "summary": note.get("objection_text", "")[:240],
        }
        for note in notes
    ]
    if attacks:
        return attacks
    return [
        {
            "note_id": blocker.get("note_id", ""),
            "objection_type": blocker.get("objection_type", "unknown"),
            "severity": blocker.get("severity", "unknown"),
            "summary": "ROI lens reviewer blocker without expanded note text.",
        }
        for blocker in roi.get("reviewer_blockers", [])
        if isinstance(blocker, dict)
    ]


def _expected_failure_modes(
    gap: dict[str, Any],
    roi: dict[str, Any],
    reviewer_attack_points: list[dict[str, str]],
    duplicate_matches: list[dict[str, Any]],
) -> list[str]:
    modes = [f"Gap remains unresolved: {gap.get('description', '')}"]
    modes.extend(f"Unknown {item.get('field', 'field')}: {item.get('follow_up_retrieval_target', '')}" for item in roi.get("unknowns", []))
    modes.extend(f"Reviewer may attack {point.get('objection_type', 'unknown')}" for point in reviewer_attack_points)
    if duplicate_matches:
        modes.append("Negative memory marks a similar killed idea; explain a concrete difference before review.")
    return [mode for mode in modes if mode]


def _strongest_rejection_case(
    gap: dict[str, Any],
    roi: dict[str, Any],
    reviewer_attack_points: list[dict[str, str]],
    evidence_ids: list[str],
    closest_work_ids: list[str],
) -> str:
    if not evidence_ids:
        return "Reject for Phase 6: the candidate has no direct evidence_ids from gap_map."
    if not closest_work_ids:
        return "Reject for Phase 6: closest work is missing, so novelty proximity cannot be checked."
    high_attack = next((point for point in reviewer_attack_points if point.get("severity") == "high"), None)
    if high_attack:
        return f"Reviewer blocker `{high_attack['objection_type']}` is high severity and must be neutralized first."
    unknowns = roi.get("unknowns", [])
    if unknowns:
        return f"ROI unknown `{unknowns[0].get('field', 'unknown')}` may collapse the story if not resolved."
    return f"Closest work may already cover the gap: {gap.get('description', '')}"


def _cheapest_falsification(
    ctx: PackContext,
    gap: dict[str, Any],
    primary_claim: str,
    direct_baselines: list[str],
    benchmark_opportunities: list[str],
    roi: dict[str, Any],
) -> dict[str, Any]:
    unknown_targets = [item.get("follow_up_retrieval_target", "") for item in roi.get("unknowns", []) if item.get("follow_up_retrieval_target")]
    baseline_text = _paper_title_list(ctx, direct_baselines, limit=3) or "the closest direct baseline"
    benchmark_text = _paper_title_list(ctx, benchmark_opportunities, limit=3) or "one selected benchmark anchor"
    gap_type = gap.get("gap_type", "")
    if gap_type == "temporal_action_coherence":
        minimal_test = (
            f"Run a 12-action mini-suite on {benchmark_text} against {baseline_text}; report action success, temporal "
            "warp/LPIPS consistency, Gaussian identity drift, and edit latency."
        )
        falsifies_if = "No action-success gain remains, or temporal/action coherence drops by more than 10% versus the best baseline."
    elif gap_type == "feedforward_native_gaussian_editing":
        minimal_test = (
            f"Reproduce {baseline_text}, then compare one-pass native Gaussian delta prediction on the same scenes and prompts; "
            "measure edit latency, multi-view consistency, and quality."
        )
        falsifies_if = "Latency is not lower at matched quality, or the feed-forward branch fails the closest-work reproduction check."
    elif gap_type == "large_magnitude_editing":
        minimal_test = (
            f"Bucket edits into small/medium/large action-change magnitudes on {benchmark_text}; compare failure boundary "
            f"against {baseline_text}."
        )
        falsifies_if = "The large-change bucket does not improve before identity, geometry, or temporal coherence failure."
    elif gap_type == "benchmark_protocol_gap":
        minimal_test = (
            f"Audit {baseline_text} and {benchmark_text}; produce the must-run baseline list, dataset split, metrics, "
            "ablation table, and reviewer-objection checklist before model training."
        )
        falsifies_if = "The audit cannot define at least one direct baseline, one dataset/protocol, and one primary metric."
    else:
        minimal_test = unknown_targets[0] if unknown_targets else "Run a one-benchmark ablation against the closest direct baseline."
        falsifies_if = "No measurable delta remains after controlling the closest work, baseline burden, and compute cost."
    return {
        "claim_to_falsify": primary_claim,
        "minimal_test": minimal_test,
        "falsifies_if": falsifies_if,
        "required_baseline_ids": direct_baselines,
        "expected_cost": _estimate_compute(ctx, roi),
    }


def _compact_roi(roi: dict[str, Any]) -> dict[str, Any]:
    return {
        "positive_signals": roi.get("positive_signals", {}),
        "difficulty_signals": roi.get("difficulty_signals", {}),
        "unknowns": roi.get("unknowns", []),
        "reviewer_blockers": roi.get("reviewer_blockers", []),
        "confidence": roi.get("confidence", "unknown"),
    }


def _duplicate_matches(gap: dict[str, Any], roi: dict[str, Any], memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not memories:
        return []
    target_text = " ".join(
        [
            gap.get("gap_type", ""),
            gap.get("description", ""),
            " ".join(item.get("field", "") for item in roi.get("unknowns", []) if isinstance(item, dict)),
        ]
    )
    matches: list[dict[str, Any]] = []
    for memory in memories:
        if memory.get("subject_type") != "idea" or memory.get("decision_status") not in {"killed", "rejected"}:
            continue
        score = _token_overlap(target_text, memory.get("reason", ""))
        if score >= 0.28:
            matches.append({**memory, "similarity": score})
    return matches


def _memory_refs(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "memory_id": match.get("memory_id", ""),
            "subject_id": match.get("subject_id", ""),
            "reason": match.get("reason", ""),
            "similarity": round(float(match.get("similarity", 0.0)), 3),
        }
        for match in matches
    ]


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _tokens(text: str) -> set[str]:
    stop = {"the", "and", "with", "from", "into", "that", "this", "must", "before", "after", "idea"}
    return {token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(token) > 2 and token not in stop}


def _dimension_value(dimensions: dict[str, Any], name: str) -> str:
    payload = dimensions.get(name, {}) if isinstance(dimensions, dict) else {}
    return payload.get("value", "unknown") if isinstance(payload, dict) else "unknown"


def _paper_title_list(ctx: PackContext, paper_ids: list[str], *, limit: int = 4) -> str:
    titles = [ctx.title_for_paper(paper_id) for paper_id in paper_ids[:limit] if paper_id]
    if len(paper_ids) > limit:
        titles.append(f"{len(paper_ids) - limit} additional listed baselines")
    return ", ".join(titles)


def _constraint_text(ctx: PackContext) -> str:
    parts = []
    for key, label in (("target_venue", "target"), ("compute_budget", "compute"), ("timeline", "timeline")):
        value = str(ctx.research_spec.get(key, "") or "").strip()
        if value and value != "unknown":
            parts.append(f"{label}={value}")
    return ", ".join(parts) if parts else "the stated Resmax constraints"


def _slug(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower())).strip("_") or "unknown"


def _read_negative_memory(path: Path) -> tuple[str, list[dict[str, Any]]]:
    if not path.exists():
        return "not_found", []
    memories: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                value = json.loads(raw)
                if isinstance(value, dict):
                    memories.append(value)
    return "loaded", memories


def _trace(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "event_type": event_type,
        "producer": PRODUCER,
        "payload": payload,
    }


def _write_manifest(
    out_dir: Path,
    ctx: PackContext,
    ideas: list[dict[str, Any]],
    memory_status: str,
    memory_path: Path,
) -> dict[str, Any]:
    artifacts = [
        _artifact(out_dir, "idea_cards", "idea_cards.jsonl", "idea_card.schema.json"),
        _artifact(out_dir, "idea_lineage", "idea_lineage.json"),
        _artifact(out_dir, "closest_work_checks", "closest_work_checks.jsonl"),
        _artifact(out_dir, "strongest_rejection_cases", "strongest_rejection_cases.md"),
        _artifact(out_dir, "cheapest_falsification", "cheapest_falsification.md"),
        _artifact(out_dir, "generation_trace", "generation_trace.jsonl"),
        _artifact(out_dir, "idea_report", "idea_report.md"),
    ]
    manifest_input = {
        "research_pack": ctx.manifest.get("state_id", ""),
        "idea_ids": [idea["idea_id"] for idea in ideas],
        "artifact_hashes": [artifact["sha256"] for artifact in artifacts],
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("idea_portfolio", manifest_input),
        "created_at": utc_now(),
        "input_hash": input_hash(manifest_input),
        "parent_state_ids": [item for item in [ctx.manifest.get("state_id"), ctx.gap_map.get("state_id")] if item],
        "producer": PRODUCER,
        "portfolio_id": f"idea_portfolio/{ctx.selected_subdirection.get('selected_subdirection_id', 'unknown')}",
        "research_pack_path": str(ctx.pack_dir),
        "source_index": ctx.source_index,
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "candidate_counts": {
            "total": len(ideas),
            "phase6_ready": sum(1 for idea in ideas if idea["readiness"]["phase6_review_ready"]),
            "experiment_blueprint_ready": sum(1 for idea in ideas if idea["readiness"]["experiment_blueprint_ready"]),
            "insufficient_evidence": sum(1 for idea in ideas if idea["status"] == "insufficient_evidence"),
            "duplicate_risk": sum(1 for idea in ideas if idea["status"] == "duplicate_risk"),
        },
        "memory_status": memory_status,
        "negative_memory_path": str(memory_path),
        "decision_policy": {
            "topic_direct_generation_allowed": False,
            "closest_work_required_for_phase6": True,
            "direct_baseline_required_for_experiment_blueprint": True,
            "final_promotion_allowed": False,
        },
    }
    _write_json(out_dir / "manifest.json", manifest)
    return manifest


def _artifact(out_dir: Path, kind: str, path: str, schema: str = "") -> dict[str, str]:
    payload = {"kind": kind, "path": path, "sha256": _sha256_file(out_dir / path)}
    if schema:
        payload["schema"] = schema
    return payload


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a Resmax Phase 5 idea portfolio.")
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--negative-memory", type=Path)
    args = parser.parse_args(argv)
    try:
        result = generate_portfolio(pack=args.pack, out=args.out, negative_memory=args.negative_memory)
    except Exception as exc:
        print(f"ERROR {exc}")
        return 1
    print(
        "[idea] generated "
        f"ideas={result['idea_count']} phase6_ready={result['phase6_ready']} out={result['ideas_dir']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
