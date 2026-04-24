from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agents" / "skills" / "resmax-survey" / "scripts"))

from search_literature_lib.filter_logger import FilterLog  # noqa: E402


def test_degraded_embedding_cache_is_not_error(tmp_path: Path) -> None:
    log = FilterLog(direction="smoke", keywords=["scene", "graph"])
    log.keyword_total_matches = 10
    log.keyword_kept = 3
    log.log_degraded("Embedding cache not found at /tmp/missing.npz; keyword-only retrieval")

    out = tmp_path / "filter_log.md"
    log.write(out)
    text = out.read_text(encoding="utf-8")

    assert "Degraded mode" in text
    assert "Embedding cache not found" in text
    assert "## Errors" not in text
    assert "## Stage 7: Final Distribution" not in text
