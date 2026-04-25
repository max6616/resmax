# `.secrets/` — API credentials and personal identifiers

This directory holds **real credentials**: API keys, passwords, personal
contact emails used as API User-Agents. Everything inside this folder is
gitignored (only `README.md` and `*.env.example` templates are tracked).

> **Never commit anything here without the `.example` suffix.**

## Quick start for new clones

```bash
# 1. Copy every template to its real .env counterpart
for f in .secrets/*.env.example; do
  cp "$f" "${f%.example}"
done

# 2. Edit the resulting .env files and fill in your real values
# 3. Load on demand per skill:
source .secrets/openreview.env
```

## File index

| File | Purpose | Consumed by |
| --- | --- | --- |
| `openreview.env` | OpenReview API credentials | `resmax-database/scripts/enrich_reviews.py` |
| `github.env` | GitHub personal access token | `resmax-database/scripts/enrich_code_quality.py` |
| `openalex.env` | OpenAlex API key (optional but recommended for journals) | `resmax-database/scripts/accepted_index_builder/fetchers.py` |
| `serpapi.env` | SerpAPI key (optional fallback for missing abstracts) | `resmax-database/scripts/enrich_abstracts_fallback.py` |
| `s2.env` | Semantic Scholar API key (optional) | `resmax-database/scripts/enrich_code_urls.py` |
| `contact.env` | Contact email used as API User-Agent (OpenAlex / Crossref politeness policy) | `resmax-database/scripts/enrich_abstracts_fallback.py` |

## Loader behaviour

All skills read secrets through `.agents/skills/_shared/secrets_loader.py`. When a
required env var is missing, the loader raises `MissingSecretError` with a
standardised message that tells the agent:

- which skill asked for it;
- which `.secrets/*.env` file to populate;
- which env var(s) are missing.

The agent is then expected to **halt execution and ask the user for the
value**, write it into the local `.secrets/` file, and re-run the command.
See `SECRETS.md` at the repo root for the full workflow.
