# resmax

<p align="center">
  <img src="./assets/icon.jpeg" alt="resmax" width="256" />
</p>

> Autonomous literature infrastructure for AI research agents.
>
> Encapsulates the repeatable parts of the research literature workflow as reusable Cursor Skills so agents can build paper databases, semantic indexes, and direction-level surveys with consistent quality.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/agent-Cursor%20Skills-black.svg)
![Status](https://img.shields.io/badge/status-active-brightgreen.svg)

**Languages:** [English](README.md) · [中文](README_zh.md)

<!--
Badges are small labels at the top of the README, often from https://shields.io/ ,
embedded with Markdown image syntax. Typical uses: license, Python version, CI status.
-->

---

## Highlights

- **Three skills, filesystem-decoupled** — `resmax-database`, `resmax-embedding`, and `resmax-survey` exchange data via CSV and `.npz` caches only; no runtime coupling, so each stage can be swapped independently.
- **Top AI venues** — Multi-source accepted-list ingestion (OpenReview / OpenAlex / Semantic Scholar, etc.) with automatic enrichment: abstracts, reviews, open-source signals, acceptance tier.
- **Dual retrieval + LLM scoring** — Keyword search combined with Qwen3-Embedding-8B semantic search; merged and deduplicated, then per-paper scoring by a subagent and a final review pass by the main agent.
- **Incremental-friendly and verifiable** — Stable artifacts per stage; `validate_database.py` is the single source of truth for database health.
- **No secrets in the repo** — API keys and machine-specific settings live under `.secrets/` and `.localconfig/`; clone the repo and follow templates to run.

---

## Architecture

```
   Conferences / Journals
              │
              ▼
  ┌─────────────────────┐         paper_database/
  │   resmax-database   │───────▶ ├── accepted_index.csv
  │   fetch + enrich    │         └── reviews/
  └─────────────────────┘
              │
              ▼
  ┌─────────────────────┐
  │  resmax-embedding   │───────▶ paper_database/embedding_cache/*.npz
  │  build vector cache │
  │  (GPU server)       │
  └─────────────────────┘
              │
              ▼
  ┌─────────────────────┐         literature_research/<topic>/
  │   resmax-survey     │───────▶ ├── research_index.csv
  │   retrieve + rank   │         ├── literature_list.md
  └─────────────────────┘         └── filter_log.md
```

Each layer only reads the previous layer's artifacts, so stages can be rerun, swapped out, or replayed with a different embedding model without disturbing the rest of the pipeline.

---

## Repository Structure

```
resmax/
├── .agents/skills/              # Agent Skills (core capabilities)
│   ├── _shared/                 #   cross-skill utilities (secrets_loader, ...)
│   ├── resmax-database/         #   Skill 1: base literature index
│   ├── resmax-embedding/        #   Skill 2: embedding cache on GPU
│   └── resmax-survey/           #   Skill 3: topic-level retrieval + ranking
├── .claude/skills -> ../.agents/skills
├── .codex/skills  -> ../.agents/skills
├── .cursor/skills -> ../.agents/skills
├── scripts/                     # human-facing utility commands
├── paper_database/              # full index + embedding cache (gitignored)
├── cache/                        # internal transfer/cache state (gitignored)
├── literature_research/         # per-topic retrieval outputs (gitignored)
├── .secrets/                    # API credentials (gitignored, templates only)
├── .localconfig/                # machine-specific config (gitignored, templates only)
├── SECRETS.md                   # authoritative guide to credentials & local config
├── requirements.txt             # aggregated Python dependencies
├── LICENSE                      # MIT
├── README.md                    # English (default on GitHub)
└── README_zh.md                 # Chinese
```

`.agents/skills` is the canonical skill source. `.claude/skills`, `.codex/skills`, and `.cursor/skills` are compatibility symlinks so Claude Code, Codex, Cursor, and other Agent Skills-compatible tools can auto-discover the same `SKILL.md` bundles without duplicated files.

> `paper_database/`, `cache/`, and `literature_research/` are gitignored. Inside `.secrets/` and `.localconfig/` only `*.env.example` and `README.md` are tracked.

---

## Prerequisites

| Component | Version / Notes | Required when |
|-----------|-----------------|---------------|
| Python | 3.10+ | all skills |
| Codex, Cursor, or another Agent Skills-compatible agent | with local `SKILL.md` support | driving every workflow in this repo |
| GPU server (optional) | CUDA + `torch` + `transformers` + Qwen3-Embedding-8B | building the embedding cache; local query encoding when the machine is memory-starved |
| External API keys | OpenReview / GitHub / OpenAlex / Semantic Scholar / SerpAPI | `resmax-database` enrichment (mostly soft requirements — scripts degrade gracefully when missing) |

Per-skill Python dependencies are aggregated in `requirements.txt` at the repo root.

> **Note:** `.agents/skills` is the canonical skill directory. Compatibility symlinks such as `.codex/skills`, `.cursor/skills`, and `.claude/skills` point compatible agents at the same skill set when available.

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/max6616/resmax.git
cd resmax
```

### 2. Install Python dependencies

Use a virtualenv or conda env if you prefer.

```bash
python -m pip install -r requirements.txt
```

### 3. Initialize with `resmax-init`

Ask your agent to use the `resmax-init` skill for the target you need, for example:

> Use `resmax-init` to initialize this checkout to `survey-ready`.

The skill runs the audit/materialization script internally, then explains which values are required, which are optional, where they are stored, and how to restore or build missing `paper_database/` artifacts. If large artifacts are missing, it asks one data question:

- no Hugging Face read token: skip private dataset download and build from sources;
- has read token or existing HF login: download `max6616/resmax` into the local runtime layout automatically.

Real credentials stay in gitignored `.secrets/*.env`; machine-specific settings stay in gitignored `.localconfig/*.env`. Hugging Face read tokens are passed through the current process only unless the user explicitly logs in with `hf auth login`. See [`SECRETS.md`](./SECRETS.md) for the full field reference.

For manual debugging without an agent, the internal entrypoint is:

```bash
python3 .agents/skills/resmax-init/scripts/resmax_init_check.py --materialize --with-data
```

### 4. Run workflow skills

After initialization, invoke the workflow skills through your agent:

| Goal | Example triggers | Output |
|------|------------------|--------|
| Build or update the base literature index | "update accepted list" / "build literature base" / "full rebuild" | `paper_database/accepted_index.csv` |
| Build or refresh the embedding cache | "build embedding" / "refresh embedding cache" | `paper_database/embedding_cache/*.npz` |
| Run a topic survey | "literature survey \<topic\>" / "retrieve papers for \<topic\>" | `literature_research/<topic>/` |

When a required value is missing, the agent must stop and ask instead of inventing a value.

---

## Skills

| # | Skill | Role | Main artifacts | SKILL.md |
|---|-------|------|----------------|----------|
| 0 | `resmax-init` | First-time setup: local env files, required/optional fields, database artifact choices | `.secrets/*.env` + `.localconfig/*.env` + setup report | [link](./.agents/skills/resmax-init/SKILL.md) |
| 1 | `resmax-database` | Multi-source accepted-list fetch + batch enrichment (abstracts / reviews / code / acceptance type) | `accepted_index.csv` + `reviews/` | [link](./.agents/skills/resmax-database/SKILL.md) |
| 2 | `resmax-embedding` | Encode title+abstract with Qwen3-Embedding-8B on a GPU server; emit `.npz` cache | `embedding_cache/qwen3_8b.npz` | [link](./.agents/skills/resmax-embedding/SKILL.md) |
| 3 | `resmax-survey`   | Dual retrieval (keyword + embedding) → merge → per-paper scoring → main-agent review → ranked list | `literature_research/<topic>/literature_list.md` | [link](./.agents/skills/resmax-survey/SKILL.md) |

Each skill's internal stages, parameters, error handling and behavioural constraints are documented as an "API manual" inside its own `SKILL.md`, which is the authoritative reference for the agent.

---

## Configuration

All machine-specific or private values stay out of git via two sibling directories:

| Directory | Purpose | Typical variables |
|-----------|---------|-------------------|
| `.secrets/` | API credentials, personal identifiers | `OPENREVIEW_USERNAME`, `GITHUB_TOKEN`, `OPENALEX_API_KEY`, `S2_API_KEY`, `SERPAPI_KEY`, `RESMAX_CONTACT_EMAIL` |
| `.localconfig/` | Machine runtime settings | `RESMAX_SSH_HOST`, `RESMAX_SSH_REMOTE_DIR`, `RESMAX_SSH_CONDA_ENV`, `RESMAX_HF_DATASET_REPO` |

Loader implementation, hard-vs-soft requirements, and the agent's standard response to a missing secret are all described in [`SECRETS.md`](./SECRETS.md).

---

## Data Outputs

| Path | Producer | Contents |
|------|----------|----------|
| `paper_database/accepted_index.csv` | `resmax-database` | Canonical base literature index (CSV = single source of truth) |
| `paper_database/reviews/` | `resmax-database` | Per-venue OpenReview review JSON dumps |
| `paper_database/embedding_cache/*.npz` | `resmax-embedding` | Vector matrix aligned row-wise with `accepted_index.csv` |
| `paper_database/accepted_index_coverage_report.md` | `resmax-database` | Metadata coverage health report |
| `literature_research/<topic>/research_index.csv` | `resmax-survey` | Topic-level subset of hits |
| `literature_research/<topic>/literature_list.md` | `resmax-survey` | Final ranked list (with scores and rationales) |
| `literature_research/<topic>/filter_log.md` | `resmax-survey` | Filter / scoring pipeline log |
| `cache/huggingface/resmax/` | `scripts/resmax_data.py` | Internal Hugging Face transfer mirror for `accepted_index.csv`, `manifest.json`, `qwen3_8b.npz`, and packaged `reviews/` |

All of the above directories are gitignored — they are reproducible artifacts.

For maintainers, the same data command handles upload preparation and upload:

```bash
python3 scripts/resmax_data.py push
```

---

## Roadmap

- [ ] **Fetcher coverage** — CVPR / ICCV / SIGGRAPH and similar camera-ready venues
- [ ] **arXiv daily incremental ingestion** into the base index
- [ ] **Code quality auto-profile** for S/A-tier repositories during `resmax-survey`
- [ ] **Alternative embedding models** (e.g. BGE / E5) with side-by-side comparison
- [ ] **Package as a Cursor plugin** + broaden agent support beyond Cursor (generic CLI / other agent frameworks)
- [ ] **Tech-stack survey from S/A papers** — starting from S/A-tier accepted papers, aggregate the baselines, datasets, and base models they cite/use, to surface the mainstream technical routes of a given direction at a glance
- [ ] **Query keyword management** — inspect how keywords and query vectors are currently produced (e.g. can a full research proposal be embedded as a single vector? how should the most important keywords be auto-summarised from an ongoing conversation?) and build a dedicated keyword / query-intent module

---

## License

Released under the [MIT License](./LICENSE). © 2026 Zhao Zhang.

---

## Citation

If you use resmax in academic work, please cite:

```bibtex
@software{zhang2026resmax,
  author  = {Zhao Zhang},
  title   = {resmax: Autonomous Literature Infrastructure for AI Research Agents},
  year    = {2026},
  url     = {https://github.com/max6616/resmax}
}
```

---

## Acknowledgements

resmax builds on top of the following third-party services, models, and tools:

- **Metadata & indexing** — [OpenReview](https://openreview.net/), [OpenAlex](https://openalex.org/), [Semantic Scholar](https://www.semanticscholar.org/), [arXiv](https://arxiv.org/), [DBLP](https://dblp.org/), [Crossref](https://www.crossref.org/), [Unpaywall](https://unpaywall.org/)
- **Code hosting & quality signals** — [GitHub REST API](https://docs.github.com/en/rest), [Hugging Face Hub](https://huggingface.co/)
- **Full-text extraction** — [MinerU](https://github.com/opendatalab/MinerU) (MCP server), [PyMuPDF](https://pymupdf.readthedocs.io/), [arxiv-to-prompt](https://pypi.org/project/arxiv-to-prompt/)
- **Semantic embedding** — [Qwen3-Embedding-8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B) by Alibaba, served through [🤗 Transformers](https://github.com/huggingface/transformers) and quantized with [bitsandbytes](https://github.com/TimDettmers/bitsandbytes)
- **Web search fallback** — [SerpAPI](https://serpapi.com/)
- **Agent runtime** — [Cursor](https://cursor.com/) Agent Skills platform
