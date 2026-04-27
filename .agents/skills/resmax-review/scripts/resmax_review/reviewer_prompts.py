from __future__ import annotations

import json
from typing import Any

from . import REVIEWER_ROLES
from .build_evidence_package import sha256_text


ROLE_INSTRUCTIONS = {
    "novelty": "Stress-test closest-work delta, overlap, and whether the claimed contribution is already covered.",
    "theory_or_mechanism": "Stress-test the mechanism, causal story, assumptions, and whether the claim follows from evidence.",
    "experiment": "Stress-test baselines, benchmark fit, falsification path, measurement, and missing experiment contracts.",
    "engineering": "Stress-test implementation reuse, compute cost, runtime risk, data friction, and reproducibility burden.",
    "reviewer_pressure": "Stress-test likely reviewer objections using reviewer pressure notes and attack surfaces.",
}


def build_prompt(reviewer_role: str, evidence_package: dict[str, Any]) -> str:
    if reviewer_role not in REVIEWER_ROLES:
        raise ValueError(f"unsupported reviewer role: {reviewer_role}")
    compact = {
        "idea_id": evidence_package.get("idea_id"),
        "package_id": evidence_package.get("package_id"),
        "review_input_policy": evidence_package.get("review_input_policy", {}),
        "idea_card": evidence_package.get("idea_card", {}),
        "research_spec": evidence_package.get("research_spec", {}),
        "selected_subdirection": evidence_package.get("selected_subdirection", {}),
        "closest_work_check": evidence_package.get("closest_work_check", {}),
        "closest_work_papers": evidence_package.get("closest_work_papers", []),
        "paper_role_assignments": evidence_package.get("paper_role_assignments", []),
        "source_gaps": evidence_package.get("source_gaps", []),
        "source_claims": evidence_package.get("source_claims", []),
        "evidence_cards": evidence_package.get("evidence_cards", []),
        "evidence_spans": evidence_package.get("evidence_spans", []),
        "roi_lens_entries": evidence_package.get("roi_lens_entries", []),
        "reviewer_pressure_notes": evidence_package.get("reviewer_pressure_notes", []),
    }
    return (
        f"You are the Resmax Phase 6 {reviewer_role} reviewer.\n"
        f"Task: {ROLE_INSTRUCTIONS[reviewer_role]}\n"
        "Use only the standard evidence package below. Do not use idea_report.md, chat context, or a generator pitch.\n"
        "Return raw JSON conforming to ReviewTrace. Preserve blockers as objects with severity and evidence_ids.\n"
        "Promotion requires crossing blockers; do not average scores.\n\n"
        + json.dumps(compact, ensure_ascii=False, sort_keys=True)
    )


def build_prompt_hash(reviewer_role: str, evidence_package: dict[str, Any]) -> str:
    return sha256_text(build_prompt(reviewer_role, evidence_package))
