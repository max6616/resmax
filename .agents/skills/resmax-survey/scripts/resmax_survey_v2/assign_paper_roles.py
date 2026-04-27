from __future__ import annotations

import argparse
from pathlib import Path

from .phase4_roi import assign_paper_roles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assign Phase 4 role-aware paper roles and matrices.")
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    result = assign_paper_roles(pack=args.pack, out=args.out)
    print(f"[survey-v2] paper roles assignments={result['paper_role_assignments']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
