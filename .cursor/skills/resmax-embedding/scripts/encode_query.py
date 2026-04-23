#!/usr/bin/env python3
"""Encode a query string into an embedding vector using the same model as the cache.

Designed to run on the GPU server and be invoked over SSH from the client
(the exact SSH host, remote path, and conda env are configured in
`.localconfig/server.env` — see SECRETS.md). Example invocation:

  ssh <RESMAX_SSH_HOST> \\
    "source <RESMAX_SSH_CONDA_INIT> && conda activate <RESMAX_SSH_CONDA_ENV> && \\
     HF_HUB_OFFLINE=1 python3 <RESMAX_SSH_REMOTE_SCRIPT> --query 'your query text'"

Accepts the query as either `--query <text>` or as the first positional argument.
Prints the embedding as a JSON list of floats to stdout; loading logs go to stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _pick_free_gpu(min_free_mib: int = 20000) -> str:
    """Pick the first GPU with >= `min_free_mib` MiB free memory via nvidia-smi.

    Returns a torch device string like ``cuda:1``. Falls back to ``cuda:0`` if
    no GPU meets the threshold (lets torch raise a clearer OOM if it comes to
    that). Qwen3-Embedding-8B in INT8 needs roughly 16 GB free to load safely.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        candidates: list[tuple[int, int]] = []
        for line in out.splitlines():
            idx_str, free_str = [p.strip() for p in line.split(",")]
            candidates.append((int(idx_str), int(free_str)))
        candidates.sort(key=lambda t: -t[1])
        for idx, free in candidates:
            if free >= min_free_mib:
                return f"cuda:{idx}"
    except Exception as exc:
        print(f"[encode_query] warning: nvidia-smi probe failed: {exc}", file=sys.stderr)
    return "cuda:0"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Encode a query into an embedding vector (stdout = JSON list of floats).",
    )
    p.add_argument(
        "query_pos",
        nargs="?",
        default="",
        help="Query text (positional). Overridden by --query if both are given.",
    )
    p.add_argument("--query", default="", help="Query text (flag form). Preferred.")
    p.add_argument("--model", default="Qwen/Qwen3-Embedding-8B")
    p.add_argument(
        "--device",
        default="auto",
        help="'auto' picks the first GPU with >= 20 GiB free via nvidia-smi.",
    )
    p.add_argument("--dim", type=int, default=0, help="Truncate to dim (0=full).")
    return p.parse_args()


def main():
    args = _parse_args()
    query = args.query or args.query_pos
    if not query:
        print(
            "Usage: encode_query.py --query <text> [--model MODEL] [--device DEVICE] [--dim N]",
            file=sys.stderr,
        )
        sys.exit(1)

    model_name = args.model
    device = args.device
    dim = args.dim

    if device == "auto":
        device = _pick_free_gpu()

    # Default to offline mode: the model is pre-cached on the GPU server and
    # reaching HuggingFace / hf-mirror.com from the server network can hang.
    # Callers who really want online resolution can set HF_HUB_OFFLINE=0.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ["TRANSFORMERS_VERBOSITY"] = "error"

    import torch
    from transformers import AutoTokenizer, AutoModel, BitsAndBytesConfig

    print(f"loading {model_name} on {device}...", file=sys.stderr)
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    quant_config = BitsAndBytesConfig(load_in_8bit=True)
    model = AutoModel.from_pretrained(
        model_name, trust_remote_code=True,
        quantization_config=quant_config,
        device_map={"": torch.device(device)},
    )
    model.eval()

    encoded = tokenizer(
        [query], padding=True, truncation=True,
        max_length=8192, return_tensors="pt",
    ).to(torch.device(device))

    with torch.no_grad():
        outputs = model(**encoded)
        last_hidden = outputs.last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1).to(last_hidden.dtype)
        emb = (last_hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        emb = torch.nn.functional.normalize(emb, p=2, dim=1)
        vec = emb.cpu().float().numpy()[0]

    if dim and len(vec) > dim:
        vec = vec[:dim]
        norm = (vec ** 2).sum() ** 0.5
        if norm > 0:
            vec = vec / norm

    # Print as JSON list to stdout — stderr has the loading logs
    print(json.dumps(vec.tolist()))


if __name__ == "__main__":
    main()
