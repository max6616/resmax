#!/usr/bin/env python3
"""Build embedding cache using INT8 quantized model + multi-GPU data parallel.

Each GPU loads a full INT8 copy of the model (~8GB), then processes 1/4 of the
papers independently. 4x throughput with zero inter-GPU waiting.

Usage (on 4x5090 server):
  python build_cache_multigpu.py --accepted accepted_index.csv --out paper_database/embedding_cache/qwen3_8b.npz
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np


def encode_on_gpu(
    gpu_id: int,
    texts: list[str],
    model_name: str,
    batch_size: int,
    max_length: int,
    shard_dir: str,
):
    """Worker: load INT8 model on one GPU, encode assigned texts, save shard."""
    import torch
    from transformers import AutoTokenizer, AutoModel, BitsAndBytesConfig

    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    device = torch.device("cuda:0")

    print(f"[GPU {gpu_id}] loading INT8 model...")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    quant_config = BitsAndBytesConfig(load_in_8bit=True)
    model = AutoModel.from_pretrained(
        model_name,
        trust_remote_code=True,
        quantization_config=quant_config,
        device_map={"": device},
    )
    model.eval()

    mem_gb = torch.cuda.memory_allocated(0) / 1e9
    print(f"[GPU {gpu_id}] model loaded, VRAM: {mem_gb:.1f} GB, encoding {len(texts)} texts")

    all_embs = []
    num_batches = (len(texts) + batch_size - 1) // batch_size
    t0 = time.time()

    for i in range(num_batches):
        start = i * batch_size
        end = min(start + batch_size, len(texts))
        batch = texts[start:end]

        encoded = tokenizer(
            batch, padding=True, truncation=True,
            max_length=max_length, return_tensors="pt",
        ).to(device)

        with torch.no_grad():
            outputs = model(**encoded)
            last_hidden = outputs.last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).to(last_hidden.dtype)
            emb = (last_hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            emb = torch.nn.functional.normalize(emb, p=2, dim=1)
            all_embs.append(emb.cpu().float().numpy())

        if (i + 1) % 20 == 0 or (i + 1) == num_batches:
            elapsed = time.time() - t0
            speed = end / elapsed
            eta = (len(texts) - end) / speed if speed > 0 else 0
            print(f"[GPU {gpu_id}] {end}/{len(texts)} ({speed:.0f} papers/s, ETA {eta:.0f}s)")

    shard = np.vstack(all_embs)
    shard_path = os.path.join(shard_dir, f"shard_{gpu_id}.npy")
    np.save(shard_path, shard)
    print(f"[GPU {gpu_id}] done, saved shard {shard_path}, shape: {shard.shape}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted", required=True)
    parser.add_argument("--out", default="paper_database/embedding_cache/qwen3_8b.npz")
    parser.add_argument("--model", default="Qwen/Qwen3-Embedding-8B")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=8192)
    parser.add_argument("--dim", type=int, default=0, help="Truncate to dim (0=full)")
    parser.add_argument("--gpus", default="0,1,2,3", help="Comma-separated GPU IDs")
    parser.add_argument("--instruction", default="", help="Instruction prefix for queries")
    args = parser.parse_args()

    import csv
    print(f"[main] loading papers from {args.accepted}")
    with open(args.accepted, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    paper_ids = [r.get("paper_id", "") for r in rows]
    texts = []
    for r in rows:
        t = r.get("title", "").strip()
        a = r.get("abstract_raw", "").strip()
        text = t + ("\n" + a if a else "")
        if args.instruction:
            text = args.instruction + text
        texts.append(text)

    print(f"[main] {len(texts)} papers loaded")

    gpu_ids = [int(g) for g in args.gpus.split(",")]
    num_gpus = len(gpu_ids)
    print(f"[main] using {num_gpus} GPUs: {gpu_ids}")

    # Split texts across GPUs
    chunk_size = (len(texts) + num_gpus - 1) // num_gpus
    chunks = [texts[i * chunk_size:(i + 1) * chunk_size] for i in range(num_gpus)]

    # Launch parallel processes
    import torch.multiprocessing as mp
    mp.set_start_method("spawn", force=True)

    import tempfile
    shard_dir = tempfile.mkdtemp(prefix="emb_shards_")
    print(f"[main] shard temp dir: {shard_dir}")

    t0 = time.time()
    processes = []
    for i, gpu_id in enumerate(gpu_ids):
        p = mp.Process(
            target=encode_on_gpu,
            args=(gpu_id, chunks[i], args.model, args.batch_size, args.max_length, shard_dir),
        )
        p.start()
        processes.append(p)

    for p in processes:
        p.join()

    elapsed = time.time() - t0
    print(f"[main] all GPUs done in {elapsed:.1f}s")

    # Reassemble shards in order
    shards = []
    for gpu_id in gpu_ids:
        shard_path = os.path.join(shard_dir, f"shard_{gpu_id}.npy")
        shards.append(np.load(shard_path))
        os.remove(shard_path)
    os.rmdir(shard_dir)
    all_embeddings = np.vstack(shards)

    if args.dim and all_embeddings.shape[1] > args.dim:
        all_embeddings = all_embeddings[:, :args.dim]
        norms = np.linalg.norm(all_embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        all_embeddings = all_embeddings / norms
        print(f"[main] truncated to dim={args.dim}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        embeddings=all_embeddings.astype(np.float32),
        paper_ids=np.array(paper_ids, dtype=object),
        meta=json.dumps({
            "model_name": args.model,
            "dimension": all_embeddings.shape[1],
            "count": len(paper_ids),
        }),
    )
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[main] saved: {out_path} ({size_mb:.1f} MB), shape: {all_embeddings.shape}")
    print(f"[main] throughput: {len(texts) / elapsed:.0f} papers/s")


if __name__ == "__main__":
    main()
