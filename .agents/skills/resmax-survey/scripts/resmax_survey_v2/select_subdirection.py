from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .phase3_pack import select_subdirection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select a Survey V2 subdirection for Phase 3 evidence extraction.")
    parser.add_argument("--macro-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--subdirection-id", default="")
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--allow-auto-select", action="store_true")
    parser.add_argument("--mode", choices=["production", "test", "dev", "debug", "smoke"], default="production")
    args = parser.parse_args(argv)
    try:
        payload = select_subdirection(
            macro_dir=args.macro_dir,
            out_dir=args.out_dir,
            subdirection_id=args.subdirection_id,
            max_candidates=args.max_candidates,
            allow_auto_select=args.allow_auto_select,
            mode=args.mode,
        )
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print(f"[survey-v2] selected {payload['selected_subdirection_id']} candidates={payload['paper_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
