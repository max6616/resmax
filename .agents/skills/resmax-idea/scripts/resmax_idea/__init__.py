from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
SCRIPTS_ROOT = PACKAGE_ROOT.parent
SKILL_ROOT = SCRIPTS_ROOT.parent
SKILLS_ROOT = SKILL_ROOT.parent
SHARED_ROOT = SKILLS_ROOT / "_shared"
REPO_ROOT = SKILLS_ROOT.parents[1]
SCHEMA_ROOT = SHARED_ROOT / "resmax_core" / "schemas"

if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))

from resmax_core.state import SCHEMA_VERSION  # noqa: E402


PRODUCER = {"name": "resmax_idea", "version": SCHEMA_VERSION, "run_id": "phase5"}

REQUIRED_PHASE4_ARTIFACTS = (
    "gap_map.json",
    "claim_graph.json",
    "evidence_cards.jsonl",
    "evidence_spans.jsonl",
    "reviewer_pressure_notes.jsonl",
    "paper_roles.json",
    "roi_lens.json",
    "gap_roi_table.csv",
    "idea_seed_constraints.md",
)

PORTFOLIO_ARTIFACTS = (
    "manifest.json",
    "idea_cards.jsonl",
    "idea_lineage.json",
    "closest_work_checks.jsonl",
    "strongest_rejection_cases.md",
    "cheapest_falsification.md",
    "generation_trace.jsonl",
    "idea_report.md",
)

ALLOWED_GENERATION_SOURCES = {
    "gap_driven",
    "reviewer_pressure_driven",
    "benchmark_blindspot_driven",
    "method_transfer_driven",
    "human_seed",
}

READY_STATUSES = {"phase6_ready"}
NON_RECOMMENDED_STATUSES = {
    "phase6_ready",
    "not_ready_for_phase6",
    "not_ready_for_experiment",
    "speculative",
    "insufficient_evidence",
    "duplicate_risk",
}
