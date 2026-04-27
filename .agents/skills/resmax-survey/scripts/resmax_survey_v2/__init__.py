from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
SCRIPTS_ROOT = PACKAGE_ROOT.parent
SKILLS_ROOT = PACKAGE_ROOT.parents[2]
SHARED_ROOT = SKILLS_ROOT / "_shared"
REPO_ROOT = PACKAGE_ROOT.parents[4]
SCHEMA_ROOT = SHARED_ROOT / "resmax_core" / "schemas"

if str(SHARED_ROOT) not in sys.path:
    sys.path.insert(0, str(SHARED_ROOT))


ROLE_ORDER = (
    "direct_baseline",
    "method_donor",
    "benchmark_opportunity",
    "implementation_reference",
    "negative_evidence",
    "reviewer_risk",
    "survey_or_taxonomy",
)

ROLE_LABELS = {
    "direct_baseline": "Direct baseline",
    "method_donor": "Method donor",
    "benchmark_opportunity": "Benchmark opportunity",
    "implementation_reference": "Implementation reference",
    "negative_evidence": "Negative evidence",
    "reviewer_risk": "Reviewer risk",
    "survey_or_taxonomy": "Survey or taxonomy",
}
