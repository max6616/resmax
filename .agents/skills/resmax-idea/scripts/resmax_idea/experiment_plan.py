from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id
from resmax_core.state import SCHEMA_VERSION, utc_now
from resmax_core.validators.common import load_json, validate_with_schema

from . import PRODUCER, SCHEMA_ROOT
from .load_pack import PackContext, resolve_pack_dir


PLAN_PRODUCER = {**PRODUCER, "run_id": "phase7"}

PLAN_ARTIFACTS = (
    "experiment_blueprint.json",
    "minimal_falsification_plan.md",
    "baseline_contract.md",
    "metric_contract.md",
    "ablation_plan.md",
    "visualization_plan.md",
    "risk_register.md",
    "human_gate.md",
    "claim_to_experiment_matrix.csv",
)

REQUIRED_REVIEW_ARTIFACTS = (
    "manifest.json",
    "promoted_ideas.jsonl",
    "killed_ideas.jsonl",
    "revise_ideas.jsonl",
    "human_gate_ideas.jsonl",
    "tournament_trace.jsonl",
)


def compile_experiment_plan(*, pack: Path, ideas: Path, reviews: Path, out: Path) -> dict[str, Any]:
    pack_ctx = PackContext.load(resolve_pack_dir(pack))
    idea_ctx = _load_ideas(ideas)
    review_ctx = _load_reviews(reviews)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    blocks: list[dict[str, Any]] = []
    blocked_promoted: list[dict[str, Any]] = []
    for decision in review_ctx["promoted"]:
        idea_id = str(decision.get("idea_id", ""))
        card = idea_ctx["cards_by_id"].get(idea_id) or decision.get("idea_snapshot", {})
        if not card:
            blocked_promoted.append(_blocked_idea(idea_id, "missing_idea_card", decision))
            continue
        missing_raw = _missing_raw_reviews(idea_id, decision, review_ctx)
        if missing_raw:
            blocked_promoted.append(_blocked_idea(idea_id, "missing_raw_review_trace", decision, missing_raw))
            continue
        blocks.append(_experiment_block(card, decision, pack_ctx, review_ctx["raw_by_idea"].get(idea_id, [])))

    blueprint = _blueprint(
        pack_ctx=pack_ctx,
        ideas=ideas,
        reviews=reviews,
        idea_manifest=idea_ctx["manifest"],
        review_manifest=review_ctx["manifest"],
        blocks=blocks,
        blocked_promoted=blocked_promoted,
    )
    _write_json(out / "experiment_blueprint.json", blueprint)
    _validate_blueprint(out / "experiment_blueprint.json")
    _write_markdown_outputs(out, blueprint)
    _write_matrix(out / "claim_to_experiment_matrix.csv", blocks)
    manifest = _write_manifest(out, blueprint, pack_ctx, idea_ctx["manifest"], review_ctx["manifest"])
    return {
        "out": str(out),
        "blueprint_id": blueprint["blueprint_id"],
        "experiment_block_count": len(blocks),
        "blocked_promoted_count": len(blocked_promoted),
        "manifest": manifest,
    }


