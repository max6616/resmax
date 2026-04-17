#!/usr/bin/env python3
"""Encode a query string into an embedding vector using the same model as the cache.

Usage (called via SSH from MacBook):
  ssh 5090 "cd ~/resmax_embedding_build && conda run -n llm python scripts/encode_query.py 'your query text here'"

Prints the embedding as a JSON list of floats to stdout.
"""
from __future__ import annotations

import json
import os
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: encode_query.py <query_text> [--model MODEL] [--device DEVICE]", file=sys.stderr)
        sys.exit(1)

    query = sys.argv[1]
    model_name = "Qwen/Qwen3-Embedding-8B"
    device = "cuda:0"
    dim = 0

    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            model_name = args[i + 1]; i += 2
        elif args[i] == "--device" and i + 1 < len(args):
            device = args[i + 1]; i += 2
        elif args[i] == "--dim" and i + 1 < len(args):
            dim = int(args[i + 1]); i += 2
        else:
            i += 1

    import torch
    from transformers import AutoTokenizer, AutoModel, BitsAndBytesConfig

    os.environ["TRANSFORMERS_VERBOSITY"] = "error"

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
