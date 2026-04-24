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
import sys
import shlex
from pathlib import Path

import numpy as np

from .models import CandidatePaper

# Auto-load .secrets/*.env and .localconfig/*.env into os.environ.
# File path: .agents/skills/resmax-survey/scripts/search_literature_lib/embedding_filter.py
# parents: [0]=search_literature_lib, [1]=scripts, [2]=resmax-survey, [3]=skills, [4]=.agents
_SHARED = Path(__file__).resolve().parents[3] / "_shared"
sys.path.insert(0, str(_SHARED))
from secrets_loader import MissingSecretError, get_secret, require_secret  # noqa: E402


def _remote_shell_quote(value: str) -> str:
    if value.startswith("~/"):
        return "$HOME/" + shlex.quote(value[2:])
    return shlex.quote(value)


def load_embedding_cache(cache_path) -> tuple:
    """Load cached embeddings from .npz file. Only needs numpy."""
    import json as _json
    data = np.load(cache_path, allow_pickle=False)
    embeddings = data["embeddings"]
    paper_ids = [str(x) for x in data["paper_ids"].tolist()]
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
    ssh_host: str = "",
    remote_script: str = "",
    conda_env: str = "",
    model_name: str = "Qwen/Qwen3-Embedding-8B",
    device: str = "auto",
    dimension: int = 0,
    # Qwen3-Embedding-8B INT8 first-load (4 shards) takes ~50s on a warm cache;
    # cold HF download can push well past 3 min. Budget 5 min to be safe.
    timeout: int = 300,
    conda_init: str = "",
) -> np.ndarray:
    # Empty args mean "read from .localconfig/server.env". RESMAX_SSH_HOST is
    # hard-required: without it we can't even attempt the SSH fallback and
    # should raise a MissingSecretError the Cursor agent will convert into
    # an interactive prompt to the user (see SECRETS.md).
    ssh_host = ssh_host or require_secret(
        "RESMAX_SSH_HOST",
        env_file=".localconfig/server.env",
        purpose="SSH into the GPU server to encode the query embedding",
    )
    remote_script = remote_script or get_secret(
        "RESMAX_SSH_REMOTE_SCRIPT",
        env_file=".localconfig/server.env",
        default="~/resmax_embedding_build/scripts/encode_query.py",
    )
    conda_env = conda_env or get_secret(
        "RESMAX_SSH_CONDA_ENV",
        env_file=".localconfig/server.env",
        default="llm",
    )
    conda_init = conda_init or get_secret(
        "RESMAX_SSH_CONDA_INIT",
        env_file=".localconfig/server.env",
        default="~/miniconda3/etc/profile.d/conda.sh",
    )
    remote_parts = [
        "source",
        _remote_shell_quote(conda_init),
        "&&",
        "conda",
        "activate",
        shlex.quote(conda_env),
        "&&",
        "HF_HUB_OFFLINE=1",
        "python3",
        _remote_shell_quote(remote_script),
        "--query",
        shlex.quote(query),
        "--model",
        shlex.quote(model_name),
        "--device",
        shlex.quote(device),
    ]
    if dimension:
        remote_parts.extend(["--dim", str(dimension)])
    remote_cmd = " ".join(remote_parts)
    # HF_HUB_OFFLINE=1 is mandatory — the Qwen3-Embedding-8B weights are
    # pre-cached on the server and reaching HuggingFace Hub from the server
    # network can hang or 403. encode_query.py also sets this internally as
    # a safety net; we set it here so the process never even tries online
    # resolution during conda activation.
    print(f"[embedding-retrieval] SSH to {ssh_host} for query encoding...")
    result = subprocess.run(
        ["ssh", ssh_host, remote_cmd],
        capture_output=True, text=True, timeout=timeout,
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
    ssh_host: str = "",
    ssh_remote_script: str = "",
    ssh_conda_env: str = "",
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
        # Use 'auto' so encode_query.py's nvidia-smi probe picks the first
        # GPU with >= 20 GiB free. Avoids hanging on a busy cuda:0.
        device="auto",
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
    ssh_host: str = "",
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
