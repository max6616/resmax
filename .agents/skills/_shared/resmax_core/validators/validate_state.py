from __future__ import annotations

import argparse
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from validators.common import print_errors, validate_json_file  # type: ignore
else:
    from .common import print_errors, validate_json_file


def run(schema_path: Path, input_path: Path) -> int:
    try:
        errors = validate_json_file(input_path, schema_path)
    except Exception as exc:
        print(f"ERROR $: {exc}", file=sys.stderr)
        return 2
    if errors:
        print_errors(errors)
        return 1
    print(f"OK {input_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate one Resmax JSON state artifact.")
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)
    return run(args.schema, args.input)


if __name__ == "__main__":
    raise SystemExit(main())
