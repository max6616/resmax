"""Unified secrets / local-config loader for all resmax-* skills.

Design goals
------------
1. **Zero dependencies.** Pure stdlib so any cloned repo can import it
   without a pip install.
2. **Single source of truth for paths.** `.secrets/*.env` holds real
   credentials; `.localconfig/*.env` holds machine-specific config.
   The loader sources both on import so downstream code reads
   `os.environ` uniformly.
3. **Machine-readable errors.** When a required variable is missing, we
   raise `MissingSecretError` whose `str()` starts with the fixed prefix
   `[MISSING_SECRET]` and embeds a JSON payload. The Cursor agent is
   expected to detect this prefix and halt to ask the user, per the
   "information supplement protocol" documented in SECRETS.md.

The loader is intentionally named `secrets_loader` (not `secrets`) to
avoid shadowing Python's stdlib `secrets` module.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------
# Error protocol
# --------------------------------------------------------------------------

MISSING_SECRET_PREFIX = "[MISSING_SECRET]"


class MissingSecretError(RuntimeError):
    """Raised when a required secret / local-config value is not set.

    The stringified message is `<PREFIX> <json-payload>` so callers can
    detect it in subprocess stderr with a plain substring match.
    """

    def __init__(
        self,
        var: str,
        env_file: str,
        purpose: str = "",
        extra_vars: Optional[list[str]] = None,
    ) -> None:
        self.var = var
        self.env_file = env_file
        self.purpose = purpose
        self.extra_vars = extra_vars or []
        payload = {
            "missing_var": var,
            "all_vars": [var] + list(self.extra_vars),
            "env_file": env_file,
            "example_file": env_file + ".example",
            "purpose": purpose,
        }
        super().__init__(f"{MISSING_SECRET_PREFIX} {json.dumps(payload, ensure_ascii=False)}")


# --------------------------------------------------------------------------
# Repo-root discovery
# --------------------------------------------------------------------------

def _find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk upward from `start` (or this file) until a marker is found.

    Preference order: `.git/` directory, then `.secrets/` directory.
    Falls back to the nearest ancestor containing either. Raises
    `RuntimeError` if nothing matches before filesystem root.
    """
    current = (start or Path(__file__)).resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists() or (parent / ".secrets").is_dir():
            return parent
    raise RuntimeError(
        "Could not locate repository root (no .git or .secrets directory "
        f"in any ancestor of {current})."
    )


_REPO_ROOT = _find_repo_root()


def repo_root() -> Path:
    """Public accessor for the cached repository root."""
    return _REPO_ROOT


# --------------------------------------------------------------------------
# Shell-style .env parser (stdlib only — no python-dotenv dependency)
# --------------------------------------------------------------------------

# Matches lines like:  export FOO='bar baz'   or   FOO=bar
_ENV_LINE_RE = re.compile(
    r"""^
    (?:export\s+)?
    (?P<key>[A-Za-z_][A-Za-z0-9_]*)
    \s*=\s*
    (?P<value>.*?)
    \s*$
    """,
    re.VERBOSE,
)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_env_file(path: Path) -> dict[str, str]:
    """Very small shell-compatible .env parser.

    Supports: `export KEY=value`, `KEY=value`, single/double quotes,
    comments starting with `#`, empty lines. Does NOT support variable
    interpolation or multi-line values.
    """
    result: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return result
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE_RE.match(line)
        if not m:
            continue
        result[m.group("key")] = _strip_quotes(m.group("value"))
    return result


# --------------------------------------------------------------------------
# Auto-load on import
# --------------------------------------------------------------------------

_LOADED_FILES: list[Path] = []


def _auto_load() -> None:
    """Source `.secrets/*.env` and `.localconfig/*.env` into os.environ.

    Existing environment variables take precedence — we never clobber.
    Files with a `.example` suffix are ignored (they are templates).
    """
    for subdir in (".secrets", ".localconfig"):
        directory = _REPO_ROOT / subdir
        if not directory.is_dir():
            continue
        for env_path in sorted(directory.glob("*.env")):
            if env_path.name.endswith(".example"):
                continue
            parsed = _parse_env_file(env_path)
            for key, value in parsed.items():
                if key not in os.environ and value != "":
                    os.environ[key] = value
            _LOADED_FILES.append(env_path)


_auto_load()


def loaded_env_files() -> list[Path]:
    """Return the list of `.env` files that were sourced at import time."""
    return list(_LOADED_FILES)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def get_secret(
    var: str,
    *,
    env_file: str,
    default: Optional[str] = None,
) -> Optional[str]:
    """Soft accessor: return `os.environ[var]` or `default`.

    `env_file` is recorded only for documentation / agent hints; it is
    not used to drive lookup because `_auto_load()` has already merged
    everything into `os.environ` on import.
    """
    _ = env_file  # kept in the signature for self-documenting call sites
    value = os.environ.get(var, "")
    if value:
        return value
    return default


def require_secret(
    var: str,
    *,
    env_file: str,
    purpose: str = "",
    extra_vars: Optional[list[str]] = None,
) -> str:
    """Hard accessor: return value or raise MissingSecretError.

    Parameters
    ----------
    var : str
        The primary environment variable name.
    env_file : str
        Repo-relative path to the `.env` file where this variable belongs
        (e.g. `.secrets/github.env`). Used in the error payload so the
        agent knows which file to create/edit.
    purpose : str
        Short human-readable reason the secret is needed. Shown to the
        user when the agent prompts for the missing value.
    extra_vars : list[str] | None
        Additional variables that must be set *together* with `var`
        (e.g. username + password pair). They are all required to be
        non-empty; the first missing one triggers the error.
    """
    all_vars = [var] + list(extra_vars or [])
    for name in all_vars:
        value = os.environ.get(name, "")
        if not value:
            raise MissingSecretError(
                var=name,
                env_file=env_file,
                purpose=purpose,
                extra_vars=[v for v in all_vars if v != name],
            )
    return os.environ[var]


def emit_missing_and_exit(err: MissingSecretError, *, exit_code: int = 2) -> None:
    """Convenience helper: print the error to stderr and exit.

    Scripts that don't want to propagate the exception can call this to
    ensure the `[MISSING_SECRET]` prefix lands in the CLI output.
    """
    print(str(err), file=sys.stderr, flush=True)
    sys.exit(exit_code)


__all__ = [
    "MISSING_SECRET_PREFIX",
    "MissingSecretError",
    "emit_missing_and_exit",
    "get_secret",
    "loaded_env_files",
    "repo_root",
    "require_secret",
]
