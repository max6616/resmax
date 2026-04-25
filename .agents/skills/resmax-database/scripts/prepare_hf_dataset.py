#!/usr/bin/env python3
"""Prepare a Hugging Face dataset mirror for Resmax artifacts.

The runtime contract stays under paper_database/. This script creates a
Hub-shaped mirror directory that can be uploaded directly with:

  hf upload <repo-id> cache/huggingface/resmax . --repo-type dataset
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_under(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"refusing to write outside output directory: {path}") from exc


def reset_path(path: Path, root: Path) -> None:
    ensure_under(path, root)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def link_or_copy_file(src: Path, dst: Path, *, root: Path, mode: str) -> str:
    if not src.exists():
        raise FileNotFoundError(src)
    ensure_under(dst, root)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        if dst.is_file() and src.samefile(dst):
            return "existing"
        reset_path(dst, root)
    if mode == "copy":
        shutil.copy2(src, dst)
        return "copied"
    if mode == "symlink":
        os.symlink(src.resolve(), dst)
        return "symlinked"
    try:
        os.link(src, dst)
        return "hardlinked"
    except OSError:
        shutil.copy2(src, dst)
        return "copied"


def link_or_copy_tree(src_dir: Path, dst_dir: Path, *, root: Path, mode: str) -> dict[str, int]:
    if not src_dir.is_dir():
        raise FileNotFoundError(src_dir)
    reset_path(dst_dir, root)
    counts = {"files": 0, "hardlinked": 0, "copied": 0, "symlinked": 0, "existing": 0}
    for src in sorted(p for p in src_dir.rglob("*") if p.is_file()):
        rel = src.relative_to(src_dir)
        action = link_or_copy_file(src, dst_dir / rel, root=root, mode=mode)
        counts["files"] += 1
        counts[action] = counts.get(action, 0) + 1
    return counts


def render_dataset_card(manifest: dict, review_manifest: dict, *, manifest_sha256: str) -> str:
    csv_info = manifest.get("csv", {})
    coverage = manifest.get("coverage", {})
    embedding = manifest.get("embedding", {})
    embedding_meta = embedding.get("meta", {}) if isinstance(embedding.get("meta"), dict) else {}
    rows = csv_info.get("rows", "")
    columns = csv_info.get("columns", "")
    source_report = manifest.get("source_report", {})
    source_status = source_report.get("source_status", {})
    source_cohorts = len(source_status) if isinstance(source_status, dict) else ""
    review_rows = review_manifest.get("accepted_review_rows", "")
    review_files = review_manifest.get("review_json_files", "")
    missing_review_files = review_manifest.get("missing_review_files", "")
    orphaned_review_files = review_manifest.get("orphaned_review_files", "")
    embedding_model = embedding_meta.get("model_name") or embedding.get("model_name", "")
    embedding_dim = embedding.get("embedding_dim") or embedding_meta.get("dimension", "")
    embedding_count = embedding.get("cached_papers") or embedding_meta.get("count", "")
    csv_sha = csv_info.get("sha256", "")
    manifest_sha = manifest_sha256
    embedding_sha = embedding.get("sha256", "")

    return f"""---
pretty_name: Resmax Paper Database
language:
- en
tags:
- ai
- scholarly-metadata
- literature-review
- research-agent
- information-retrieval
- embeddings
- openreview
size_categories:
- 10K<n<100K
---

# Resmax Paper Database

