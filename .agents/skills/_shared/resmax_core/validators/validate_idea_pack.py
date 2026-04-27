from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from validators.common import validate_json_file  # type: ignore
else:
    from .common import validate_json_file


SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
REQUIRED_PORTFOLIO = {
    "manifest.json",
    "idea_cards.jsonl",
    "idea_lineage.json",
    "closest_work_checks.jsonl",
    "strongest_rejection_cases.md",
    "cheapest_falsification.md",
    "generation_trace.jsonl",
    "idea_report.md",
}


def _validate_named(path: Path | None, schema_name: str, schema_dir: Path) -> list[str]:
    if path is None:
        return []
    if not path.exists():
        return [f"{path}: file does not exist"]
    schema_path = schema_dir / schema_name
    errors = validate_json_file(path, schema_path)
    return [f"{path} {error.format()}" for error in errors]


def run(
    *,
    idea_card: Path | None = None,
    ideas: Path | None = None,
    review_trace: Path | None = None,
    experiment_blueprint: Path | None = None,
    negative_memory: Path | None = None,
    schema_dir: Path = SCHEMA_DIR,
) -> int:
    errors: list[str] = []
    if ideas is not None:
        errors.extend(_validate_portfolio(ideas, schema_dir))
    else:
        errors.extend(_validate_named(idea_card, "idea_card.schema.json", schema_dir))
    errors.extend(_validate_named(review_trace, "review_trace.schema.json", schema_dir))
    errors.extend(_validate_named(experiment_blueprint, "experiment_blueprint.schema.json", schema_dir))
    errors.extend(_validate_named(negative_memory, "negative_memory.schema.json", schema_dir))
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(f"OK {ideas or idea_card}")
    return 0


def _validate_portfolio(ideas: Path, schema_dir: Path) -> list[str]:
    errors: list[str] = []
    missing = [name for name in sorted(REQUIRED_PORTFOLIO) if not (ideas / name).exists()]
    errors.extend(f"{ideas / name}: required artifact missing" for name in missing)
    if missing:
        return errors
    manifest = _load_json(ideas / "manifest.json")
    if isinstance(manifest, dict):
        errors.extend(_validate_hashes(ideas, manifest))
    schema_path = schema_dir / "idea_card.schema.json"
    for line_no, card in _read_jsonl(ideas / "idea_cards.jsonl"):
        tmp = ideas / f".idea_card_line_{line_no}.json"
        tmp.write_text(json.dumps(card, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        try:
            errors.extend(f"idea_cards.jsonl line {line_no} {error.format()}" for error in validate_json_file(tmp, schema_path))
        finally:
            tmp.unlink(missing_ok=True)
    return errors


def _validate_hashes(ideas: Path, manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for artifact in manifest.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        rel_path = artifact.get("path", "")
        path = ideas / rel_path
        if not path.exists():
            errors.append(f"manifest artifact missing: {rel_path}")
            continue
        expected = artifact.get("sha256", "")
        actual = _sha256_file(path)
        if expected and expected != actual:
            errors.append(f"manifest sha256 mismatch for {rel_path}: expected {expected}, got {actual}")
    return errors


def _read_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            rows.append((line_no, value if isinstance(value, dict) else {}))
    return rows


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Resmax idea pack subset.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--idea-card", type=Path)
    target.add_argument("--ideas", type=Path)
    parser.add_argument("--review-trace", type=Path)
    parser.add_argument("--experiment-blueprint", type=Path)
    parser.add_argument("--negative-memory", type=Path)
    parser.add_argument("--schema-dir", type=Path, default=SCHEMA_DIR)
    args = parser.parse_args(argv)
    return run(
        idea_card=args.idea_card,
        ideas=args.ideas,
        review_trace=args.review_trace,
        experiment_blueprint=args.experiment_blueprint,
        negative_memory=args.negative_memory,
        schema_dir=args.schema_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
