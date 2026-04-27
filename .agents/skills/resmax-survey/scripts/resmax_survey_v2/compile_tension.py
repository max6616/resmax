from __future__ import annotations

import argparse
from pathlib import Path

from .phase3_pack import compile_tension


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile Phase 3 ClaimGraph and GapMap from evidence cards.")
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    result = compile_tension(out_dir=args.out_dir)
    print(
        "[survey-v2] tension "
        f"claims={len(result['claim_graph']['claims'])} gaps={len(result['gap_map']['gaps'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
