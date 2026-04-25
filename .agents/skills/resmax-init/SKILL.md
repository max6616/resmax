---
name: resmax-init
description: Initialize a freshly cloned Resmax checkout. Use when Codex needs to guide first-time setup, materialize local env files from templates, collect required API keys or machine config through questions, restore or build paper_database artifacts, explain hard vs soft requirements, and verify the repo is ready for resmax-database, resmax-embedding, or resmax-survey.
---

# resmax-init

## 目标

用于新 clone 的 `resmax` 仓库初始化：生成本地 `.env`、通过问答补齐必要配置、选择数据库/评审/embedding 产物来源，并把最终状态验证到能安全进入生产流程。

不要把它当成“静默 bootstrap 脚本”。用户相关的决定必须显式询问；脚本只负责审计状态和给出缺口。

## 固定入口

当用户要求执行 `resmax-init` skill 时，agent 先运行审计；新 clone 或模板缺失时加 `--materialize`。如果初始化目标需要同时处理大文件数据恢复，加 `--with-data`。这些命令是 skill 内部入口，不是 README 面向普通用户的主流程：

```bash
python3 .agents/skills/resmax-init/scripts/resmax_init_check.py --materialize
```

```bash
python3 .agents/skills/resmax-init/scripts/resmax_init_check.py --materialize --with-data
```

需要机器可读输出时：

```bash
python3 .agents/skills/resmax-init/scripts/resmax_init_check.py --materialize --json
```

普通审计只创建空的本地 `.env`，不会填入密钥，不会下载数据，不会启动长任务。`--with-data` 是交互模式：当 `accepted_index.csv`、`manifest.json`、`qwen3_8b.npz` 或 review package 缺失时，必须先询问用户是否有 `max6616/resmax` 私有 HF dataset 的 read token。

## 问答原则

- 所有用户特定信息都用提问获得，不猜测、不硬编码。
- 选择类问题提供有限选项；例如初始化目标、数据库来源、是否允许 Sci-Hub、是否配置远程 GPU。
- API key、密码、token、用户名、邮箱、SSH host、HF repo id 使用自由填写；不要提供假选项。
- optional / soft 字段允许用户留空；说明留空后的降级结果。
- hard-required 字段缺失时，终止当前步骤，说明需要哪个值、写入哪个 `.env`、为什么需要，然后等待用户补充。
- 如果当前客户端支持结构化提问工具，choice 问题用选项，secret/config 问题用自由输入；否则在聊天里逐题问。不要在最终回复复述密钥原文。

## 初始化问卷

按审计结果裁剪问题，避免一次性索要无关信息。

### 1. 初始化目标

先问用户要做到哪一层：

1. `config-only`：只补配置文件，不准备数据库。
2. `database-ready`：准备 `accepted_index.csv`、manifest、reviews；若没有 embedding cache，只能算数据库层准备好，不能宣称 validator `overall=PASS`。
3. `survey-ready`：数据库和 embedding cache 都可用，可跑 `resmax-survey` 生产检索。
4. `embedding-build`：配置远程 GPU 并构建/刷新 embedding cache。

### 2. 大文件数据来源

如果 `paper_database/accepted_index.csv`、`paper_database/manifest.json`、`paper_database/embedding_cache/qwen3_8b.npz` 或 `paper_database/hf_export/reviews/reviews_manifest.json` 任一缺失，只问一个问题：

1. `skip-no-token-build-from-sources`：用户没有 read token，完全跳过 HF 文件下载；明确提示需要用 `resmax-database` 从头构建 CSV/reviews，再用 `resmax-embedding` 构建 `.npz`，不能把当前状态当成 `survey-ready`。
2. `use-read-token-download`：用户有 read token，读取 token 后自动调用统一数据命令：

```bash
python3 scripts/resmax_data.py pull --repo-id max6616/resmax
```

token 不写入 git-tracked 文件，也不写入 `.localconfig/`；只通过本次进程环境传给下载脚本。若用户已经 `hf auth login` 或设置了 `HF_TOKEN`，token 输入可留空。

### 3. 从源头构建时的 embedding

如果用户选择 `skip-no-token-build-from-sources`，CSV/reviews 需要先由 `resmax-database` 从源头构建，embedding 再按生产目标处理：

1. `remote-build`：配置 SSH GPU 并运行 `resmax-embedding`。
2. `skip-production`：只允许开发 smoke 的关键词降级，不能作为生产验收。

