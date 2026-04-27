from __future__ import annotations

import hashlib
import json
import re
from typing import Any


_STATE_KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for hashing state inputs."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    """Return a sha256 hash for any JSON-serializable value."""
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def input_hash(value: Any) -> str:
    """Name the hash by intent at call sites that hash upstream inputs."""
    return stable_hash(value)


def make_state_id(kind: str, value: Any, *, length: int = 16) -> str:
    """Create a deterministic compact state id like ``evidence_card:abcd...``."""
    if not _STATE_KIND_RE.match(kind):
        raise ValueError(f"invalid state kind: {kind!r}")
    if length < 8 or length > 64:
        raise ValueError("state id hash length must be between 8 and 64")
    return f"{kind}:{stable_hash(value).split(':', 1)[1][:length]}"
