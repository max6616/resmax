from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from validators.common import load_json, validate_with_schema  # type: ignore
else:
    from .common import load_json, validate_with_schema


def run(schema_path: Path, input_path: Path) -> int:
    try:
        schema = load_json(schema_path)
    except Exception as exc:
        print(f"ERROR $: cannot load schema: {exc}", file=sys.stderr)
        return 2

    had_error = False
    try:
        with input_path.open("r", encoding="utf-8") as f:
            for line_no, raw in enumerate(f, 1):
                if not raw.strip():
                    continue
                try:
                    instance = json.loads(raw)
                except json.JSONDecodeError as exc:
                    print(f"ERROR line {line_no} $: invalid JSON: {exc}")
                    had_error = True
                    continue
                for error in validate_with_schema(instance, schema):
                    print(f"ERROR line {line_no} {error.format()}")
                    had_error = True
    except Exception as exc:
        print(f"ERROR $: cannot read input: {exc}", file=sys.stderr)
        return 2

    if had_error:
        return 1
    print(f"OK {input_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Resmax JSONL state artifacts.")
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)
    return run(args.schema, args.input)


if __name__ == "__main__":
    raise SystemExit(main())
