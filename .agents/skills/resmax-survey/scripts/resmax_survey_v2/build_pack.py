from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .phase3_pack import build_pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Phase 3 research_pack from a Survey V2 macro pack.")
    parser.add_argument("--macro-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--subdirection-id", default="")
    parser.add_argument("--source-cache-dir", type=Path, default=None)
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--max-spans-per-paper", type=int, default=3)
    parser.add_argument("--skip-source-materialization", action="store_true")
    parser.add_argument("--disable-oa-api", action="store_true")
    parser.add_argument("--enable-sci-hub", action="store_true")
    parser.add_argument("--overwrite-sources", action="store_true")
    parser.add_argument("--allow-auto-select", action="store_true")
    parser.add_argument("--allow-abstract-fallback", action="store_true")
    parser.add_argument("--mode", choices=["production", "test", "dev", "debug", "smoke"], default="production")
    args = parser.parse_args(argv)
    try:
        result = build_pack(
            macro_dir=args.macro_dir,
            out_dir=args.out_dir,
            subdirection_id=args.subdirection_id,
            source_cache_dir=args.source_cache_dir,
            max_candidates=args.max_candidates,
            max_spans_per_paper=args.max_spans_per_paper,
            skip_source_materialization=args.skip_source_materialization,
            disable_oa_api=args.disable_oa_api,
            enable_sci_hub=args.enable_sci_hub,
            overwrite_sources=args.overwrite_sources,
            allow_auto_select=args.allow_auto_select,
            allow_abstract_fallback=args.allow_abstract_fallback,
            mode=args.mode,
        )
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    coverage = result["coverage"]
    materialization = result.get("materialization", {})
    if materialization:
        counts = materialization.get("counts", {})
        print(
            "[survey-v2] materialized sources "
            f"readable={counts.get('readable_source_count', 0)}/{counts.get('selected_candidate_count', 0)} "
            f"pdf_text={counts.get('pdf_text_count', 0)}/{counts.get('selected_candidate_count', 0)}"
        )
    print(f"[survey-v2] wrote research pack to {result['pack_dir']}")
    print(
        "[survey-v2] coverage "
        f"candidates={coverage['selected_candidate_count']} spans={coverage['evidence_span_count']} "
        f"cards={coverage['evidence_card_count']} missing_source={coverage['missing_source_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
