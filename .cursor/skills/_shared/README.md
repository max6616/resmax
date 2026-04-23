# `_shared/` — cross-skill helpers

Utilities used by every `resmax-*` skill. Kept deliberately small; anything
skill-specific should live in that skill's own `scripts/` directory.

## Files

| File | Purpose |
| --- | --- |
| `secrets_loader.py` | Unified loader for `.secrets/` and `.localconfig/`. Automatically sources `.env` files, exposes `require_secret()` and `get_secret()` with a standardised missing-value error that tells the agent which file to populate. (Named with the `_loader` suffix to avoid shadowing Python's stdlib `secrets` module.) |

## Usage from a script

```python
import sys
from pathlib import Path
# Scripts live at .cursor/skills/<skill>/scripts/<name>.py, so the shared
# helpers are three levels up.
SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(SHARED))
from secrets_loader import require_secret, get_secret, MissingSecretError  # noqa: E402

# Hard requirement — raise with a machine-readable hint if missing:
token = require_secret(
    "GITHUB_TOKEN",
    env_file=".secrets/github.env",
    purpose="GitHub API probes in resmax-database",
)

# Soft requirement — fall back to a default silently:
email = get_secret(
    "RESMAX_CONTACT_EMAIL",
    env_file=".secrets/contact.env",
    default="resmax@example.com",
)
```

## MissingSecretError format

The error is printed with a fixed prefix `[MISSING_SECRET]` so the agent
can grep for it in subprocess output. See `SECRETS.md` at the repo root
for the full agent-side protocol.
