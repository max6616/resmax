# `.localconfig/` — machine-specific runtime configuration

This directory holds **non-secret but per-machine** config: SSH hosts,
remote paths, conda environment names, workspace-specific tuning. Kept
separate from `.secrets/` so credentials and machine config have distinct
lifecycles.

Everything inside is gitignored except `README.md` and `*.env.example`
templates.

## Quick start for new clones

```bash
# 1. Copy every template
for f in .localconfig/*.env.example; do
  cp "$f" "${f%.example}"
done

# 2. Edit the .env files to point at your own GPU server, paths, conda env
# 3. Skills load these automatically via _shared/secrets_loader.py
```

Hugging Face read tokens are credentials, not localconfig values. Use
`resmax-init --with-data`, `HF_TOKEN`, or `hf auth login` for private dataset
access.

## File index

| File | Purpose | Consumed by |
| --- | --- | --- |
| `server.env` | Remote GPU server settings: SSH host, working directory, conda env | `resmax-embedding`, `resmax-survey` (embedding query encoding over SSH) |
| `huggingface.env` | Hugging Face dataset repo/path defaults for large artifact pull and review-cache restore | `scripts/resmax_data.py`, `resmax-database/scripts/ensure_reviews_available.py` |

## Loader behaviour

The same `.agents/skills/_shared/secrets_loader.py` loader reads these values.
When a required variable is missing, the loader halts with a message
that names which `.localconfig/*.env` file to populate. The agent then
asks the user interactively and writes the value into the file.