### 4. 灰色来源策略

Sci-Hub 默认关闭。只有用户明确选择才可在 Stage 5.5 deepcheck 传 `--enable-sci-hub`：

1. `disabled`：默认；只使用合法 OA / publisher / arXiv / OpenReview 等来源。
2. `ask-each-time`：每次 deepcheck 前再确认。
3. `enabled-for-this-run`：仅本次运行允许；不要写成全局默认。

如用户选择启用且需要自定义镜像，再让用户自由填写 `RESMAX_SCI_HUB_MIRRORS`；否则不要创建该变量。

## 配置字段规则

硬依赖：

- `OPENREVIEW_USERNAME` / `OPENREVIEW_PASSWORD`：仅在 OpenReview fetch 模式必填；`--rehydrate` / `--mark-unavailable` 不需要。
- `RESMAX_SSH_HOST`：仅当本机无法编码 query 且需要 SSH fallback，或要远程构建 embedding 时必填。
- `RESMAX_HF_DATASET_REPO`：非密钥，默认 `max6616/resmax`；只有使用自定义 HF dataset repo 时需要修改。

软依赖：

- `GITHUB_TOKEN`：缺失时 GitHub API 降到 60 req/h。
- `OPENALEX_API_KEY`：缺失时期刊抓取额度低。
- `S2_API_KEY`：缺失时 Semantic Scholar 仍可用但更容易限流。
- `SERPAPI_KEY`：缺失时跳过 Google fallback。
- `RESMAX_CONTACT_EMAIL`：缺失时使用默认联系邮箱，礼貌池和限流表现可能变差。
- `RESMAX_SSH_REMOTE_DIR` / `RESMAX_SSH_REMOTE_SCRIPT` / `RESMAX_SSH_CONDA_ENV` / `RESMAX_SSH_CONDA_INIT`：有模板默认值，按用户机器修改。
- `RESMAX_HF_REVIEWS_PATH` / `RESMAX_HF_REPO_TYPE`：有默认值，通常无需改。

## 写入协议

- 真实值只写入 `.secrets/*.env` 或 `.localconfig/*.env`，这些文件被 gitignore。
- `.secrets/*.env` 创建或改写后设置为 `0600`。
- 如果目标 `.env` 不存在，先从对应 `.env.example` 复制。
- 写入格式使用 `export KEY='value'`；已有同名 key 时更新，不重复追加。
- 不要把用户密钥写入 `README`、`SKILL.md`、Python 脚本、git-tracked config 或最终总结。

## 执行路线

配置完成后按目标运行：

`database-ready`：

```bash
python3 scripts/resmax_data.py pull --repo-id max6616/resmax
```

如果没有 HF read token，则使用从源头构建路线：

```bash
python3 .agents/skills/resmax-database/scripts/normalize_database.py \
  --csv paper_database/accepted_index.csv \
  --manifest paper_database/manifest.json

python3 .agents/skills/resmax-database/scripts/ensure_reviews_available.py \
  --csv paper_database/accepted_index.csv \
  --reviews-dir paper_database/reviews \
  --package-dir paper_database/hf_export/reviews
```

如果 embedding cache 已存在，继续跑完整验证：

```bash
python3 .agents/skills/resmax-database/scripts/validate_database.py \
  --csv paper_database/accepted_index.csv \
  --cache paper_database/embedding_cache/qwen3_8b.npz \
  --manifest paper_database/manifest.json \
  --out paper_database/validate_report.json
```

如果 embedding cache 不存在，停止在数据库层并明确告诉用户：`validate_database.py` 的 hard requirement 包含 cache 对齐，不能把该状态当成 `survey-ready`。

`survey-ready`：先确保 `database-ready`，再确认 embedding cache 存在且 validator `overall=PASS`。缺 cache 时转 `resmax-embedding`，不要绕过生产门槛。

`embedding-build`：转 `resmax-embedding`，先确认远程 GPU 空闲，再运行长任务。

## 终止条件

- hard-required 值缺失且用户未提供：停止，不重试。
- 用户选择 `skip-no-token-build-from-sources`：停止 HF 下载路线，只报告从源头构建 CSV/reviews 和 embedding 的下一步。
- 下载、checksum、CSV hash、manifest 或 validator 失败：停止并报告失败原因，不降级。
- 用户未明确允许 Sci-Hub：不得启用 Sci-Hub fallback。
