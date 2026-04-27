from __future__ import annotations

import argparse
from pathlib import Path

from .phase3_pack import extract_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract Phase 3 evidence spans and cards from selected candidates.")
    parser.add_argument("--macro-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--source-cache-dir", type=Path, default=None)
    parser.add_argument("--max-spans-per-paper", type=int, default=3)
    args = parser.parse_args(argv)
    coverage = extract_evidence(
        macro_dir=args.macro_dir,
        out_dir=args.out_dir,
        source_cache_dir=args.source_cache_dir,
        max_spans_per_paper=args.max_spans_per_paper,
    )
    print(
        "[survey-v2] evidence "
        f"spans={coverage['evidence_span_count']} cards={coverage['evidence_card_count']} "
        f"missing_source={coverage['missing_source_count']} missing_pdf={coverage['missing_pdf_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
