#!/usr/bin/env python3
"""Audit a Resmax checkout for first-time initialization gaps."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ENV_LINE_RE = re.compile(
    r"""^
    (?:export\s+)?
    (?P<key>[A-Za-z_][A-Za-z0-9_]*)
    \s*=\s*
    (?P<value>.*?)
    \s*$
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Field:
    key: str
    env_file: str
    level: str
    purpose: str
    ask: str = "free_text"
    default: str = ""


FIELDS: tuple[Field, ...] = (
    Field(
        "OPENREVIEW_USERNAME",
        ".secrets/openreview.env",
        "conditional_required",
        "OpenReview review fetch mode",
    ),
    Field(
        "OPENREVIEW_PASSWORD",
        ".secrets/openreview.env",
        "conditional_required",
        "OpenReview review fetch mode",
    ),
    Field(
        "GITHUB_TOKEN",
        ".secrets/github.env",
        "soft",
        "GitHub code quality enrichment; unauthenticated limit is 60 req/h",
    ),
    Field(
        "OPENALEX_API_KEY",
        ".secrets/openalex.env",
        "soft_recommended",
        "OpenAlex journal indexing and faster metadata enrichment",
    ),
    Field(
        "S2_API_KEY",
        ".secrets/s2.env",
        "soft_recommended",
        "Semantic Scholar enrichment with higher rate limits",
    ),
    Field(
        "SERPAPI_KEY",
        ".secrets/serpapi.env",
        "soft",
        "Google fallback for unresolved abstracts",
    ),
    Field(
        "RESMAX_CONTACT_EMAIL",
        ".secrets/contact.env",
        "soft_recommended",
        "polite API User-Agent contact email",
    ),
    Field(
        "RESMAX_SSH_HOST",
        ".localconfig/server.env",
        "conditional_required",
        "remote GPU embedding build or SSH query-encoding fallback",
    ),
    Field(
        "RESMAX_SSH_REMOTE_DIR",
        ".localconfig/server.env",
        "soft_default",
        "remote working directory for embedding scripts",
        default="~/resmax_embedding_build",
    ),
    Field(
        "RESMAX_SSH_REMOTE_SCRIPT",
        ".localconfig/server.env",
        "soft_default",
        "remote query encoder path",
        default="~/resmax_embedding_build/scripts/encode_query.py",
    ),
    Field(
        "RESMAX_SSH_CONDA_ENV",
        ".localconfig/server.env",
        "soft_default",
        "remote conda environment",
        default="llm",
    ),
    Field(
        "RESMAX_SSH_CONDA_INIT",
        ".localconfig/server.env",
        "soft_default",
        "remote conda init script",
        default="~/miniconda3/etc/profile.d/conda.sh",
    ),
    Field(
        "RESMAX_HF_DATASET_REPO",
        ".localconfig/huggingface.env",
        "conditional_required",
        "download review packages from a Hugging Face dataset repo",
    ),
    Field(
        "RESMAX_HF_REVIEWS_PATH",
        ".localconfig/huggingface.env",
        "soft_default",
        "path to review package inside the Hugging Face repo",
        default="reviews",
    ),
    Field(
        "RESMAX_HF_REPO_TYPE",
        ".localconfig/huggingface.env",
        "soft_default",
        "Hugging Face repository type for review packages",
        default="dataset",
    ),
)


ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    ("accepted_index", "paper_database/accepted_index.csv", "database index"),
    ("manifest", "paper_database/manifest.json", "database manifest"),
    ("embedding_cache", "paper_database/embedding_cache/qwen3_8b.npz", "survey embedding cache"),
    ("reviews_package_manifest", "paper_database/hf_export/reviews/reviews_manifest.json", "local HF review package manifest"),
    ("reviews_package_index", "paper_database/hf_export/reviews/reviews_index.csv", "local HF review package index"),
    ("validate_report", "paper_database/validate_report.json", "latest validation report"),
)


def find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists() or (parent / ".agents").is_dir():
            return parent
    raise SystemExit(f"Could not locate resmax repository root from {start}")


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE_RE.match(line)
        if not match:
            continue
        data[match.group("key")] = strip_quotes(match.group("value"))
    return data


def materialize_env_files(root: Path) -> list[str]:
    created: list[str] = []
    for pattern in (".secrets/*.env.example", ".localconfig/*.env.example"):
        for example in sorted(root.glob(pattern)):
            target = example.with_name(example.name.removesuffix(".example"))
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(example, target)
            if target.parts[-2] == ".secrets":
                target.chmod(stat.S_IRUSR | stat.S_IWUSR)
            created.append(str(target.relative_to(root)))
    return created


def audit_env(root: Path) -> list[dict[str, Any]]:
    cache: dict[str, dict[str, str]] = {}
    rows: list[dict[str, Any]] = []
    for field in FIELDS:
        path = root / field.env_file
        if field.env_file not in cache:
            cache[field.env_file] = parse_env(path)
        value = os.environ.get(field.key) or cache[field.env_file].get(field.key, "")
        rows.append(
            {
                "key": field.key,
                "env_file": field.env_file,
                "example_file": field.env_file + ".example",
                "file_exists": path.exists(),
                "present": bool(value),
                "level": field.level,
                "purpose": field.purpose,
                "ask": field.ask,
                "default": field.default,
            }
        )
    return rows


def count_review_json(root: Path) -> int:
    reviews_dir = root / "paper_database/reviews"
    if not reviews_dir.is_dir():
        return 0
    return sum(1 for path in reviews_dir.rglob("*.json") if path.is_file())


