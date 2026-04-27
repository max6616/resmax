from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[5]
SERVER_ENV = REPO_ROOT / ".localconfig" / "server.env"


@dataclass(frozen=True)
class QueryEmbeddingResult:
    ok: bool
    provider: str
    vector: list[float]
    dimension: int
    elapsed_sec: float
    error: str = ""


class QueryEmbeddingProvider:
    def __init__(self, provider: str, *, dimension: int, timeout_sec: int = 240) -> None:
        self.provider = provider
        self.dimension = max(0, int(dimension))
        self.timeout_sec = timeout_sec
        self.env = _load_server_env()

    def encode(self, query: str) -> QueryEmbeddingResult:
        return self.encode_many([query])[0]

    def encode_many(self, queries: list[str]) -> list[QueryEmbeddingResult]:
        started = time.time()
        if not queries:
            return []
        if self.provider == "none":
            elapsed = time.time() - started
            return [QueryEmbeddingResult(False, self.provider, [], 0, elapsed, "query embedding provider disabled") for _ in queries]
        if self.provider == "hash":
            elapsed = time.time() - started
            return [
                QueryEmbeddingResult(True, self.provider, vector, len(vector), elapsed)
                for vector in (_hash_vector(query, self.dimension or 16) for query in queries)
            ]
        if self.provider == "ssh":
            return self._encode_many_ssh(queries, started)
        elapsed = time.time() - started
        return [
            QueryEmbeddingResult(False, self.provider, [], 0, elapsed, f"unsupported query embedding provider: {self.provider}")
            for _ in queries
        ]

    def _encode_many_ssh(self, queries: list[str], started: float) -> list[QueryEmbeddingResult]:
        host = self.env.get("RESMAX_SSH_HOST", "").strip()
        if not host:
            return self._failed_many(queries, started, "RESMAX_SSH_HOST is not configured")

        remote_dir = self.env.get("RESMAX_SSH_REMOTE_DIR", "~/resmax_embedding_build").strip()
        remote_script = self.env.get("RESMAX_SSH_REMOTE_SCRIPT", "").strip()
        if not remote_script:
            remote_script = f"{remote_dir.rstrip('/')}/scripts/encode_query.py"
        conda_env = self.env.get("RESMAX_SSH_CONDA_ENV", "").strip()
        conda_init = self.env.get("RESMAX_SSH_CONDA_INIT", "").strip()

        setup_parts: list[str] = []
        if conda_init:
            setup_parts.append(f"source {_remote_path(conda_init)}")
        if conda_env:
            setup_parts.append(f"conda activate {shlex.quote(conda_env)}")
        if remote_dir:
            setup_parts.append(f"cd {_remote_path(remote_dir)}")
        dim_arg = f" --dim {self.dimension}" if self.dimension else ""
        query_arg = "--query" if len(queries) == 1 else "--queries-json"
        query_payload = queries[0] if len(queries) == 1 else json.dumps(queries, ensure_ascii=False)
        command = " && ".join(
            setup_parts
            + [
                "HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 "
                f"python3 {_remote_path(remote_script)} {query_arg} {shlex.quote(query_payload)}{dim_arg}"
            ]
        )
        try:
            result = subprocess.run(
                ["ssh", host, command],
                text=True,
                capture_output=True,
                check=False,
                timeout=self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            return self._failed_many(queries, started, f"ssh query encoding timed out: {exc}")
        if result.returncode != 0:
            stderr = result.stderr.strip().splitlines()
            detail = stderr[-1] if stderr else result.stdout.strip()[:500]
            return self._failed_many(queries, started, f"ssh query encoding failed: {detail}")
        try:
            vectors = _parse_vectors_stdout(result.stdout, expected_count=len(queries))
        except ValueError as exc:
            return self._failed_many(queries, started, str(exc))
        elapsed = time.time() - started
        results: list[QueryEmbeddingResult] = []
        for vector in vectors:
            if self.dimension and len(vector) != self.dimension:
                results.append(
                    QueryEmbeddingResult(
                        False,
                        self.provider,
                        [],
                        0,
                        elapsed,
                        f"query vector dimension mismatch: expected {self.dimension}, got {len(vector)}",
                    )
                )
            else:
                results.append(QueryEmbeddingResult(True, self.provider, vector, len(vector), elapsed))
        return results

    def _failed_many(self, queries: list[str], started: float, error: str) -> list[QueryEmbeddingResult]:
        elapsed = time.time() - started
        return [QueryEmbeddingResult(False, self.provider, [], 0, elapsed, error) for _ in queries]


def _load_server_env() -> dict[str, str]:
    env = dict(os.environ)
    if not SERVER_ENV.exists():
        return env
    for raw in SERVER_ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        env.setdefault(key.strip(), value.strip().strip("'").strip('"'))
    return env


def _remote_path(value: str) -> str:
    value = value.strip()
    if value == "~":
        return "~"
    if value.startswith("~/"):
        return "~/" + shlex.quote(value[2:])
    return shlex.quote(value)


def _parse_vectors_stdout(stdout: str, *, expected_count: int) -> list[list[float]]:
    for raw in reversed(stdout.splitlines()):
        text = raw.strip()
        if not text:
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, list):
            continue
        if expected_count == 1 and (not value or not isinstance(value[0], list)):
            return [_coerce_vector(value)]
        if len(value) != expected_count:
            raise ValueError(f"query encoder returned {len(value)} vectors for {expected_count} queries")
        return [_coerce_vector(item) for item in value]
    raise ValueError("query encoder stdout did not contain a JSON vector")


def _coerce_vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        raise ValueError("query encoder returned a non-list vector")
    try:
        vector = [float(x) for x in value]
    except (TypeError, ValueError) as exc:
        raise ValueError("query encoder returned a non-numeric vector") from exc
    if not vector:
        raise ValueError("query encoder returned an empty vector")
    return vector


def _hash_vector(text: str, dimension: int) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(f"{counter}:{text}".encode("utf-8")).digest()
        for index in range(0, len(digest), 4):
            raw = int.from_bytes(digest[index : index + 4], "big", signed=False)
            values.append((raw / 2**31) - 1.0)
            if len(values) >= dimension:
                break
        counter += 1
    norm = math.sqrt(sum(value * value for value in values))
    if norm:
        values = [value / norm for value in values]
    return values
