#!/usr/bin/env python3
"""Build embedding cache using INT8 quantized model + multi-GPU data parallel.

Each GPU loads a full INT8 copy of the model (~8GB), then processes 1/4 of the
papers independently. 4x throughput with zero inter-GPU waiting.

Usage (on 4x5090 server):
  python build_cache_multigpu.py --accepted accepted_index.csv --out paper_database/embedding_cache/qwen3_8b.npz
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np


def is_valid_abstract(raw: str) -> bool:
    text = (raw or "").strip()
    if not text:
        return False
    if text.lower() in {"none", "null", "nan", "n/a", "international audience"}:
        return False
    return len(text) >= 10


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_cache(out_path: Path, embeddings: np.ndarray, paper_ids: list[str], model_name: str, accepted_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        embeddings=embeddings.astype(np.float32),
        paper_ids=np.array(paper_ids, dtype=np.str_),
        meta=json.dumps({
            "model_name": model_name,
            "dimension": embeddings.shape[1],
            "count": len(paper_ids),
            "accepted_csv_sha256": _sha256_file(accepted_path),
            "paper_id_dtype": "str",
        }),
    )


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
        all_rows = list(csv.DictReader(f))
    rows = [r for r in all_rows if r.get("paper_id", "") and is_valid_abstract(r.get("abstract_raw", ""))]

    all_paper_ids = [r.get("paper_id", "") for r in rows]
    all_texts = []
    for r in rows:
        t = r.get("title", "").strip()
        a = r.get("abstract_raw", "").strip()
        text = t + ("\n" + a if a else "")
        if args.instruction:
            text = args.instruction + text
        all_texts.append(text)

    print(f"[main] {len(all_texts)} queryable papers loaded ({len(all_rows)} CSV rows)")

    out_path = Path(args.out)
    existing_embs = None
    existing_ids = None
    full_rebuild = False

    if out_path.exists():
        try:
            cache = np.load(out_path, allow_pickle=False)
            existing_embs = cache["embeddings"]
            existing_ids = [str(x) for x in cache["paper_ids"].tolist()]
            cached_dim = existing_embs.shape[1]
            target_dim = args.dim if args.dim > 0 else None
            if target_dim and cached_dim != target_dim:
                print(f"[main] dimension mismatch: cache={cached_dim}, target={target_dim}. Full rebuild.")
                full_rebuild = True
                existing_embs = None
                existing_ids = None
            else:
                print(f"[main] existing cache: {existing_embs.shape[0]} papers, dim={cached_dim}")
                target_ids = set(all_paper_ids)
                cached_ids = set(existing_ids)
                orphaned = cached_ids - target_ids
                if orphaned:
                    print(f"[main] cache has {len(orphaned)} orphaned paper_ids. Full rebuild.")
                    full_rebuild = True
                    existing_embs = None
                    existing_ids = None
        except Exception as e:
            print(f"[main] failed to load existing cache: {e}. Full rebuild.")
            full_rebuild = True

    if existing_ids and not full_rebuild:
        existing_set = set(existing_ids)
        new_indices = [i for i, pid in enumerate(all_paper_ids) if pid not in existing_set]
        if not new_indices:
            print(f"[main] cache is up-to-date, nothing to encode.")
            print(f"[main] refreshing cache metadata for {args.accepted}")
            save_cache(out_path, existing_embs, existing_ids, args.model, Path(args.accepted))
            size_mb = out_path.stat().st_size / (1024 * 1024)
            print(f"[main] saved: {out_path} ({size_mb:.1f} MB), shape: {existing_embs.shape}")
            return
        paper_ids = [all_paper_ids[i] for i in new_indices]
        texts = [all_texts[i] for i in new_indices]
        print(f"[main] incremental: {len(new_indices)} new papers to encode, {len(existing_ids)} cached")
    else:
        paper_ids = all_paper_ids
        texts = all_texts

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
    new_embeddings = np.vstack(shards)

    if args.dim and new_embeddings.shape[1] > args.dim:
        new_embeddings = new_embeddings[:, :args.dim]
        norms = np.linalg.norm(new_embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        new_embeddings = new_embeddings / norms
        print(f"[main] truncated to dim={args.dim}")

    # Merge with existing cache if incremental
    if existing_embs is not None and not full_rebuild:
        all_embeddings = np.vstack([existing_embs, new_embeddings])
        final_paper_ids = existing_ids + paper_ids
        print(f"[main] merged: {existing_embs.shape[0]} existing + {new_embeddings.shape[0]} new = {all_embeddings.shape[0]} total")
    else:
        all_embeddings = new_embeddings
        final_paper_ids = paper_ids

    out_path = Path(args.out)
    save_cache(out_path, all_embeddings, final_paper_ids, args.model, Path(args.accepted))
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"[main] saved: {out_path} ({size_mb:.1f} MB), shape: {all_embeddings.shape}")
    print(f"[main] throughput: {len(texts) / elapsed:.0f} papers/s (encoded {len(texts)} new)")


if __name__ == "__main__":
    main()