This private dataset stores the generated data artifacts for
[resmax](https://github.com/max6616/resmax), an autonomous literature
infrastructure for AI research agents.

The GitHub repository contains the reproducible agent skills and scripts. This
Hugging Face dataset contains the large, gitignored runtime artifacts consumed
by those skills: the canonical paper index, the embedding cache, and the
packaged OpenReview review cache.

## What Is Included

| Path | Description |
| --- | --- |
| `accepted_index.csv` | Canonical paper index produced by `resmax-database`; CSV is the single source of truth for paper metadata. |
| `manifest.json` | Reproducibility manifest for the local database snapshot, including source registry hash, CSV hash, coverage stats, and embedding metadata. |
| `qwen3_8b.npz` | Qwen3-Embedding-8B vector cache aligned with `accepted_index.csv` by `paper_id`. |
| `reviews/` | Hugging Face-friendly review package: review shards, row-level indices, manifest, checksums, and restore instructions. |

This dataset is intended to be downloaded into a `resmax` checkout as
`paper_database/` artifacts, not as a standalone benchmark.

## Snapshot Summary

- Paper rows: `{rows}`
- CSV columns: `{columns}`
- Source registry cohorts: `{source_cohorts}`
- Valid abstract coverage: `{coverage.get('valid_abstract_pct', '')}%`
- PDF available coverage: `{coverage.get('pdf_available_pct', '')}%`
- Source text evidence coverage: `{coverage.get('source_text_evidence_pct', '')}%`
- DOI coverage: `{coverage.get('doi_pct', '')}%`
- Rows with packaged OpenReview reviews: `{review_rows}`
- Review JSON files packaged: `{review_files}`
- Missing review JSON files referenced by CSV: `{missing_review_files}`
- Review JSON files not referenced by CSV: `{orphaned_review_files}`
- Embedding model: `{embedding_model}`
- Embedding dimension: `{embedding_dim}`
- Embedding rows: `{embedding_count}`

Important hashes:

| Artifact | SHA256 |
| --- | --- |
| `accepted_index.csv` | `{csv_sha}` |
| `manifest.json` | `{manifest_sha}` |
| `qwen3_8b.npz` | `{embedding_sha}` |

Review package checksums are stored in `reviews/checksums.sha256`.

## Relationship To Resmax

Resmax is organized as three decoupled agent skills:

1. `resmax-database` builds and validates `accepted_index.csv` plus review
   metadata.
2. `resmax-embedding` builds a vector cache over title and abstract text.
3. `resmax-survey` combines keyword retrieval and embedding retrieval to
   produce topic-level literature surveys.

This dataset provides the persisted outputs for the first two stages so a
consumer can restore a survey-ready local checkout without rebuilding the full
database and embedding cache from scratch.

## Restore Into A Resmax Checkout

From a local `resmax` checkout, ask your agent to use the `resmax-init` skill:

> Use `resmax-init` to initialize this checkout to `survey-ready`.

The skill asks whether you have a read token for this private dataset. If you
do, it calls the unified data command internally. For manual debugging without
an agent, the equivalent command is:

```bash
python3 .agents/skills/resmax-init/scripts/resmax_init_check.py --materialize --with-data
```

The command downloads into the internal `cache/` directory, materializes the
runtime artifacts under `paper_database/`, restores raw review JSON files to:

```text
paper_database/reviews/{{conf_year}}/{{forum_id}}.json
```

and runs the database validator. The `cache/` directory is only a transfer
implementation detail; existing `resmax-database` and `resmax-survey` skills
continue to read `paper_database/`.

## Data Schema

`accepted_index.csv` contains 66 columns. Core fields include:

- identity: `paper_id`, `short_id`, `venue`, `year`, `conf_year`
- bibliographic metadata: `title`, `authors`, `doi`, `arxiv_id`,
  `openreview_forum_id`
- source links: `paper_link`, `landing_url`, `pdf_url`, `source_text_url`
- source status: `pdf_status`, `pdf_source`, `source_text_status`,
  `source_text_evidence`
- content fields: `keywords_raw`, `abstract_raw`, `abstract_status`
- acceptance metadata: `decision`, `acceptance_type`, `topic`
- code signals: `code_url`, `code_is_real`, `code_stars`,
  `code_primary_language`, `code_last_commit`
- review fields: `review_available`, `review_detail_path`,
  `review_score_status`, `review_score_mean`, `review_scores`,
  `review_confidence_mean`

The `.npz` embedding cache is row-addressed by `paper_id` and stores vectors
generated from the title and abstract text. It is validated against the CSV by
`manifest.json`.

## Review Package

The raw OpenReview JSON cache contains many small files, so it is uploaded as
compressed shards rather than as individual JSON files. The `reviews/` folder
contains `reviews_index.csv`, `reviews_index.parquet`,
`reviews_manifest.json`, `checksums.sha256`, and
`archives/reviews_<conf_year>.tar.zst`.

Each index row maps a paper to the archive and tar member containing the raw
review JSON payload. Use `reviews/checksums.sha256` after download to verify
the package before restoring.

## Limitations

- Coverage is defined by the current `resmax-database` source registry, not by
  every possible AI conference, journal, workshop, or arXiv paper.
- Some source records intentionally preserve publisher or official landing
  pages when no reliable direct PDF/preprint URL was available.
- DOI coverage depends on upstream metadata availability and is not complete.
- OpenReview review data is available only for supported OpenReview venues and
  years.
- The embedding cache should be regenerated whenever `title` or `abstract_raw`
  changes materially.

## Intended Use

Use this dataset to restore a private resmax paper database for
agent-assisted literature retrieval, topic-level research surveys, metadata
coverage audits, reproducible testing of the resmax skills, and
embedding-backed semantic search over the indexed papers.

Do not treat this dataset as an authoritative venue-completeness benchmark
without auditing the source registry for your target venue/year scope.

## Provenance

The artifacts are produced by the `resmax` local workflow:

- `resmax-database`: accepted-list ingestion, enrichment, normalization, review
  packaging, and validation
- `resmax-embedding`: Qwen3-Embedding-8B cache generation
- `resmax-survey`: downstream retrieval and ranking consumer

Source metadata is assembled from public venue listings and scholarly metadata
providers such as OpenReview, OpenAlex, Semantic Scholar, arXiv, publisher
pages, and official conference or journal pages where applicable.

## License And Use Constraints

The resmax code repository is released under the MIT License. The dataset
contains bibliographic metadata, links, embeddings, and packaged review payloads
derived from third-party sources. Downstream users should respect the terms of
the original sources and the access policy of this private repository.
"""


def prepare(args: argparse.Namespace) -> dict:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for legacy_dir in ("data", "embeddings"):
        reset_path(out_dir / legacy_dir, out_dir)

    csv_path = Path(args.csv)
    manifest_path = Path(args.manifest)
    embedding_path = Path(args.embedding)
    reviews_package_dir = Path(args.reviews_package)
    review_manifest_path = reviews_package_dir / "reviews_manifest.json"

    manifest = load_json(manifest_path)
    review_manifest = load_json(review_manifest_path)
    card = render_dataset_card(
        manifest,
        review_manifest,
        manifest_sha256=sha256_file(manifest_path),
    )
    readme_path = out_dir / "README.md"
    readme_path.write_text(card, encoding="utf-8")

    actions = {
        "README.md": "generated",
        "manifest.json": link_or_copy_file(
            manifest_path,
            out_dir / "manifest.json",
            root=out_dir,
            mode=args.mode,
        ),
        "accepted_index.csv": link_or_copy_file(
            csv_path,
            out_dir / "accepted_index.csv",
            root=out_dir,
            mode=args.mode,
        ),
        "qwen3_8b.npz": link_or_copy_file(
            embedding_path,
            out_dir / embedding_path.name,
            root=out_dir,
            mode=args.mode,
        ),
        "reviews/": link_or_copy_tree(
            reviews_package_dir,
            out_dir / "reviews",
            root=out_dir,
            mode=args.mode,
        ),
    }
    return actions


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", default="paper_database/accepted_index.csv")
    p.add_argument("--manifest", default="paper_database/manifest.json")
    p.add_argument("--embedding", default="paper_database/embedding_cache/qwen3_8b.npz")
    p.add_argument("--reviews-package", default="paper_database/hf_export/reviews")
    p.add_argument("--out-dir", default="cache/huggingface/resmax")
    p.add_argument("--mode", choices=["hardlink", "copy", "symlink"], default="hardlink")
    p.add_argument("--hf-repo-id", default="max6616/resmax")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    actions = prepare(args)
    print(json.dumps({"out_dir": args.out_dir, "actions": actions}, indent=2), flush=True)
    print("", flush=True)
    print("Upload with:", flush=True)
    print(
        f"  hf upload {args.hf_repo_id} {args.out_dir} . "
        "--repo-type dataset --commit-message \"upload resmax dataset artifacts\"",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
