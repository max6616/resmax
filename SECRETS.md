# SECRETS — clone-and-run protocol

This project stores every machine-specific or private value outside the
tracked source tree. Two sibling directories hold them, both gitignored:

| Directory | Purpose | Examples |
| --- | --- | --- |
| `.secrets/` | API credentials and personal identifiers | `OPENREVIEW_PASSWORD`, `GITHUB_TOKEN`, `RESMAX_CONTACT_EMAIL` |
| `.localconfig/` | Machine-specific runtime settings (not secret, but per-user) | `RESMAX_SSH_HOST`, remote paths, conda env names |

Only `README.md` and `*.env.example` templates are tracked by git; the
real `.env` files stay on your disk.

---

## 1. First-time setup after `git clone`

```bash
# 1. Create local .env files from templates
for f in .secrets/*.env.example .localconfig/*.env.example; do
  cp "$f" "${f%.example}"
done

# 2. Edit them and fill in your real values
```

Scripts auto-source every `.env` in both directories via the shared
loader at `.agents/skills/_shared/secrets_loader.py`; no manual
`source` command is required. (You can still `source .secrets/*.env` in
your shell if you want the values available to ad-hoc commands.)

---

## 2. Where values are consumed

### `.secrets/`

| Env var(s) | `.env` file | Used by | Hard-required? |
| --- | --- | --- | --- |
| `OPENREVIEW_USERNAME`, `OPENREVIEW_PASSWORD` | `openreview.env` | `resmax-database/enrich_reviews.py` | Yes (for fetch mode; `--rehydrate` / `--mark-unavailable` work without) |
| `GITHUB_TOKEN` | `github.env` | `resmax-database/enrich_code_quality.py` | Soft — script warns and falls back to 60 req/h unauthenticated |
| `OPENALEX_API_KEY` | `openalex.env` | `resmax-database/accepted_index_builder/fetchers.py` | Soft — journals capped at 100 req/day without |
| `SERPAPI_KEY` | `serpapi.env` | `resmax-database/enrich_abstracts_fallback.py` | Soft — only the Google fallback is skipped |
| `S2_API_KEY` | `s2.env` | `resmax-database/enrich_code_urls.py` | Soft — Semantic Scholar still works, just rate-limited |
| `RESMAX_CONTACT_EMAIL` | `contact.env` | `resmax-database/enrich_abstracts_fallback.py`, `resmax-survey/search_literature_lib/oa_resolvers.py` | Soft — falls back to `resmax@example.com` |

### `.localconfig/`

| Env var | `.env` file | Used by | Hard-required? |
| --- | --- | --- | --- |
| `RESMAX_SSH_HOST` | `server.env` | `resmax-survey` (SSH fallback for query encoding), `resmax-embedding` (docs examples) | **Yes**, when the embedding query cannot be encoded locally and the skill needs to SSH to a GPU server |
| `RESMAX_SSH_REMOTE_SCRIPT` | `server.env` | same | Soft — defaults to `~/resmax_embedding_build/scripts/encode_query.py` |
| `RESMAX_SSH_CONDA_ENV` | `server.env` | same | Soft — defaults to `llm` |
| `RESMAX_SSH_CONDA_INIT` | `server.env` | same | Soft — defaults to `~/miniconda3/etc/profile.d/conda.sh` |
| `RESMAX_HF_DATASET_REPO` | `huggingface.env` | `scripts/resmax_data.py`, `resmax-database/ensure_reviews_available.py` | Soft — defaults to `max6616/resmax`; private access still needs `HF_TOKEN` or `hf auth login` |
| `RESMAX_HF_REVIEWS_PATH`, `RESMAX_HF_REPO_TYPE` | `huggingface.env` | same | Soft — default to `reviews` and `dataset` |

---

## 3. Information supplement protocol (for agents)

All skills read secrets through `.agents/skills/_shared/secrets_loader.py`.
When a hard-required value is missing, that helper raises
`MissingSecretError`, which is printed to the script's stderr with the
fixed prefix:

```
[MISSING_SECRET] {"missing_var": "...", "all_vars": [...], "env_file": "...", "example_file": "...", "purpose": "..."}
```

**Agents MUST handle this as follows:**

1. **Halt the current execution step.** Do not retry, do not fall back
   to a default, do not invent a value.
2. **Parse the JSON payload** after the `[MISSING_SECRET]` prefix.
3. **Prompt the user** in natural language, explaining:
   - which skill needs the value (`purpose`);
   - which env file will store it (`env_file`);
   - which variable(s) must be set (`all_vars`);
   - that `.secrets/` and `.localconfig/` are gitignored.
4. **Persist the answer**: append `export VAR='<user_value>'` to the
   `env_file` (create the file from `example_file` if it does not
   exist), with file mode `0600` for anything under `.secrets/`.
5. **Re-run the original command.** The loader will pick up the new
   value on next invocation.

### Example prompt wording (Chinese + English)

> 这个 skill 需要 `OPENREVIEW_USERNAME` 和 `OPENREVIEW_PASSWORD` 来拉取
> OpenReview 评审数据。本项目从不把凭据写入跟踪文件，请告诉我你要
> 使用的 OpenReview 账号，我会把它保存在 `.secrets/openreview.env`
> （已 gitignore）里。
>
> This skill needs `OPENREVIEW_USERNAME` and `OPENREVIEW_PASSWORD` to
> fetch OpenReview reviews. Credentials never land in tracked files;
> tell me the values and I'll store them in `.secrets/openreview.env`
> (gitignored).

### What the agent should NOT do

- Don't paste the plaintext value into chat history beyond what's
  required to confirm with the user.
- Don't commit the `.env` file (gitignored, but double-check via
  `git status` before any `git add -A`).
- Don't propose hardcoding the value back into a Python script.

### Hugging Face read tokens

Hugging Face read tokens are credentials. Do not write them to tracked files or
to `.localconfig/`. For first-time data restore, `resmax-init --with-data`
prompts for the token and passes it to `scripts/resmax_data.py pull` through the
process environment only. Users who prefer a persistent local login can run
`hf auth login` themselves or set `HF_TOKEN` in their shell.

---

## 4. Adding a new secret

When a new skill starts using an API that needs a key:

1. Add a new template: `.secrets/<name>.env.example` with a comment
   block explaining where to register for the key and which scripts
   consume it.
2. In the consuming script, source the loader:
   ```python
   from secrets_loader import require_secret  # or get_secret for soft
   key = require_secret("NEW_KEY", env_file=".secrets/<name>.env",
                        purpose="<what it unlocks>")
   ```
3. Document the new row in this file's tables above.
4. Update the relevant skill's `SKILL.md` "信息补充指引 / Secrets" section.
