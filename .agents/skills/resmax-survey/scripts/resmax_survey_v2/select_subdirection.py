from __future__ import annotations

import argparse
from pathlib import Path

from .phase3_pack import select_subdirection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Select a Survey V2 subdirection for Phase 3 evidence extraction.")
    parser.add_argument("--macro-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--subdirection-id", default="")
    parser.add_argument("--max-candidates", type=int, default=None)
    args = parser.parse_args(argv)
    payload = select_subdirection(
        macro_dir=args.macro_dir,
        out_dir=args.out_dir,
        subdirection_id=args.subdirection_id,
        max_candidates=args.max_candidates,
    )
    print(f"[survey-v2] selected {payload['selected_subdirection_id']} candidates={payload['paper_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
