from __future__ import annotations

import argparse
from pathlib import Path

from .phase4_roi import extract_reviewer_pressure


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract Phase 4 reviewer pressure notes from review cache.")
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--reviews", type=Path, default=Path("paper_database/reviews"))
    parser.add_argument("--accepted", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--max-notes-per-paper", type=int, default=4)
    args = parser.parse_args(argv)
    result = extract_reviewer_pressure(
        pack=args.pack,
        reviews=args.reviews,
        accepted=args.accepted,
        out=args.out,
        max_notes_per_paper=args.max_notes_per_paper,
    )
    print(
        "[survey-v2] reviewer pressure "
        f"notes={result['reviewer_pressure_notes']} "
        f"missing_review_targets={result['missing_review_follow_up_targets']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
