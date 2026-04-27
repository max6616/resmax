from __future__ import annotations

import argparse
from pathlib import Path

from .phase4_roi import build_roi_lens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Phase 4 reviewer-pressure ROI lens for a research_pack.")
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--reviews", type=Path, default=Path("paper_database/reviews"))
    parser.add_argument("--accepted", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--max-notes-per-paper", type=int, default=4)
    args = parser.parse_args(argv)
    result = build_roi_lens(
        pack=args.pack,
        reviews=args.reviews,
        accepted=args.accepted,
        out=args.out,
        max_notes_per_paper=args.max_notes_per_paper,
    )
    print(
        "[survey-v2] roi lens "
        f"notes={result['reviewer_pressure_notes']} roles={result['paper_role_assignments']} "
        f"gap_rows={result['gap_roi_rows']} unknown_targets={result['unknown_follow_up_targets']}"
    )
    print(f"[survey-v2] wrote research pack to {result['pack_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
