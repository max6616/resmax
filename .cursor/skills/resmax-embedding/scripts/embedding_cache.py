"""Embedding cache: encode papers once, persist as .npz, incremental update, self-check."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np


def _paper_text(title: str, abstract: str, instruction: str = "") -> str:
    """Combine title + abstract into the text to embed."""
    body = title.strip()
    if abstract.strip():
        body += "\n" + abstract.strip()
    if instruction:
        return instruction + body
    return body


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_cache(cache_path: Path) -> tuple[np.ndarray, list[str], dict]:
    """Load cached embeddings. Only needs numpy, no torch/model required.

    Returns: (embeddings, paper_ids, meta_dict)
    """
    data = np.load(cache_path, allow_pickle=True)
    embeddings = data["embeddings"]
    paper_ids = list(data["paper_ids"])
    meta = json.loads(str(data["meta"]))
    return embeddings, paper_ids, meta


def _save_cache(
    cache_path: Path,
    embeddings: np.ndarray,
    paper_ids: list[str],
    model_name: str,
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        cache_path,
        embeddings=embeddings.astype(np.float32),
        paper_ids=np.array(paper_ids, dtype=object),
        meta=json.dumps({
            "model_name": model_name,
            "dimension": int(embeddings.shape[1]),
            "count": len(paper_ids),
        }),
    )
    size_mb = cache_path.stat().st_size / (1024 * 1024)
    print(f"[embedding-cache] saved: {cache_path} ({size_mb:.1f} MB, {len(paper_ids)} papers, dim={embeddings.shape[1]})")


# ---------------------------------------------------------------------------
# Diff: discover what needs incremental encoding
# ---------------------------------------------------------------------------

def diff_cache_vs_index(
    cache_path: Path,
    index_paper_ids: list[str],
) -> dict:
    """Compare cache against current accepted_index paper_ids.

    Returns a dict with:
      - status: "missing" | "ok" | "stale" | "drift"
      - missing_ids: paper_ids in index but not in cache
      - stale_ids: paper_ids in cache but not in index (orphans)
      - cached_count: number of papers in cache
      - index_count: number of papers in index
    """
    if not cache_path.exists():
        return {
            "status": "missing",
            "missing_ids": index_paper_ids,
            "stale_ids": [],
            "cached_count": 0,
            "index_count": len(index_paper_ids),
        }

    _, cached_ids, _ = load_cache(cache_path)
    cached_set = set(cached_ids)
    index_set = set(index_paper_ids)

    missing = [pid for pid in index_paper_ids if pid not in cached_set]
    stale = [pid for pid in cached_ids if pid not in index_set]

    if not missing and not stale:
        status = "ok"
    elif missing and not stale:
        status = "stale"  # cache is behind index
    elif not missing and stale:
        status = "drift"  # cache has orphans (index shrank)
    else:
        status = "drift"  # both missing and stale

    return {
        "status": status,
        "missing_ids": missing,
        "stale_ids": stale,
        "cached_count": len(cached_ids),
        "index_count": len(index_paper_ids),
    }


def print_diff_report(diff: dict) -> None:
    """Print a human-readable diff report."""
    print(f"[cache-check] status: {diff['status']}")
    print(f"[cache-check] index: {diff['index_count']} papers, cache: {diff['cached_count']} papers")
    if diff["missing_ids"]:
        print(f"[cache-check] missing from cache: {len(diff['missing_ids'])} papers (need incremental encode)")
    if diff["stale_ids"]:
        print(f"[cache-check] stale in cache (orphans): {len(diff['stale_ids'])} papers")
    if diff["status"] == "ok":
        print("[cache-check] cache is fully consistent with index")


# ---------------------------------------------------------------------------
# Self-check: validate cache integrity
# ---------------------------------------------------------------------------

def verify_cache(cache_path: Path, index_paper_ids: list[str]) -> bool:
    """Quick self-check: verify cache exists, is loadable, and matches index.

    Returns True if cache is valid and consistent.
    Prints diagnostics to stdout.
    """
    if not cache_path.exists():
        print(f"[verify] FAIL: cache file not found: {cache_path}")
        return False

    try:
        embeddings, cached_ids, meta = load_cache(cache_path)
    except Exception as e:
        print(f"[verify] FAIL: cannot load cache: {e}")
        return False

    ok = True

    # Shape consistency
    if embeddings.shape[0] != len(cached_ids):
        print(f"[verify] FAIL: embedding rows ({embeddings.shape[0]}) != paper_id count ({len(cached_ids)})")
        ok = False

    if int(meta.get("count", -1)) != len(cached_ids):
        print(f"[verify] WARN: meta.count ({meta.get('count')}) != actual ({len(cached_ids)})")

    # NaN / Inf check
    nan_count = int(np.isnan(embeddings).any(axis=1).sum())
    inf_count = int(np.isinf(embeddings).any(axis=1).sum())
    if nan_count or inf_count:
        print(f"[verify] FAIL: {nan_count} NaN rows, {inf_count} Inf rows in embeddings")
        ok = False

    # Norm check (should be ~1.0 for L2-normalized vectors)
    norms = np.linalg.norm(embeddings, axis=1)
    bad_norms = int(((norms < 0.95) | (norms > 1.05)).sum())
    if bad_norms:
        print(f"[verify] WARN: {bad_norms}/{len(norms)} vectors have norm outside [0.95, 1.05]")

    # Duplicate paper_id check
    if len(set(cached_ids)) != len(cached_ids):
        dup_count = len(cached_ids) - len(set(cached_ids))
        print(f"[verify] FAIL: {dup_count} duplicate paper_ids in cache")
        ok = False

    # Consistency with index
    diff = diff_cache_vs_index(cache_path, index_paper_ids)
    if diff["missing_ids"]:
        print(f"[verify] WARN: {len(diff['missing_ids'])} papers in index but not in cache")
    if diff["stale_ids"]:
        print(f"[verify] INFO: {len(diff['stale_ids'])} orphan papers in cache (not in current index)")

    if ok and not diff["missing_ids"]:
        print(f"[verify] OK: cache is valid and complete ({len(cached_ids)} papers, dim={embeddings.shape[1]})")
    elif ok:
        print(f"[verify] PARTIAL: cache is valid but incomplete ({len(diff['missing_ids'])} missing)")

    return ok


# ---------------------------------------------------------------------------
# Incremental update
# ---------------------------------------------------------------------------

def incremental_update(
    cache_path: Path,
    all_paper_ids: list[str],
    all_titles: list[str],
    all_abstracts: list[str],
    model_name: str,
    dimension: int = 0,
    batch_size: int = 32,
    device: str = "cuda",
    instruction: str = "",
    remove_stale: bool = False,
) -> np.ndarray:
    """Detect missing papers, encode only those, merge into existing cache.

    If remove_stale=True, also removes orphan embeddings not in current index.
    Designed to run on GPU server.
    """
    # Build lookup
    id_to_idx = {pid: i for i, pid in enumerate(all_paper_ids)}

    diff = diff_cache_vs_index(cache_path, all_paper_ids)
    print_diff_report(diff)

    if diff["status"] == "missing":
        # No cache at all — this should use build_cache_multigpu.py instead
        print("[incremental] ERROR: no existing cache. Use build_cache_multigpu.py for initial build.")
        sys.exit(1)

    if not diff["missing_ids"] and not (remove_stale and diff["stale_ids"]):
        print("[incremental] cache is up to date, nothing to do.")
        old_emb, _, _ = load_cache(cache_path)
        return old_emb

    old_embeddings, old_ids, meta = load_cache(cache_path)

    # --- Encode missing papers ---
    new_embeddings = None
    if diff["missing_ids"]:
        try:
            import torch
            from transformers import AutoTokenizer, AutoModel, BitsAndBytesConfig
        except ImportError:
            raise ImportError("transformers, torch, bitsandbytes required for incremental encode")

        missing_indices = [id_to_idx[pid] for pid in diff["missing_ids"]]
        missing_titles = [all_titles[i] for i in missing_indices]
        missing_abstracts = [all_abstracts[i] for i in missing_indices]
        texts = [_paper_text(t, a, instruction) for t, a in zip(missing_titles, missing_abstracts)]

        print(f"[incremental] encoding {len(texts)} new papers on {device}")
        tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)

        if device.startswith("cuda"):
            quant_config = BitsAndBytesConfig(load_in_8bit=True)
            model = AutoModel.from_pretrained(
                model_name, trust_remote_code=True,
                quantization_config=quant_config,
                device_map={"": torch.device(device)},
            )
        else:
            model = AutoModel.from_pretrained(
                model_name, trust_remote_code=True,
                torch_dtype=torch.float32,
            ).to(device)
        model.eval()

        new_emb_list = []
        num_batches = (len(texts) + batch_size - 1) // batch_size
        t0 = time.time()

        for i in range(num_batches):
            s, e = i * batch_size, min((i + 1) * batch_size, len(texts))
            encoded = tokenizer(
                texts[s:e], padding=True, truncation=True,
                max_length=8192, return_tensors="pt",
            )
            first_dev = next(model.parameters()).device
            encoded = {k: v.to(first_dev) for k, v in encoded.items()}

            with torch.no_grad():
                outputs = model(**encoded)
                last_hidden = outputs.last_hidden_state
                mask = encoded["attention_mask"].unsqueeze(-1).to(last_hidden.dtype)
                emb = (last_hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
                emb = torch.nn.functional.normalize(emb, p=2, dim=1)
                new_emb_list.append(emb.cpu().float().numpy())

            if (i + 1) % 10 == 0 or (i + 1) == num_batches:
                elapsed = time.time() - t0
                speed = e / elapsed if elapsed > 0 else 0
                print(f"  [{i+1}/{num_batches}] {e}/{len(texts)} ({speed:.0f} papers/s)")

        new_embeddings = np.vstack(new_emb_list)
        # Truncate to target dimension if needed (e.g. 4096 → 1024)
        if dimension and new_embeddings.shape[1] > dimension:
            new_embeddings = new_embeddings[:, :dimension]
            # Re-normalize after truncation
            norms = np.linalg.norm(new_embeddings, axis=1, keepdims=True)
            norms = np.where(norms < 1e-9, 1.0, norms)
            new_embeddings = new_embeddings / norms
        print(f"[incremental] encoded {new_embeddings.shape[0]} new papers (dim={new_embeddings.shape[1]})")

    # --- Merge ---
    if new_embeddings is not None:
        combined_emb = np.vstack([old_embeddings, new_embeddings.astype(np.float32)])
        combined_ids = old_ids + diff["missing_ids"]
    else:
        combined_emb = old_embeddings
        combined_ids = old_ids

    # --- Remove stale ---
    if remove_stale and diff["stale_ids"]:
        stale_set = set(diff["stale_ids"])
        keep_mask = [pid not in stale_set for pid in combined_ids]
        combined_emb = combined_emb[keep_mask]
        combined_ids = [pid for pid, keep in zip(combined_ids, keep_mask) if keep]
        print(f"[incremental] removed {len(diff['stale_ids'])} stale entries")

    # --- Truncate dimension if needed ---
    if dimension and combined_emb.shape[1] > dimension:
        combined_emb = combined_emb[:, :dimension]
        norms = np.linalg.norm(combined_emb, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        combined_emb = combined_emb / norms

    _save_cache(cache_path, combined_emb, combined_ids, model_name)
    return combined_emb


# ---------------------------------------------------------------------------
# Legacy build_cache (kept for single-GPU / small batch use)
# For multi-GPU initial build, use build_cache_multigpu.py
# ---------------------------------------------------------------------------

def build_cache(
    paper_ids: list[str],
    titles: list[str],
    abstracts: list[str],
    model_name: str,
    cache_path: Path,
    dimension: int = 0,
    batch_size: int = 64,
    device: str = "cuda",
    instruction: str = "",
    show_progress: bool = True,
) -> np.ndarray:
    """Single-device full encode. For multi-GPU, use build_cache_multigpu.py."""
    try:
        import torch
        from transformers import AutoTokenizer, AutoModel, BitsAndBytesConfig
    except ImportError:
        raise ImportError("transformers and torch required. pip install transformers torch bitsandbytes")

    print(f"[embedding-cache] loading model: {model_name} on {device}")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)

    if device.startswith("cuda"):
        quant_config = BitsAndBytesConfig(load_in_8bit=True)
        model = AutoModel.from_pretrained(
            model_name, trust_remote_code=True,
            quantization_config=quant_config,
            device_map={"": torch.device(device)},
        )
    else:
        model = AutoModel.from_pretrained(
            model_name, trust_remote_code=True,
            torch_dtype=torch.float32,
        ).to(device)
    model.eval()

    texts = [_paper_text(t, a, instruction) for t, a in zip(titles, abstracts)]
    total = len(texts)
    num_batches = (total + batch_size - 1) // batch_size
    print(f"[embedding-cache] encoding {total} papers (batch_size={batch_size})")

    all_embeddings = []
    t0 = time.time()

    for i in range(num_batches):
        start = i * batch_size
        end = min(start + batch_size, total)

        encoded = tokenizer(
            texts[start:end], padding=True, truncation=True,
            max_length=8192, return_tensors="pt",
        )
        first_dev = next(model.parameters()).device
        encoded = {k: v.to(first_dev) for k, v in encoded.items()}

        with torch.no_grad():
            outputs = model(**encoded)
            last_hidden = outputs.last_hidden_state
            mask = encoded["attention_mask"].unsqueeze(-1).to(last_hidden.dtype)
            emb = (last_hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
            emb = torch.nn.functional.normalize(emb, p=2, dim=1)
            all_embeddings.append(emb.cpu().float().numpy())

        if show_progress and (i + 1) % 20 == 0:
            elapsed = time.time() - t0
            speed = end / elapsed
            eta = (total - end) / speed if speed > 0 else 0
            print(f"  [{i+1}/{num_batches}] {end}/{total} ({speed:.0f} papers/s, ETA {eta:.0f}s)")

    embeddings = np.vstack(all_embeddings)

    if dimension and embeddings.shape[1] > dimension:
        embeddings = embeddings[:, :dimension]
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        embeddings = embeddings / norms

    elapsed = time.time() - t0
    print(f"[embedding-cache] done: {total} papers in {elapsed:.1f}s, shape {embeddings.shape}")

    _save_cache(cache_path, embeddings, paper_ids, model_name)
    return embeddings
