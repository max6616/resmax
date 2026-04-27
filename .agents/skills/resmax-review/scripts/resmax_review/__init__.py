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


PRODUCER = {"name": "resmax_review", "version": SCHEMA_VERSION, "run_id": "phase6"}

REVIEWER_ROLES = (
    "novelty",
    "theory_or_mechanism",
    "experiment",
    "engineering",
    "reviewer_pressure",
)

FINAL_STATUS_FILES = {
    "promoted": "promoted_ideas.jsonl",
    "killed": "killed_ideas.jsonl",
    "revise": "revise_ideas.jsonl",
    "human_gate": "human_gate_ideas.jsonl",
}

REVIEW_ARTIFACTS = (
    "manifest.json",
    "review_matrix.csv",
    "blocker_summary.md",
    "disagreement_report.md",
    "tournament_trace.jsonl",
    "promoted_ideas.jsonl",
    "killed_ideas.jsonl",
    "revise_ideas.jsonl",
    "human_gate_ideas.jsonl",
)
