# resmax

> Autonomous literature infrastructure for AI research agents.
>
> 面向 AI agent 的自动化科研文献基础设施 — 将科研流程中可标准化的文献环节封装为可复用 skill，让 agent 高质量地完成论文库构建、语义索引与方向级调研。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/agent-Cursor%20Skills-black.svg)
![Status](https://img.shields.io/badge/status-active-brightgreen.svg)

<!--
关于徽章 (badges) 的说明：
徽章就是 README 顶部这些小标签图片，常见来源是 https://shields.io/ ，
用 Markdown 图片语法 `![alt](url)` 嵌入，点击可以跳到对应链接（例如 License 徽章跳到 LICENSE 文件）。
典型用途包括展示许可证、Python 版本、CI 状态、版本号等，属于"一眼看清项目元信息"的门面元素。
-->

---

## Highlights

- **三 skill 协同、文件系统解耦** — `resmax-database` / `resmax-embedding` / `resmax-survey` 彼此通过 CSV 与 `.npz` 缓存交换数据，无运行时依赖，可独立替换。
- **AI 顶会/顶刊覆盖** — 基于 OpenReview / OpenAlex / Semantic Scholar 等多源抓取 accepted list，自动补全摘要、评审、开源信息、录用等级。
- **双路检索 + LLM 评分** — 关键词检索 ⊕ Qwen3-Embedding-8B 语义检索，合并去重后由 subagent 逐篇评分，主 agent 再复核。
- **增量友好 + 可验证** — 每个阶段输出稳定文件，`validate_database.py` 作为数据库可用性的单一事实源。
- **凭据零入库** — 所有 API key / 机器相关配置通过 `.secrets/` 与 `.localconfig/` 管理，clone 即可跑通模板流程。

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
├── .cursor/skills/              # Cursor Agent Skills (core capabilities)
│   ├── _shared/                 #   cross-skill utilities (secrets_loader, ...)
│   ├── resmax-database/         #   Skill 1: base literature index
│   ├── resmax-embedding/        #   Skill 2: embedding cache on GPU
│   └── resmax-survey/           #   Skill 3: topic-level retrieval + ranking
├── paper_database/              # full index + embedding cache (gitignored)
├── literature_research/         # per-topic retrieval outputs (gitignored)
├── .secrets/                    # API credentials (gitignored, templates only)
├── .localconfig/                # machine-specific config (gitignored, templates only)
├── SECRETS.md                   # authoritative guide to credentials & local config
├── requirements.txt             # aggregated Python dependencies
├── LICENSE                      # MIT
└── README.md
```

> `paper_database/` and `literature_research/` are gitignored. Inside `.secrets/` and `.localconfig/` only `*.env.example` and `README.md` are tracked.

---

## Prerequisites

| Component | Version / Notes | Required when |
|-----------|-----------------|---------------|
| Python | 3.10+ | all skills |
| [Cursor](https://cursor.com/) IDE or CLI | with Agent Skills support | driving every workflow in this repo |
| GPU server (optional) | CUDA + `torch` + `transformers` + Qwen3-Embedding-8B | building the embedding cache; local query encode when the laptop is memory-starved |
| External API keys | OpenReview / GitHub / OpenAlex / Semantic Scholar / SerpAPI | `resmax-database` enrichment (mostly soft requirements — scripts degrade gracefully when missing) |

Per-skill Python dependencies are aggregated in `requirements.txt` at the repo root.

> **Note — Cursor-only for now.** Every workflow in this repo is currently driven by Cursor Agent reading the corresponding `SKILL.md`. Support for a more generic agent architecture (e.g. plain CLI entrypoints, other agent frameworks) is on the [Roadmap](#roadmap).

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/max6616/resmax.git
cd resmax

# Python deps (use a virtualenv / conda env if you like)
python -m pip install -r requirements.txt
```

### 2. Configure credentials and local paths

```bash
# Materialize local .env files from the tracked templates (gitignored)
for f in .secrets/*.env.example .localconfig/*.env.example; do
  cp "$f" "${f%.example}"
done

# Fill in your API keys, SSH alias, conda env name, etc.
$EDITOR .secrets/*.env .localconfig/*.env
```

See [`SECRETS.md`](./SECRETS.md) for the full field-by-field reference and the "missing-secret handling protocol" used by every skill.

### 3. Trigger skills from Cursor

The three skills are invoked through Cursor Agent via natural-language triggers:

| Goal | Trigger (examples) | Output |
|------|-------------------|--------|
| Build or update the base literature index | "更新 accepted" / "build literature base" / "全量重建" | `paper_database/accepted_index.csv` |
| Build or refresh the embedding cache | "build embedding" / "更新 embedding" | `paper_database/embedding_cache/*.npz` |
| Run a topic survey | "检索文献 \<topic\>" / "文献调研 \<topic\>" | `literature_research/<topic>/` |

The agent will read the matching `SKILL.md` and execute the stages in order. When a required secret is missing, it halts and asks you for the value as described in `SECRETS.md`.

---

## Skills

| # | Skill | Role | Main artifacts | SKILL.md |
|---|-------|------|----------------|----------|
| 1 | `resmax-database` | Multi-source accepted-list fetch + batch enrichment (abstracts / reviews / code / acceptance type) | `accepted_index.csv` + `reviews/` | [link](./.cursor/skills/resmax-database/SKILL.md) |
| 2 | `resmax-embedding` | Encode title+abstract with Qwen3-Embedding-8B on a GPU server; emit `.npz` cache | `embedding_cache/qwen3_8b.npz` | [link](./.cursor/skills/resmax-embedding/SKILL.md) |
| 3 | `resmax-survey`   | Dual retrieval (keyword + embedding) → merge → per-paper scoring → main-agent review → ranked list | `literature_research/<topic>/literature_list.md` | [link](./.cursor/skills/resmax-survey/SKILL.md) |

Each skill's internal stages, parameters, error handling and behavioural constraints are documented as an "API manual" inside its own `SKILL.md`, which is the authoritative reference for the agent.

---

## Configuration

All machine-specific or private values stay out of git via two sibling directories:

| Directory | Purpose | Typical variables |
|-----------|---------|-------------------|
| `.secrets/` | API credentials, personal identifiers | `OPENREVIEW_USERNAME`, `GITHUB_TOKEN`, `OPENALEX_API_KEY`, `S2_API_KEY`, `SERPAPI_KEY`, `RESMAX_CONTACT_EMAIL` |
| `.localconfig/` | Machine runtime settings | `RESMAX_SSH_HOST`, `RESMAX_SSH_REMOTE_DIR`, `RESMAX_SSH_CONDA_ENV` |

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

All of the above directories are gitignored — they are reproducible artifacts.

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
