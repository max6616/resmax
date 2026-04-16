"""Embedding-based paper retrieval: query encode + cosine top-K.

Returns candidate papers with raw cosine similarity scores.
No grading or normalization — that happens downstream via subagent scoring.

Query encoding strategy:
  1. Try local (sentence-transformers + enough RAM)
  2. Fallback: SSH to GPU server, encode there, read JSON vector from stdout
  3. Cosine similarity search is always local (pure numpy, milliseconds)
"""
from __future__ import annotations

import json
import subprocess
import shlex
from pathlib import Path

import numpy as np

from .models import CandidatePaper


def load_embedding_cache(cache_path) -> tuple:
    """Load cached embeddings from .npz file. Only needs numpy."""
    import json as _json
    data = np.load(cache_path, allow_pickle=True)
    embeddings = data["embeddings"]
    paper_ids = list(data["paper_ids"])
    meta = _json.loads(str(data["meta"]))
    return embeddings, paper_ids, meta


# ---------------------------------------------------------------------------
# Query encoding: local or remote
# ---------------------------------------------------------------------------

def _encode_query_local(
    query: str,
    model_name: str,
    dimension: int = 0,
    device: str = "cpu",
) -> np.ndarray:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name, device=device, trust_remote_code=True)
    vec = model.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
    if dimension and len(vec) > dimension:
        vec = vec[:dimension]
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
    return vec.astype(np.float32)


def _encode_query_ssh(
    query: str,
    ssh_host: str = "5090",
    remote_script: str = "~/resmax_embedding_build/scripts/encode_query.py",
    conda_env: str = "llm",
    model_name: str = "Qwen/Qwen3-Embedding-8B",
    device: str = "cuda:0",
    dimension: int = 0,
    timeout: int = 180,
) -> np.ndarray:
    escaped_query = shlex.quote(query)
    dim_arg = f" --dim {dimension}" if dimension else ""
    cmd = (
        f"ssh {ssh_host} "
        f"\"source ~/miniconda3/etc/profile.d/conda.sh && conda activate {conda_env} && "
        f"export HF_ENDPOINT=https://hf-mirror.com && "
        f"python {remote_script} {escaped_query} --model {model_name} --device {device}{dim_arg}\""
    )
    print(f"[embedding-retrieval] SSH to {ssh_host} for query encoding...")
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout,
    )
    if result.stderr:
        for line in result.stderr.strip().split("\n"):
            print(f"  [remote] {line}")
    if result.returncode != 0:
        raise RuntimeError(
            f"Remote query encode failed (exit {result.returncode}):\n{result.stderr[:500]}"
        )

    output = result.stdout.strip()
    for line in reversed(output.split("\n")):
        line = line.strip()
        if line.startswith("["):
            vec = np.array(json.loads(line), dtype=np.float32)
            print(f"[embedding-retrieval] got vector dim={len(vec)} from {ssh_host}")
            return vec

    raise RuntimeError(f"No JSON vector in remote stdout:\n{output[:300]}")


def encode_query(
    query: str,
    model_name: str = "Qwen/Qwen3-Embedding-8B",
    dimension: int = 0,
    device: str = "cpu",
    instruction: str = "",
    ssh_host: str = "5090",
    ssh_remote_script: str = "~/resmax_embedding_build/scripts/encode_query.py",
    ssh_conda_env: str = "llm",
) -> np.ndarray:
    """Encode query, auto-selecting local or SSH."""
    text = (instruction + query) if instruction else query

    try:
        import sentence_transformers  # noqa: F401
        import psutil
        avail_gb = psutil.virtual_memory().available / 1e9
        if avail_gb < 4.0:
            raise MemoryError("Not enough RAM")
        print(f"[embedding-retrieval] encoding locally on {device}")
        return _encode_query_local(text, model_name, dimension, device)
    except (ImportError, MemoryError, Exception):
        pass

    return _encode_query_ssh(
        text,
        ssh_host=ssh_host,
        remote_script=ssh_remote_script,
        conda_env=ssh_conda_env,
        model_name=model_name,
        device="cuda:0",
        dimension=dimension,
    )


# ---------------------------------------------------------------------------
# Cosine similarity search (pure numpy, always local)
# ---------------------------------------------------------------------------

def cosine_topk(
    query_vec: np.ndarray,
    embeddings: np.ndarray,
    top_k: int = 50,
) -> list[tuple[int, float]]:
    """Return top-K (index, similarity) pairs. Pure numpy, milliseconds on M1."""
    scores = embeddings @ query_vec
    if top_k >= len(scores):
        indices = np.argsort(-scores)
    else:
        indices = np.argpartition(-scores, top_k)[:top_k]
        indices = indices[np.argsort(-scores[indices])]
    return [(int(idx), float(scores[idx])) for idx in indices]


# ---------------------------------------------------------------------------
# Main retrieval entry point
# ---------------------------------------------------------------------------

def embedding_retrieve(
    papers: list[CandidatePaper],
    direction: str,
    keywords: list[str],
    cache_path: Path,
    model_name: str,
    dimension: int = 0,
    top_k: int = 50,
    device: str = "cpu",
    instruction: str = "",
    ssh_host: str = "5090",
) -> list[tuple[CandidatePaper, float]]:
    """Retrieve top-K papers by embedding similarity.

    Returns (paper, cosine_similarity) pairs sorted by similarity desc.
    No scoring or grading — just raw retrieval.
    """
    embeddings, cached_ids, meta = load_embedding_cache(cache_path)
    paper_map = {p.paper_id: p for p in papers}

    query_parts = [direction.strip()]
    if keywords:
        query_parts.append("Keywords: " + ", ".join(keywords))
    query_text = "\n".join(query_parts)

    query_vec = encode_query(
        query_text,
        model_name=model_name,
        dimension=dimension,
        device=device,
        instruction=instruction,
        ssh_host=ssh_host,
    )

    if query_vec.shape[0] != embeddings.shape[1]:
        target_dim = min(query_vec.shape[0], embeddings.shape[1])
        if query_vec.shape[0] > target_dim:
            query_vec = query_vec[:target_dim]
            norm = np.linalg.norm(query_vec)
            if norm > 0:
                query_vec = query_vec / norm
        if embeddings.shape[1] > target_dim:
            embeddings = embeddings[:, :target_dim]
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            embeddings = embeddings / norms
        print(f"[embedding-retrieval] dimension mismatch resolved: query={query_vec.shape[0]}, cache={embeddings.shape[1]} -> {target_dim}")

    print(f"[embedding-retrieval] searching top-{top_k} from {embeddings.shape[0]} cached embeddings")
    topk_results = cosine_topk(query_vec, embeddings, top_k=top_k)

    results: list[tuple[CandidatePaper, float]] = []
    for idx, score in topk_results:
        pid = cached_ids[idx]
        paper = paper_map.get(pid)
        if paper:
            results.append((paper, score))

    if results:
        print(f"[embedding-retrieval] {len(results)} candidates (cosine: {results[0][1]:.4f} ~ {results[-1][1]:.4f})")
    else:
        print("[embedding-retrieval] no candidates found")
    return results


# Keep old name as alias for backward compatibility
embedding_filter = embedding_retrieve
