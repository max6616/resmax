#!/usr/bin/env python3
"""Lightweight abstract-based openness scan.

Strategy — pure local keyword/regex scan of abstract_raw:
  - has_pretrained_weights: yes / no_promise / unknown
    * yes: explicit URL (HF / Zenodo / Drive / GitHub release) or
      release-weight phrase without a negative qualifier
    * no_promise: phrase like "will release upon acceptance" without
      an actual release URL
    * unknown: no signal
  - has_dataset: public / private / standard_only / unknown
    * public: explicit dataset release phrase or URL
    * private: explicit proprietary/private dataset phrase
    * standard_only: 2+ well-known benchmark names but no release phrase
    * unknown: no signal

Intentionally excludes (moved to resmax-survey/meta_enrich deepcheck):
  - HuggingFace Hub API lookups (useful for S/A papers only)
  - PWC datasets dump cross-match (coverage already weak after PWC shutdown)

Zero network. Deterministic. Fast (~1s per 10k abstracts).

Usage:
  python3 enrich_openness.py --csv paper_database/accepted_index.csv
  python3 enrich_openness.py --csv ... --filter ICLR_2026 --dry-run
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from pathlib import Path


WEIGHT_URL_PATTERNS = [
    re.compile(r"huggingface\.co/[\w\-]+/[\w\-]+", re.IGNORECASE),
    re.compile(r"hf\.co/[\w\-]+/[\w\-]+", re.IGNORECASE),
    re.compile(r"drive\.google\.com/\S+", re.IGNORECASE),
    re.compile(r"github\.com/[\w\-]+/[\w\-]+/releases", re.IGNORECASE),
    re.compile(r"zenodo\.org/record/\d+", re.IGNORECASE),
    re.compile(r"modelscope\.cn/[\w\-]+/[\w\-]+", re.IGNORECASE),
]

WEIGHT_POSITIVE_PHRASES = [
    "pretrained model", "pre-trained model", "pretrained weight",
    "pre-trained weight", "model checkpoint", "model weights are",
    "release the model", "release our model", "release the weight",
    "release our weight", "publicly available model",
    "available on huggingface", "available on hugging face",
    "download the model", "download our model",
    "we release the trained", "we release our trained",
    "checkpoint is available", "checkpoints are available",
    "weights are available", "weight is available",
    "released the trained", "released pretrained",
]

WEIGHT_NEGATIVE_QUALIFIERS = [
    "will release", "will be released", "upon acceptance",
    "code will be", "not release", "not publicly",
    "plan to release", "we intend to release", "to be released",
]

DATASET_PUBLIC_PHRASES = [
    "publicly available dataset", "public dataset", "open dataset",
    "publicly released dataset", "we release the dataset",
    "we release our dataset", "dataset is publicly",
    "dataset can be downloaded", "dataset is open",
    "open-source dataset", "release the benchmark",
    "release our benchmark", "our dataset is available",
    "the dataset is available",
]

DATASET_PRIVATE_PHRASES = [
    "proprietary dataset", "private dataset", "internal dataset",
    "in-house dataset", "not publicly available",
    "cannot be shared", "not release the data",
    "due to privacy", "due to licensing",
    "confidential dataset", "restricted access dataset",
]

DATASET_URL_PATTERNS = [
    re.compile(r"huggingface\.co/datasets/[\w\-]+/[\w\-]+", re.IGNORECASE),
    re.compile(r"kaggle\.com/datasets/\S+", re.IGNORECASE),
    re.compile(r"opendatalab\.com/\S+", re.IGNORECASE),
]

# Well-known benchmarks. Word-boundary matched so that 'coco' in 'protocol'
# doesn't count. Lowercased; we match on a lowercased abstract.
STANDARD_BENCHMARKS = [
    "imagenet", "coco", "cifar", "cifar-10", "cifar-100",
    "mnist", "fashion-mnist", "svhn", "stl-10",
    "pascal voc", "ade20k", "cityscapes",
    "squad", "glue", "superglue", "mnli", "sst-2", "qqp",
    "librispeech", "commonvoice", "voxceleb",
    "kinetics", "ucf101", "hmdb51",
    "shapenet", "modelnet", "scannet",
    "nuscenes", "kitti", "waymo",
    "openwebtext", "the pile", "redpajama",
    "laion", "cc3m", "cc12m", "conceptual captions",
    "webvid", "howto100m", "msrvtt",
    "humaneval", "mbpp", "gsm8k",
    "mmlu", "hellaswag", "winogrande", "truthfulqa",
    "mt-bench", "alpaca_eval", "chatbot arena",
]
_BENCH_RE = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in STANDARD_BENCHMARKS) + r")\b",
    re.IGNORECASE,
)


def _has_nearby(text_lower: str, target: str, qualifiers: list[str], window: int = 80) -> bool:
    """True if any qualifier appears within `window` chars of target."""
    idx = 0
    while True:
        pos = text_lower.find(target, idx)
        if pos < 0:
            return False
        start = max(0, pos - window)
        end = min(len(text_lower), pos + len(target) + window)
        ctx = text_lower[start:end]
        if any(q in ctx for q in qualifiers):
            return True
        idx = pos + len(target)


def scan_weights(abstract: str) -> str:
    """Return yes / no_promise / unknown."""
    if not abstract:
        return "unknown"
    text_lower = abstract.lower()

    for pat in WEIGHT_URL_PATTERNS:
        if pat.search(abstract):
            return "yes"

    any_positive = False
    any_positive_with_negative = False
    for phrase in WEIGHT_POSITIVE_PHRASES:
        if phrase in text_lower:
            any_positive = True
            if _has_nearby(text_lower, phrase, WEIGHT_NEGATIVE_QUALIFIERS):
                any_positive_with_negative = True
            else:
                return "yes"

    if any_positive and any_positive_with_negative:
        return "no_promise"

    # Pure negative phrase without any positive => no_promise if it mentions
    # release/code intent
    for neg in ["will release", "code will be", "plan to release"]:
        if neg in text_lower:
            return "no_promise"

    return "unknown"


def scan_dataset(abstract: str) -> str:
    """Return public / private / standard_only / unknown."""
    if not abstract:
        return "unknown"
    text_lower = abstract.lower()

    for phrase in DATASET_PRIVATE_PHRASES:
        if phrase in text_lower:
            return "private"

    for pat in DATASET_URL_PATTERNS:
        if pat.search(abstract):
            return "public"

    for phrase in DATASET_PUBLIC_PHRASES:
        if phrase in text_lower:
            return "public"

    benches = {m.group(0).lower() for m in _BENCH_RE.finditer(abstract)}
    if len(benches) >= 2:
        return "standard_only"

    return "unknown"


def main():
    parser = argparse.ArgumentParser(description="Abstract-based openness scan")
    parser.add_argument("--csv", required=True, help="Path to accepted_index.csv")
    parser.add_argument("--filter", default="", help="conf_year substring filter")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-scan even if row already has values",
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't write CSV")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[ERROR] CSV not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    csv.field_size_limit(10 * 1024 * 1024)
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    new_fields = ["has_pretrained_weights", "has_dataset"]
    for nf in new_fields:
        if nf not in fieldnames:
            fieldnames.append(nf)

    conf_filter = args.filter.strip()
    targets = []
    for i, row in enumerate(rows):
        if conf_filter and conf_filter not in row.get("conf_year", ""):
            continue
        targets.append(i)

    need_enrich = targets if args.refresh else [
        i for i in targets
        if not rows[i].get("has_pretrained_weights", "").strip()
        or not rows[i].get("has_dataset", "").strip()
    ]
    print(
        f"[openness] {len(targets)} rows in scope, {len(need_enrich)} need scanning",
        flush=True,
    )
    if not need_enrich:
        print("[openness] nothing to do", flush=True)
        return 0

    w_hit = 0
    d_hit = 0
    for i in need_enrich:
        row = rows[i]
        abstract = row.get("abstract_raw", "") or ""

        if args.refresh or not row.get("has_pretrained_weights", "").strip():
            w = scan_weights(abstract)
            row["has_pretrained_weights"] = w
            if w != "unknown":
                w_hit += 1

        if args.refresh or not row.get("has_dataset", "").strip():
            d = scan_dataset(abstract)
            row["has_dataset"] = d
            if d != "unknown":
                d_hit += 1

    # Stats
    w_stats: dict[str, int] = {}
    d_stats: dict[str, int] = {}
    for i in targets:
        w = rows[i].get("has_pretrained_weights", "unknown") or "unknown"
        d = rows[i].get("has_dataset", "unknown") or "unknown"
        w_stats[w] = w_stats.get(w, 0) + 1
        d_stats[d] = d_stats.get(d, 0) + 1

    print(f"[openness] weight stats: {w_stats}", flush=True)
    print(f"[openness] dataset stats: {d_stats}", flush=True)

    if args.dry_run:
        print("[openness] dry-run, not writing CSV", flush=True)
        return 0

    backup = csv_path.with_suffix(".csv.bak")
    shutil.copy2(csv_path, backup)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"[openness] wrote CSV: {csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
