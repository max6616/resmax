# resmax

<p align="center">
  <img src="./assets/icon.jpeg" alt="resmax" width="256" />
</p>

> 面向 AI agent 的自动化科研文献基础设施。
>
> 将科研流程中可标准化的文献环节封装为可复用 Skill，让 agent 高质量地完成论文库构建、语义索引、方向级调研、证据锚定的 idea portfolio 与 blocker-first review tournament。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![Platform](https://img.shields.io/badge/agent-Cursor%20Skills-black.svg)
![Status](https://img.shields.io/badge/status-active-brightgreen.svg)

**语言：** [English](README.md) · [中文](README_zh.md)

<!--
徽章即 README 顶部的小标签图片，常见来源为 https://shields.io/ ，
使用 Markdown 图片语法嵌入；常用于展示许可证、Python 版本、CI 状态等元信息。
-->

---

## 亮点

- **五个工作流 Skill 协同、文件系统解耦** — `resmax-database` / `resmax-embedding` / `resmax-survey` / `resmax-idea` / `resmax-review` 只通过稳定文件产物交换数据，无运行时依赖，可独立替换。
- **AI 顶会/顶刊覆盖** — 基于 OpenReview / OpenAlex / Semantic Scholar 等多源抓取录用列表，自动补全摘要、评审、开源信息、录用等级。
- **双路检索 + LLM 评分** — 关键词检索与 Qwen3-Embedding-8B 语义检索合并去重后，由 subagent 逐篇评分，主 agent 再复核。
- **增量友好 + 可验证** — 每个阶段输出稳定文件，`validate_database.py` 作为数据库可用性的单一事实源。
- **凭据零入库** — 所有 API key 与机器相关配置通过 `.secrets/` 与 `.localconfig/` 管理，按模板配置后即可跑通流程。

---

## 架构

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
  └─────────────────────┘         ├── research_pack/
              │                   └── filter_log.md
              ▼
  ┌─────────────────────┐         literature_research/<topic>/ideas/
  │    resmax-idea      │───────▶ ├── idea_cards.jsonl
  │  compile portfolio  │         └── idea_report.md
  └─────────────────────┘
              │
              ▼
  ┌─────────────────────┐         literature_research/<topic>/reviews/
  │    resmax-review    │───────▶ ├── raw/<reviewer>/<idea_id>.json
  │  blocker tournament │         └── promoted/killed/revise/human_gate JSONL
  └─────────────────────┘
```

每一层只读取上一层的产物，因此可单独重跑、替换某阶段，或在不影响其余流水线的情况下更换嵌入模型。

---

## 仓库结构

```
resmax/
├── .agents/skills/              # Agent Skills（核心能力）
│   ├── _shared/                 #   跨 Skill 工具（secrets_loader 等）
│   ├── resmax-database/         #   Skill 1：基础文献索引
│   ├── resmax-embedding/        #   Skill 2：GPU 上构建 embedding 缓存
│   ├── resmax-survey/           #   Skill 3：方向级检索与 ResearchPack
│   ├── resmax-idea/             #   Skill 4：ResearchPack -> idea portfolio
│   └── resmax-review/           #   Skill 5：raw reviews -> blocker tournament
├── .claude/skills -> ../.agents/skills
├── .codex/skills  -> ../.agents/skills
├── .cursor/skills -> ../.agents/skills
├── scripts/                     # 面向人的统一工具命令
├── paper_database/              # 完整索引 + embedding 缓存（git 忽略）
├── cache/                        # 内部传输与缓存状态（git 忽略）
├── literature_research/         # 按主题的检索输出（git 忽略）
├── .secrets/                    # API 凭据（git 忽略，仅跟踪模板）
├── .localconfig/                # 机器相关配置（git 忽略，仅跟踪模板）
├── SECRETS.md                   # 凭据与本地配置的权威说明
├── requirements.txt             # 汇总的 Python 依赖
├── LICENSE                      # MIT
├── README.md                    # 英文（GitHub 默认展示）
└── README_zh.md                 # 中文
```

`.agents/skills` 是唯一 canonical skill 源目录。`.claude/skills`、`.codex/skills`、`.cursor/skills` 都是兼容 symlink，使 Claude Code、Codex、Cursor 以及其他兼容 Agent Skills 的工具能自动发现同一套 `SKILL.md`，避免复制多份脚本。

> `paper_database/`、`cache/` 与 `literature_research/` 已被 git 忽略。`.secrets/` 与 `.localconfig/` 中仅跟踪 `*.env.example` 与 `README.md`。

---

## 环境要求

| 组件 | 版本 / 说明 | 何时需要 |
|------|-------------|----------|
| Python | 3.10+ | 全部 Skill |
| Codex、Cursor 或其他兼容 Agent Skills 的 agent | 支持本地 `SKILL.md` | 驱动本仓库内所有工作流 |
| GPU 服务器（可选） | CUDA + `torch` + `transformers` + Qwen3-Embedding-8B | 构建 embedding 缓存；本机内存紧张时可在远端编码查询 |
| 外部 API 密钥 | OpenReview / GitHub / OpenAlex / Semantic Scholar / SerpAPI | `resmax-database` 元数据补全（多为软依赖，缺失时脚本会降级） |

各 Skill 的 Python 依赖已汇总到仓库根目录的 `requirements.txt`。

> **说明：** `.agents/skills` 是唯一 canonical skill 目录。可用时，`.codex/skills`、`.cursor/skills`、`.claude/skills` 等兼容 symlink 指向同一套 skill。

---

## 快速开始

### 1. 克隆

```bash
git clone https://github.com/max6616/resmax.git
cd resmax
```

### 2. 安装 Python 依赖

建议使用 virtualenv 或 conda 环境。

```bash
python -m pip install -r requirements.txt
```

### 3. 使用 `resmax-init` 初始化

让 agent 使用 `resmax-init` skill 完成本次目标，例如：

> 使用 `resmax-init` 将当前仓库初始化到 `survey-ready`。

这个 skill 会在内部运行审计和本地模板初始化脚本，然后说明哪些值必填、哪些可选、写入哪个文件，以及缺失的 `paper_database/` 产物如何恢复。若大文件产物缺失，它只问一个数据问题：

- 没有 Hugging Face read token：完全跳过私有数据仓库下载，提示从源头构建；
- 有 read token 或已有 HF 登录态：自动从 `max6616/resmax` 下载并恢复到本地运行时目录。

真实凭据只写入 gitignore 的 `.secrets/*.env`，机器相关配置只写入 gitignore 的 `.localconfig/*.env`。Hugging Face read token 默认只通过当前进程传递，除非用户主动执行 `hf auth login`。完整字段说明见 [`SECRETS.md`](./SECRETS.md)。

如果不通过 agent、只想手工调试，内部入口是：

```bash
python3 .agents/skills/resmax-init/scripts/resmax_init_check.py --materialize --with-data
```

### 4. 运行工作流 Skill

初始化后，通过 agent 触发工作流 skill：

| 目标 | 示例触发语 | 输出 |
|------|------------|------|
| 构建或更新基础文献索引 | 「更新 accepted」/ 「build literature base」/ 「全量重建」 | `paper_database/accepted_index.csv` |
| 构建或刷新 embedding 缓存 | 「build embedding」/ 「更新 embedding」 | `paper_database/embedding_cache/*.npz` |
| 执行某一主题的文献调研 | 「检索文献 \<topic\>」/ 「文献调研 \<topic\>」 | `literature_research/<topic>/` |
| 生成 idea portfolio | 「从这个 ResearchPack 生成 idea」/ 「执行 resmax-idea」 | `literature_research/<topic>/ideas/` |
| 评审 idea portfolio | 「review this idea portfolio」/ 「执行 resmax-review」 | `literature_research/<topic>/reviews/` |

如果缺少必需值，agent 必须暂停并向你索要，不能编造默认值。

---

## Skill 一览

| # | Skill | 职责 | 主要产物 | SKILL.md |
|---|-------|------|----------|----------|
| 0 | `resmax-init` | 首次初始化：本地 env、必填/可选字段、数据库产物来源选择 | `.secrets/*.env` + `.localconfig/*.env` + setup report | [链接](./.agents/skills/resmax-init/SKILL.md) |
| 1 | `resmax-database` | 多源录用列表抓取 + 批量补全（摘要 / 评审 / 代码 / 录用类型） | `accepted_index.csv` + `reviews/` | [链接](./.agents/skills/resmax-database/SKILL.md) |
| 2 | `resmax-embedding` | 在 GPU 服务器上对标题+摘要用 Qwen3-Embedding-8B 编码，输出 `.npz` 缓存 | `embedding_cache/qwen3_8b.npz` | [链接](./.agents/skills/resmax-embedding/SKILL.md) |
| 3 | `resmax-survey`   | 双路检索 + evidence-first ResearchPack + ROI-aware gap lens | `literature_research/<topic>/research_pack/` | [链接](./.agents/skills/resmax-survey/SKILL.md) |
| 4 | `resmax-idea` | 将 validated ResearchPack 编译为 IdeaCards、lineage、closest-work checks 与 falsification notes | `literature_research/<topic>/ideas/` | [链接](./.agents/skills/resmax-idea/SKILL.md) |
| 5 | `resmax-review` | 保存异质 raw reviews、聚合 blockers 并运行 pairwise tournament | `literature_research/<topic>/reviews/` | [链接](./.agents/skills/resmax-review/SKILL.md) |

各 Skill 的内部阶段、参数、错误处理与行为约束均写在其 `SKILL.md` 中，作为面向 agent 的权威「API 手册」。

---

## 配置说明

机器相关或私密信息通过两个并列目录留在 git 之外：

| 目录 | 用途 | 典型变量 |
|------|------|----------|
| `.secrets/` | API 凭据、个人标识 | `OPENREVIEW_USERNAME`, `GITHUB_TOKEN`, `OPENALEX_API_KEY`, `S2_API_KEY`, `SERPAPI_KEY`, `RESMAX_CONTACT_EMAIL` |
| `.localconfig/` | 机器运行时设置 | `RESMAX_SSH_HOST`, `RESMAX_SSH_REMOTE_DIR`, `RESMAX_SSH_CONDA_ENV`, `RESMAX_HF_DATASET_REPO` |

加载器实现、硬/软依赖划分，以及密钥缺失时的标准应对方式见 [`SECRETS.md`](./SECRETS.md)。

---

## 数据产物

| 路径 | 产出方 | 内容 |
|------|--------|------|
| `paper_database/accepted_index.csv` | `resmax-database` | 规范的基础文献索引（CSV 为单一事实源） |
| `paper_database/reviews/` | `resmax-database` | 按会议的 OpenReview 评审 JSON 导出 |
| `paper_database/embedding_cache/*.npz` | `resmax-embedding` | 与 `accepted_index.csv` 行对齐的向量矩阵 |
| `paper_database/accepted_index_coverage_report.md` | `resmax-database` | 元数据覆盖健康报告 |
| `literature_research/<topic>/research_index.csv` | `resmax-survey` | 主题级命中子集 |
| `literature_research/<topic>/literature_list.md` | `resmax-survey` | 最终排序列表（含分数与理由） |
| `literature_research/<topic>/filter_log.md` | `resmax-survey` | 过滤 / 打分流水线日志 |
| `literature_research/<topic>/research_pack/` | `resmax-survey` | Evidence、ClaimGraph、GapMap、reviewer pressure、paper roles 与 ROI lens |
| `literature_research/<topic>/ideas/` | `resmax-idea` | IdeaCards、lineage、closest-work checks、拒稿理由与最小证伪 notes |
| `literature_research/<topic>/reviews/` | `resmax-review` | Evidence packages、raw ReviewTrace JSON、blocker aggregation、tournament trace 与 promoted/killed/revise/human_gate JSONL |
| `cache/huggingface/resmax/` | `scripts/resmax_data.py` | 内部 Hugging Face 传输镜像，包含 `accepted_index.csv`、`manifest.json`、`qwen3_8b.npz` 和压缩后的 `reviews/` |

上述目录均被 git 忽略，属于可复现产物。

维护者上传数据也走同一个统一命令：

```bash
python3 scripts/resmax_data.py push
```

---

## 路线图

- [ ] **抓取覆盖** — CVPR / ICCV / SIGGRAPH 等 camera-ready 会议
- [ ] **arXiv 日更增量** 汇入基础索引
- [ ] **代码质量自动画像** — 在 `resmax-survey` 中对 S/A 档仓库做侧写
- [ ] **备选嵌入模型**（如 BGE / E5）与并列对比
- [ ] **打包为 Cursor 插件** + 扩展到非 Cursor 的通用 CLI / 其他 agent 框架
- [ ] **基于 S/A 论文的技术栈调研** — 从 S/A 录用论文聚合其引用/使用的基线、数据集与基础模型，一览某方向主流技术路线
- [ ] **查询关键词管理** — 梳理关键词与查询向量如何生成（例如整份研究方案能否压成单向量、如何从对话中自动摘要关键词），并建设独立的关键词 / 查询意图模块

---

## 许可证

以 [MIT License](./LICENSE) 发布。© 2026 Zhao Zhang。

---

## 引用

若在学术工作中使用 resmax，请引用：

```bibtex
@software{zhang2026resmax,
  author  = {Zhao Zhang},
  title   = {resmax: Autonomous Literature Infrastructure for AI Research Agents},
  year    = {2026},
  url     = {https://github.com/max6616/resmax}
}
```

---

## 致谢

resmax 依赖以下第三方服务、模型与工具：

- **元数据与索引** — [OpenReview](https://openreview.net/)、[OpenAlex](https://openalex.org/)、[Semantic Scholar](https://www.semanticscholar.org/)、[arXiv](https://arxiv.org/)、[DBLP](https://dblp.org/)、[Crossref](https://www.crossref.org/)、[Unpaywall](https://unpaywall.org/)
- **代码托管与质量信号** — [GitHub REST API](https://docs.github.com/en/rest)、[Hugging Face Hub](https://huggingface.co/)
- **全文抽取** — [MinerU](https://github.com/opendatalab/MinerU)（MCP 服务）、[PyMuPDF](https://pymupdf.readthedocs.io/)、[arxiv-to-prompt](https://pypi.org/project/arxiv-to-prompt/)
- **语义嵌入** — 阿里 [Qwen3-Embedding-8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B)，经 [🤗 Transformers](https://github.com/huggingface/transformers) 与 [bitsandbytes](https://github.com/TimDettmers/bitsandbytes) 量化服务
- **网页搜索兜底** — [SerpAPI](https://serpapi.com/)
- **Agent 运行时** — [Cursor](https://cursor.com/) Agent Skills 平台
