#!/usr/bin/env python3
"""Fail if a skill bundle contains local/cache artifacts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


BAD_NAMES = {".DS_Store", "Thumbs.db"}
BAD_SUFFIXES = {".pyc", ".pyo"}
BAD_DIRS = {"__pycache__"}


def find_bad_files(root: Path) -> list[str]:
    bad: list[str] = []
    for path in root.rglob("*"):
        rel = str(path.relative_to(root))
        if path.is_dir() and path.name in BAD_DIRS:
            bad.append(rel + "/")
        elif path.is_file() and (path.name in BAD_NAMES or path.suffix in BAD_SUFFIXES):
            bad.append(rel)
    return sorted(bad)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".agents/skills")
    args = parser.parse_args()
    bad = find_bad_files(Path(args.root))
    if bad:
        print("[bundle-check] forbidden artifacts found:", file=sys.stderr)
        for item in bad[:100]:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("[bundle-check] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