def audit_artifacts(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, rel_path, purpose in ARTIFACTS:
        path = root / rel_path
        rows.append(
            {
                "name": name,
                "path": rel_path,
                "exists": path.exists(),
                "purpose": purpose,
                "size_bytes": path.stat().st_size if path.is_file() else None,
            }
        )
    review_json_count = count_review_json(root)
    rows.append(
        {
            "name": "raw_review_json",
            "path": "paper_database/reviews/**/*.json",
            "exists": review_json_count > 0,
            "purpose": "raw OpenReview JSON cache",
            "count": review_json_count,
        }
    )
    return rows


def should_prompt_env(row: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> tuple[bool, bool, str]:
    if row["present"] or row["level"] == "soft_default":
        return False, False, ""
    if row["level"] in {"soft", "soft_recommended"}:
        return True, False, "optional enrichment"
    key = row["key"]
    reviews_missing = (
        not artifacts.get("raw_review_json", {}).get("exists")
        and not artifacts.get("reviews_package_manifest", {}).get("exists")
    )
    embedding_missing = not artifacts.get("embedding_cache", {}).get("exists")
    if key in {"OPENREVIEW_USERNAME", "OPENREVIEW_PASSWORD"}:
        return reviews_missing, False, "only if review_source=openreview-fetch"
    if key == "RESMAX_HF_DATASET_REPO":
        return reviews_missing, False, "only if review_source=huggingface"
    if key == "RESMAX_SSH_HOST":
        return embedding_missing, False, "only if embedding_source=remote-build or SSH query fallback is needed"
    return False, False, ""


def suggested_questions(env_rows: list[dict[str, Any]], artifact_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_artifact = {row["name"]: row for row in artifact_rows}
    questions: list[dict[str, Any]] = [
        {
            "id": "init_goal",
            "type": "choice",
            "required": True,
            "prompt": "初始化目标是什么？",
            "options": ["config-only", "database-ready", "survey-ready", "embedding-build"],
        },
        {
            "id": "sci_hub_policy",
            "type": "choice",
            "required": True,
            "prompt": "是否允许 Sci-Hub 灰色 fallback？默认关闭。",
            "options": ["disabled", "ask-each-time", "enabled-for-this-run"],
            "recommended": "disabled",
        },
    ]
    if not by_artifact.get("accepted_index", {}).get("exists") or not by_artifact.get("manifest", {}).get("exists"):
        questions.append(
            {
                "id": "database_source",
                "type": "choice",
                "required": True,
                "prompt": "数据库索引缺失，使用哪种来源补齐？",
                "options": ["local-copy", "build-from-sources", "skip-now"],
            }
        )
    if not by_artifact.get("raw_review_json", {}).get("exists") and not by_artifact.get("reviews_package_manifest", {}).get("exists"):
        questions.append(
            {
                "id": "review_source",
                "type": "choice",
                "required": False,
                "prompt": "评审 JSON / package 缺失，如何补齐？",
                "options": ["local-package", "huggingface", "openreview-fetch", "skip-now"],
            }
        )
    if not by_artifact.get("embedding_cache", {}).get("exists"):
        questions.append(
            {
                "id": "embedding_source",
                "type": "choice",
                "required": False,
                "prompt": "embedding cache 缺失，如何处理？",
                "options": ["local-copy", "remote-build", "skip-production"],
            }
        )
    for row in env_rows:
        should_prompt, required, condition = should_prompt_env(row, by_artifact)
        if not should_prompt:
            continue
        questions.append(
            {
                "id": row["key"],
                "type": "free_text",
                "required": required,
                "prompt": f"{row['key']} is missing; needed for {row['purpose']}. Store in {row['env_file']}.",
                "env_file": row["env_file"],
                "level": row["level"],
                "condition": condition,
            }
        )
    return questions


def build_report(root: Path, created: list[str]) -> dict[str, Any]:
    env_rows = audit_env(root)
    artifact_rows = audit_artifacts(root)
    return {
        "repo_root": str(root),
        "created_env_files": created,
        "env": env_rows,
        "artifacts": artifact_rows,
        "suggested_questions": suggested_questions(env_rows, artifact_rows),
    }


def print_markdown(report: dict[str, Any]) -> None:
    print("# resmax-init audit")
    print()
    print(f"- repo_root: `{report['repo_root']}`")
    if report["created_env_files"]:
        print(f"- created_env_files: {', '.join('`' + item + '`' for item in report['created_env_files'])}")
    else:
        print("- created_env_files: none")
    print()
    print("## Env fields")
    for row in report["env"]:
        status = "ok" if row["present"] else "missing"
        print(f"- `{row['key']}`: {status}; level={row['level']}; file=`{row['env_file']}`")
    print()
    print("## Artifacts")
    for row in report["artifacts"]:
        status = "ok" if row["exists"] else "missing"
        suffix = f"; count={row['count']}" if "count" in row else ""
        print(f"- `{row['path']}`: {status}{suffix}; {row['purpose']}")
    print()
    print("## Suggested questions")
    for question in report["suggested_questions"]:
        if question["type"] == "choice":
            print(f"- [{question['id']}] choice: {question['prompt']} options={question['options']}")
        else:
            print(f"- [{question['id']}] free_text: {question['prompt']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default="", help="Override repository root")
    parser.add_argument("--materialize", action="store_true", help="Create missing .env files from tracked templates")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve() if args.repo_root else find_repo_root(Path.cwd())
    created = materialize_env_files(root) if args.materialize else []
    report = build_report(root, created)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_markdown(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