def _experiment_block(
    card: dict[str, Any],
    decision: dict[str, Any],
    pack_ctx: PackContext,
    raw_reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    idea_id = str(card.get("idea_id", decision.get("idea_id", "")))
    baseline = _baseline_contract(card, pack_ctx)
    dataset = _dataset_contract(card, pack_ctx)
    metric = _metric_contract(card)
    missing_contracts = [
        name
        for name, value in (
            ("baseline", baseline["category"] == "unknown_needs_followup"),
            ("dataset", dataset["status"] == "unknown_needs_followup" and not dataset["anchor_ids"]),
            ("metric", metric["primary_metric"] == "unknown_needs_followup"),
        )
        if value
    ]
    estimated_cost = _estimated_cost(card, baseline, dataset)
    over_budget = estimated_cost["budget_status"] == "over_budget"
    budget_gate_required = over_budget or estimated_cost["budget_status"] in {"unknown_needs_followup", "approval_required"}
    human_gate_required = True
    if missing_contracts:
        execution_status = "insufficient_evidence"
    elif budget_gate_required:
        execution_status = "human_gate_required"
    else:
        execution_status = "approval_required"

    tested_claim = str(card.get("primary_claim") or "unknown_needs_followup")
    anti_claim = _anti_claim(card, decision)
    cheapest = card.get("cheapest_falsification", {}) if isinstance(card.get("cheapest_falsification"), dict) else {}
    experiment_input = {
        "idea_id": idea_id,
        "tested_claim": tested_claim,
        "anti_claim": anti_claim,
        "baseline": baseline,
        "dataset": dataset,
        "metric": metric,
        "execution_status": execution_status,
    }
    return {
        "experiment_id": make_state_id("experiment", experiment_input),
        "idea_id": idea_id,
        "source_idea_state_id": card.get("state_id", ""),
        "source_review_trace_ids": [row.get("review_id", "") for row in raw_reviews if row.get("review_id")],
        "tested_claim": tested_claim,
        "anti_claim": anti_claim,
        "minimum_convincing_evidence": _minimum_convincing_evidence(card, cheapest),
        "baseline": baseline,
        "dataset": dataset,
        "metric": metric,
        "ablation_or_sanity_check": _ablation_or_sanity_check(card, baseline),
        "estimated_cost": estimated_cost,
        "stop_condition": str(cheapest.get("falsifies_if") or "Stop if the primary metric cannot beat the must-run baseline under the sanity checks."),
        "failure_interpretation": _failure_interpretation(card, anti_claim, missing_contracts),
        "required_artifacts": _required_artifacts(card, baseline, dataset, metric),
        "human_gate_required": human_gate_required,
        "execution_status": execution_status,
        "unresolved_blockers": _unresolved_blockers(decision),
        "negative_memory_if_rejected": _negative_memory_if_rejected(card, decision, missing_contracts, over_budget),
    }


def _baseline_contract(card: dict[str, Any], pack_ctx: PackContext) -> dict[str, Any]:
    direct = _dedupe([str(item) for item in card.get("direct_baselines", []) if item])
    closest = _dedupe([str(item) for item in card.get("closest_work_ids", []) if item])
    donors = _dedupe([str(item) for item in card.get("method_donors", []) if item])
    benchmark_ids = _dedupe([str(item) for item in card.get("benchmark_opportunities", []) if item])
    if not direct:
        category = "unknown_needs_followup"
        must_run: list[str] = []
        rationale = "No direct baseline is attached to the promoted idea; Phase 7 cannot mark an executable blueprint."
    else:
        category = "must_run"
        must_run = direct
        rationale = "Direct baselines from the IdeaCard are the minimum reviewer-belief-changing comparison."
    nice_to_have = [item for item in donors + benchmark_ids if item not in must_run]
    appendix_only = [item for item in closest if item not in must_run and item not in nice_to_have]
    rows = _rows_by_id(pack_ctx.pack_dir / "baseline_matrix.csv")
    burdens = [
        rows.get(item, {}).get("baseline_burden", "unknown") or "unknown"
        for item in must_run
    ]
    follow_up = [
        rows.get(item, {}).get("follow_up_targets", "")
        for item in must_run + nice_to_have + appendix_only
        if rows.get(item, {}).get("follow_up_targets")
    ]
    return {
        "category": category,
        "must_run": must_run,
        "nice_to_have": _dedupe(nice_to_have),
        "appendix_only": _dedupe(appendix_only),
        "not_applicable": [],
        "unknown_needs_followup": [] if direct else ["direct_baseline"],
        "baseline_burden": _worst_burden(burdens),
        "follow_up": _dedupe(follow_up),
        "rationale": rationale,
    }


def _dataset_contract(card: dict[str, Any], pack_ctx: PackContext) -> dict[str, Any]:
    anchors = _dedupe(
        [str(item) for item in card.get("benchmark_opportunities", []) if item]
        + [str(item) for item in card.get("closest_work_ids", []) if item]
    )
    rows = _rows_by_id(pack_ctx.pack_dir / "benchmark_matrix.csv")
    available = [item for item in anchors if rows.get(item, {}).get("has_dataset") == "yes"]
    follow_up = [
        rows.get(item, {}).get("follow_up_targets", "")
        for item in anchors
        if rows.get(item, {}).get("follow_up_targets")
    ]
    if available:
        status = "available"
        name = ", ".join(_title_for_id(pack_ctx, item) for item in available)
    elif anchors:
        status = "unknown_needs_followup"
        name = ", ".join(_title_for_id(pack_ctx, item) for item in anchors)
    else:
        status = "unknown_needs_followup"
        name = "unknown_needs_followup"
    return {
        "status": status,
        "name": name,
        "anchor_ids": anchors,
        "source": "benchmark_matrix.csv" if rows else "idea_card",
        "follow_up": _dedupe(follow_up) if follow_up else (["identify dataset or benchmark protocol"] if not anchors else []),
    }


def _metric_contract(card: dict[str, Any]) -> dict[str, Any]:
    claim = str(card.get("primary_claim", ""))
    if not claim:
        return {
            "primary_metric": "unknown_needs_followup",
            "secondary_metrics": [],
            "sanity_metrics": [],
            "failure_metric": "unknown_needs_followup",
            "rationale": "No primary claim is available to bind a metric contract.",
        }
    return {
        "primary_metric": "claim_delta_vs_must_run_baseline",
        "secondary_metrics": ["compute_or_runtime_cost", "data_or_annotation_friction"],
        "sanity_metrics": ["closest_work_reproduction_check", "baseline_only_variant"],
        "failure_metric": "no_measurable_delta_after_controlling_baseline_and_cost",
        "rationale": "Metrics are defined to falsify the primary claim before expanding into a full paper experiment table.",
    }


def _estimated_cost(card: dict[str, Any], baseline: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    raw = str(card.get("estimated_compute") or "unknown_follow_up_required")
    burden = str(baseline.get("baseline_burden", "unknown"))
    if "high" in raw or burden == "high":
        status = "over_budget"
    elif "unknown" in raw or burden == "unknown" or dataset.get("status") == "unknown_needs_followup":
        status = "unknown_needs_followup"
    elif "medium" in raw or burden == "medium":
        status = "approval_required"
    else:
        status = "within_minimal_budget"
    return {
        "estimate": raw,
        "baseline_burden": burden,
        "dataset_status": dataset.get("status", "unknown_needs_followup"),
        "budget_status": status,
    }


def _blueprint(
    *,
    pack_ctx: PackContext,
    ideas: Path,
    reviews: Path,
    idea_manifest: dict[str, Any],
    review_manifest: dict[str, Any],
    blocks: list[dict[str, Any]],
    blocked_promoted: list[dict[str, Any]],
) -> dict[str, Any]:
    blueprint_input = {
        "research_pack": pack_ctx.manifest.get("state_id", ""),
        "ideas": str(ideas.resolve()),
        "reviews": str(reviews.resolve()),
        "experiment_ids": [block["experiment_id"] for block in blocks],
        "blocked": blocked_promoted,
    }
    baseline_contract = _combined_baseline_contract(blocks)
    metric_contract = _combined_metric_contract(blocks)
    human_gate_package = [_human_gate_item(block) for block in blocks]
    risk_register = _risk_register(blocks, blocked_promoted)
    evidence_status = "supported" if blocks and not blocked_promoted else "mixed" if blocks else "insufficient_evidence"
    decision_status = "pending" if any(block["human_gate_required"] for block in blocks) or blocked_promoted else "promoted"
    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("experiment_blueprint", blueprint_input),
        "created_at": utc_now(),
        "input_hash": input_hash(blueprint_input),
        "parent_state_ids": [
            value
            for value in (
                pack_ctx.manifest.get("state_id"),
                idea_manifest.get("state_id"),
                review_manifest.get("state_id"),
            )
            if value
        ],
        "producer": PLAN_PRODUCER,
        "blueprint_id": make_state_id("blueprint", blueprint_input),
        "source_paths": {
            "research_pack": _portable_path(pack_ctx.pack_dir),
            "ideas": _portable_path(ideas),
            "reviews": _portable_path(reviews),
        },
        "experiment_blocks": blocks,
        "blocked_promoted_ideas": blocked_promoted,
        "baseline_contract": baseline_contract,
        "metric_contract": metric_contract,
        "risk_register": risk_register,
        "human_gate_package": human_gate_package,
        "evidence_status": evidence_status,
        "decision_status": decision_status,
    }


def _load_ideas(path: Path) -> dict[str, Any]:
    path = path.resolve()
    required = ("manifest.json", "idea_cards.jsonl")
    missing = [name for name in required if not (path / name).exists()]
    if missing:
        raise FileNotFoundError("idea portfolio is incomplete: " + ", ".join(missing))
    cards = _read_jsonl(path / "idea_cards.jsonl")
    return {
        "ideas_dir": path,
        "manifest": _read_json(path / "manifest.json"),
        "cards": cards,
        "cards_by_id": {str(card.get("idea_id", "")): card for card in cards if card.get("idea_id")},
    }


def _load_reviews(path: Path) -> dict[str, Any]:
    path = path.resolve()
    missing = [name for name in REQUIRED_REVIEW_ARTIFACTS if not (path / name).exists()]
    if missing:
        raise FileNotFoundError("Phase 6 reviews are incomplete: " + ", ".join(missing))
    raw_by_idea: dict[str, list[dict[str, Any]]] = {}
    raw_dir = path / "raw"
    if raw_dir.exists():
        for raw_path in sorted(raw_dir.glob("*/*.json")):
            trace = _read_json(raw_path)
            idea_id = str(trace.get("idea_id", raw_path.stem))
            raw_by_idea.setdefault(idea_id, []).append(trace)
    return {
        "reviews_dir": path,
        "manifest": _read_json(path / "manifest.json"),
        "promoted": _read_jsonl(path / "promoted_ideas.jsonl"),
        "killed": _read_jsonl(path / "killed_ideas.jsonl"),
        "revise": _read_jsonl(path / "revise_ideas.jsonl"),
        "human_gate": _read_jsonl(path / "human_gate_ideas.jsonl"),
        "raw_by_idea": raw_by_idea,
    }


def _missing_raw_reviews(idea_id: str, decision: dict[str, Any], review_ctx: dict[str, Any]) -> list[str]:
    raw_reviews = review_ctx["raw_by_idea"].get(idea_id, [])
    required_roles = [str(role) for role in review_ctx["manifest"].get("required_reviewer_roles", []) if role]
    present_roles = {str(row.get("reviewer_role", "")) for row in raw_reviews}
    missing_roles = [role for role in required_roles if role not in present_roles]
    if not raw_reviews:
        missing_roles.append("all_raw_reviews")
    missing_trace_ids = [
        str(trace_id)
        for trace_id in decision.get("review_trace_ids", [])
        if trace_id and trace_id not in {str(row.get("review_id", "")) for row in raw_reviews}
    ]
    return _dedupe(missing_roles + missing_trace_ids)


def _blocked_idea(
    idea_id: str,
    reason_type: str,
    decision: dict[str, Any],
    details: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "idea_id": idea_id,
        "reason_type": reason_type,
        "details": details or [],
        "decision_reasons": decision.get("decision_reasons", []),
        "source_review_trace_ids": decision.get("review_trace_ids", []),
        "follow_up_plan": "Recover valid raw ReviewTrace artifacts before compiling an experiment blueprint.",
        "execution_status": "insufficient_evidence",
    }


def _anti_claim(card: dict[str, Any], decision: dict[str, Any]) -> str:
    strongest = str(card.get("strongest_rejection_case", "")).strip()
    if strongest:
        return strongest
    reasons = "; ".join(str(item) for item in decision.get("decision_reasons", []) if item)
    return reasons or "The closest baseline or closest work already explains the claimed delta."


def _minimum_convincing_evidence(card: dict[str, Any], cheapest: dict[str, Any]) -> str:
    if cheapest.get("minimal_test"):
        return str(cheapest["minimal_test"])
    baselines = ", ".join(str(item) for item in card.get("direct_baselines", []) if item)
    return f"One controlled comparison against {baselines or 'the closest direct baseline'} that can falsify the primary claim."


def _ablation_or_sanity_check(card: dict[str, Any], baseline: dict[str, Any]) -> str:
    must = ", ".join(baseline.get("must_run", [])) or "the closest baseline"
    modes = card.get("expected_failure_modes", [])
    mode = modes[0] if modes else "the claimed mechanism may disappear after baseline control"
    return f"Run a baseline-only variant against {must}; verify whether {mode}."


def _failure_interpretation(card: dict[str, Any], anti_claim: str, missing_contracts: list[str]) -> str:
    if missing_contracts:
        return "The plan is not executable until these contracts are resolved: " + ", ".join(missing_contracts)
    return f"Failure supports the anti-claim: {anti_claim}"


def _required_artifacts(
    card: dict[str, Any],
    baseline: dict[str, Any],
    dataset: dict[str, Any],
    metric: dict[str, Any],
) -> list[str]:
    artifacts = [
        "raw_config_or_protocol",
        "baseline_outputs",
        "metric_table",
        "failure_notes",
    ]
    if baseline.get("follow_up"):
        artifacts.append("baseline_audit")
    if dataset.get("follow_up"):
        artifacts.append("dataset_protocol_audit")
    if metric.get("sanity_metrics"):
        artifacts.append("sanity_check_outputs")
    if card.get("evidence_ids"):
        artifacts.append("evidence_linkage")
    return artifacts


def _unresolved_blockers(decision: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = []
    for blocker in decision.get("blockers", []):
        if not isinstance(blocker, dict):
            continue
        if blocker.get("severity") in {"fatal", "major"}:
            blockers.append(
                {
                    "blocker_type": blocker.get("blocker_type", "unknown"),
                    "severity": blocker.get("severity", "unknown"),
                    "evidence_status": blocker.get("evidence_status", "unknown"),
                    "evidence_ids": blocker.get("evidence_ids", []),
                    "explanation": blocker.get("explanation", ""),
                }
            )
    return blockers


def _negative_memory_if_rejected(
    card: dict[str, Any],
    decision: dict[str, Any],
    missing_contracts: list[str],
    over_budget: bool,
) -> dict[str, Any]:
    reasons = list(decision.get("decision_reasons", []))
    if missing_contracts:
        reasons.append("missing experiment contracts: " + ", ".join(missing_contracts))
    if over_budget:
        reasons.append("minimal falsification path is over budget")
    return {
        "subject_id": card.get("idea_id", ""),
        "source_gap_ids": card.get("source_gap_ids", []),
        "evidence_card_ids": card.get("evidence_ids", []),
        "reason": "; ".join(str(item) for item in reasons if item) or "human rejected the Phase 7 experiment start gate",
    }


def _human_gate_item(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "idea_id": block["idea_id"],
        "experiment_id": block["experiment_id"],
        "why_promoted": "Phase 6 promoted this idea after blocker-first raw review aggregation.",
        "unresolved_blockers": block["unresolved_blockers"],
        "cheapest_falsification": block["minimum_convincing_evidence"],
        "estimated_cost": block["estimated_cost"],
        "what_approval_enables": "Run only the minimal falsification protocol and produce the required artifacts.",
        "negative_memory_if_rejected": block["negative_memory_if_rejected"],
        "human_gate_required": block["human_gate_required"],
    }


def _combined_baseline_contract(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    combined = {
        "must_run": [],
        "nice_to_have": [],
        "appendix_only": [],
        "not_applicable": [],
        "unknown_needs_followup": [],
    }
    for block in blocks:
        baseline = block["baseline"]
        for key in combined:
            combined[key].extend(baseline.get(key, []))
    return {key: _dedupe(values) for key, values in combined.items()}


def _combined_metric_contract(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    primary = _dedupe([block["metric"]["primary_metric"] for block in blocks if block.get("metric")])
    secondary: list[str] = []
    sanity: list[str] = []
    failure = _dedupe([block["metric"]["failure_metric"] for block in blocks if block.get("metric")])
    for block in blocks:
        metric = block.get("metric", {})
        secondary.extend(metric.get("secondary_metrics", []))
        sanity.extend(metric.get("sanity_metrics", []))
    return {
        "primary_metric": primary[0] if primary else "unknown_needs_followup",
        "secondary_metrics": _dedupe(secondary),
        "sanity_metrics": _dedupe(sanity),
        "failure_metric": failure[0] if failure else "unknown_needs_followup",
    }


def _risk_register(blocks: list[dict[str, Any]], blocked_promoted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for block in blocks:
        if block["execution_status"] != "executable":
            risks.append(
                {
                    "risk_id": make_state_id("risk", {"experiment_id": block["experiment_id"], "status": block["execution_status"]}),
                    "idea_id": block["idea_id"],
                    "risk_type": block["execution_status"],
                    "severity": "high" if block["execution_status"] == "insufficient_evidence" else "medium",
                    "mitigation": block["failure_interpretation"],
                    "source": "experiment_block",
                }
            )
        for blocker in block.get("unresolved_blockers", []):
            risks.append(
                {
                    "risk_id": make_state_id("risk", {"experiment_id": block["experiment_id"], "blocker": blocker}),
                    "idea_id": block["idea_id"],
                    "risk_type": blocker.get("blocker_type", "review_blocker"),
                    "severity": blocker.get("severity", "unknown"),
                    "mitigation": blocker.get("explanation", ""),
                    "source": "review_blocker",
                }
            )
    for item in blocked_promoted:
        risks.append(
            {
                "risk_id": make_state_id("risk", item),
                "idea_id": item.get("idea_id", ""),
                "risk_type": item.get("reason_type", "blocked_promoted_idea"),
                "severity": "high",
                "mitigation": item.get("follow_up_plan", ""),
                "source": "precondition",
            }
        )
    return risks


def _write_markdown_outputs(out: Path, blueprint: dict[str, Any]) -> None:
    blocks = blueprint["experiment_blocks"]
    _write_text(out / "minimal_falsification_plan.md", _render_minimal_plan(blocks))
    _write_text(out / "baseline_contract.md", _render_baseline_contract(blueprint["baseline_contract"], blocks))
    _write_text(out / "metric_contract.md", _render_metric_contract(blueprint["metric_contract"], blocks))
    _write_text(out / "ablation_plan.md", _render_ablation_plan(blocks))
    _write_text(out / "visualization_plan.md", _render_visualization_plan(blocks))
    _write_text(out / "risk_register.md", _render_risk_register(blueprint["risk_register"]))
    _write_text(out / "human_gate.md", _render_human_gate(blueprint["human_gate_package"], blueprint["blocked_promoted_ideas"]))


def _render_minimal_plan(blocks: list[dict[str, Any]]) -> str:
    lines = ["# Minimal Falsification Plan", "", "Rendered from `experiment_blueprint.json`.", ""]
    for block in blocks:
        lines.extend(
            [
                f"## {block['experiment_id']}",
                "",
                f"- Idea: `{block['idea_id']}`",
                f"- Tested claim: {block['tested_claim']}",
                f"- Anti-claim: {block['anti_claim']}",
                f"- Minimum convincing evidence: {block['minimum_convincing_evidence']}",
                f"- Stop condition: {block['stop_condition']}",
                f"- Execution status: `{block['execution_status']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_baseline_contract(contract: dict[str, Any], blocks: list[dict[str, Any]]) -> str:
    lines = ["# Baseline Contract", "", "Rendered from `experiment_blueprint.json`.", ""]
    for key in ("must_run", "nice_to_have", "appendix_only", "not_applicable", "unknown_needs_followup"):
        values = contract.get(key, [])
        lines.append(f"- {key}: " + (", ".join(f"`{value}`" for value in values) if values else "none"))
    lines.append("")
    for block in blocks:
        baseline = block["baseline"]
        lines.append(f"## {block['idea_id']}")
        lines.append("")
        lines.append(f"- Category: `{baseline['category']}`")
        lines.append(f"- Burden: `{baseline['baseline_burden']}`")
        lines.append(f"- Rationale: {baseline['rationale']}")
        if baseline.get("follow_up"):
            lines.append("- Follow-up: " + "; ".join(baseline["follow_up"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_metric_contract(contract: dict[str, Any], blocks: list[dict[str, Any]]) -> str:
    lines = ["# Metric Contract", "", "Rendered from `experiment_blueprint.json`.", ""]
    lines.append(f"- Primary metric: `{contract['primary_metric']}`")
    lines.append("- Secondary metrics: " + (", ".join(f"`{value}`" for value in contract["secondary_metrics"]) or "none"))
    lines.append("- Sanity metrics: " + (", ".join(f"`{value}`" for value in contract["sanity_metrics"]) or "none"))
    lines.append(f"- Failure metric: `{contract['failure_metric']}`")
    lines.append("")
    for block in blocks:
        metric = block["metric"]
        lines.append(f"## {block['idea_id']}")
        lines.append("")
        lines.append(f"- Primary: `{metric['primary_metric']}`")
        lines.append(f"- Failure: `{metric['failure_metric']}`")
        lines.append(f"- Rationale: {metric['rationale']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_ablation_plan(blocks: list[dict[str, Any]]) -> str:
    lines = ["# Ablation Plan", "", "Rendered from `experiment_blueprint.json`.", ""]
    for block in blocks:
        lines.extend([f"- `{block['experiment_id']}`: {block['ablation_or_sanity_check']}"])
    return "\n".join(lines).rstrip() + "\n"


def _render_visualization_plan(blocks: list[dict[str, Any]]) -> str:
    lines = ["# Visualization Plan", "", "Rendered from `experiment_blueprint.json`.", ""]
    for block in blocks:
        lines.append(
            f"- `{block['experiment_id']}`: show primary metric, baseline delta, compute/runtime cost, and failure metric in one compact table."
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_risk_register(risks: list[dict[str, Any]]) -> str:
    lines = ["# Risk Register", "", "Rendered from `experiment_blueprint.json`.", ""]
    if not risks:
        lines.append("No unresolved Phase 7 risks.")
    for risk in risks:
        lines.append(f"- `{risk['risk_id']}` `{risk['severity']}` {risk['risk_type']}: {risk['mitigation']}")
    return "\n".join(lines).rstrip() + "\n"


def _render_human_gate(packages: list[dict[str, Any]], blocked_promoted: list[dict[str, Any]]) -> str:
    lines = ["# Human Gate", "", "Rendered from `experiment_blueprint.json`.", ""]
    for package in packages:
        lines.extend(
            [
                f"## {package['idea_id']}",
                "",
                f"- Why promoted: {package['why_promoted']}",
                f"- Cheapest falsification: {package['cheapest_falsification']}",
                f"- Estimated cost: `{package['estimated_cost']['budget_status']}`",
                f"- What approval enables: {package['what_approval_enables']}",
                f"- Human gate required: `{package['human_gate_required']}`",
                f"- Negative memory if rejected: {package['negative_memory_if_rejected']['reason']}",
                "",
            ]
        )
    if blocked_promoted:
        lines.append("## Blocked Promoted Ideas")
        lines.append("")
        for item in blocked_promoted:
            lines.append(f"- `{item['idea_id']}` `{item['reason_type']}`: {item['follow_up_plan']}")
    return "\n".join(lines).rstrip() + "\n"


def _write_matrix(path: Path, blocks: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "idea_id",
                "experiment_id",
                "tested_claim",
                "anti_claim",
                "baseline_category",
                "dataset_status",
                "primary_metric",
                "execution_status",
                "human_gate_required",
                "stop_condition",
            ],
        )
        writer.writeheader()
        for block in blocks:
            writer.writerow(
                {
                    "idea_id": block["idea_id"],
                    "experiment_id": block["experiment_id"],
                    "tested_claim": block["tested_claim"],
                    "anti_claim": block["anti_claim"],
                    "baseline_category": block["baseline"]["category"],
                    "dataset_status": block["dataset"]["status"],
                    "primary_metric": block["metric"]["primary_metric"],
                    "execution_status": block["execution_status"],
                    "human_gate_required": str(block["human_gate_required"]).lower(),
                    "stop_condition": block["stop_condition"],
                }
            )


def _write_manifest(
    out: Path,
    blueprint: dict[str, Any],
    pack_ctx: PackContext,
    idea_manifest: dict[str, Any],
    review_manifest: dict[str, Any],
) -> dict[str, Any]:
    artifacts = [_artifact(out, rel, "experiment_blueprint.schema.json" if rel == "experiment_blueprint.json" else "") for rel in PLAN_ARTIFACTS]
    manifest_input = {
        "blueprint_id": blueprint["blueprint_id"],
        "artifact_hashes": [artifact["sha256"] for artifact in artifacts],
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("experiment_plan_manifest", manifest_input),
        "created_at": utc_now(),
        "input_hash": input_hash(manifest_input),
        "parent_state_ids": [
            value
            for value in (
                blueprint.get("state_id"),
                pack_ctx.manifest.get("state_id"),
                idea_manifest.get("state_id"),
                review_manifest.get("state_id"),
            )
            if value
        ],
        "producer": PLAN_PRODUCER,
        "blueprint_id": blueprint["blueprint_id"],
        "experiment_block_count": len(blueprint["experiment_blocks"]),
        "blocked_promoted_count": len(blueprint["blocked_promoted_ideas"]),
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "execution_boundary": {
            "runs_real_experiments": False,
            "runs_training": False,
            "writes_paper": False,
            "empirical_result_claims_allowed": False,
        },
    }
    _write_json(out / "manifest.json", manifest)
    return manifest


def _validate_blueprint(path: Path) -> None:
    schema = load_json(SCHEMA_ROOT / "experiment_blueprint.schema.json")
    payload = _read_json(path)
    errors = list(validate_with_schema(payload, schema))
    if errors:
        formatted = "; ".join(error.format() for error in errors[:5])
        raise ValueError(f"experiment blueprint schema validation failed: {formatted}")


def _rows_by_id(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as f:
        return {row.get("paper_id", ""): row for row in csv.DictReader(f) if row.get("paper_id")}


def _title_for_id(pack_ctx: PackContext, paper_id: str) -> str:
    title = pack_ctx.title_for_paper(paper_id)
    return title or paper_id


def _worst_burden(values: list[str]) -> str:
    order = {"unknown": 3, "high": 4, "medium": 2, "low": 1, "none": 0, "": 3}
    if not values:
        return "unknown"
    return max(values, key=lambda item: order.get(item, 3))


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {path}:{line_no}")
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _artifact(root: Path, rel_path: str, schema: str = "") -> dict[str, str]:
    payload = {"kind": Path(rel_path).stem, "path": rel_path, "sha256": _sha256_file(root / rel_path)}
    if schema:
        payload["schema"] = schema
    return payload


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _portable_path(path: Path) -> str:
    return str(path.resolve())


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile Phase 7 experiment blueprints from promoted Phase 6 ideas.")
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--ideas", required=True, type=Path)
    parser.add_argument("--reviews", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = compile_experiment_plan(pack=args.pack, ideas=args.ideas, reviews=args.reviews, out=args.out)
    except Exception as exc:
        print(f"ERROR {exc}")
        return 1
    print(
        "[idea] compiled experiment_plan "
        f"blocks={result['experiment_block_count']} blocked_promoted={result['blocked_promoted_count']} out={result['out']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
