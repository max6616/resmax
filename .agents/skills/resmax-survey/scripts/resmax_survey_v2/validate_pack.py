from __future__ import annotations

import argparse
from pathlib import Path

from resmax_core.validators.validate_research_pack import run

from .phase3_pack import resolve_pack_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Phase 3 research_pack.")
    parser.add_argument("--pack", required=True, type=Path)
    args = parser.parse_args(argv)
    return run(resolve_pack_dir(args.pack) / "manifest.json")


if __name__ == "__main__":
    raise SystemExit(main())
