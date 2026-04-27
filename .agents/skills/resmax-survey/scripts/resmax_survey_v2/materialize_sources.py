from __future__ import annotations

import argparse
from pathlib import Path

from .phase3_pack import materialize_sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize selected Phase 3 paper sources for a Survey V2 pack.")
    parser.add_argument("--macro-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--source-cache-dir", type=Path, default=None)
    parser.add_argument("--disable-oa-api", action="store_true")
    parser.add_argument("--enable-sci-hub", action="store_true")
    parser.add_argument("--overwrite-sources", action="store_true")
    args = parser.parse_args(argv)
    report = materialize_sources(
        macro_dir=args.macro_dir,
        out_dir=args.out_dir,
        source_cache_dir=args.source_cache_dir,
        disable_oa_api=args.disable_oa_api,
        enable_sci_hub=args.enable_sci_hub,
        overwrite_sources=args.overwrite_sources,
    )
    counts = report["counts"]
    print(
        "[survey-v2] materialized sources "
        f"readable={counts['readable_source_count']}/{counts['selected_candidate_count']} "
        f"pdf_text={counts['pdf_text_count']}/{counts['selected_candidate_count']} "
        f"cache={report['cache_dir']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
