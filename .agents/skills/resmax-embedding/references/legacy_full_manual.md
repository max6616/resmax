---
name: resmax-embedding
description: 在 GPU 服务器上构建和维护论文 embedding 缓存。读取 resmax-database 产出的 accepted_index.csv，输出 .npz 缓存供 resmax-survey 消费。
---

# resmax-embedding

## 所属体系

本 skill 属于 resmax 自动化科研文献基础设施，位于 `resmax-database` 和 `resmax-survey` 之间。

数据流：`resmax-database` 产出 `accepted_index.csv` → 本 skill 构建 embedding 缓存 → `resmax-survey` 消费缓存进行向量检索。

| 上游依赖 | 说明 |
|----------|------|
| `paper_database/accepted_index.csv` | resmax-database 产出的基础文献索引，必须包含 `paper_id`、`title`、`abstract_raw` 字段 |

| 下游消费方 | 说明 |
|-----------|------|
| `resmax-survey` | 读取 `.npz` 缓存做 embedding 检索，通过 SSH 调用 `encode_query.py` 编码查询向量 |

## 路径约定

```bash
SKILL_ROOT=.agents/skills/resmax-embedding
```

## 触发词

"build cache", "build embedding", "更新embedding", "构建缓存", "增量更新缓存"

## 主 agent 行为约束

1. **禁止主 agent 读取 `$SKILL_ROOT/scripts/` 下的任何源码**。脚本是黑盒工具，本文档是其 API 文档。
2. **前置检查是硬性要求**：每次构建前必须先确认 GPU 可用性，禁止盲目启动。

## 服务器参数（硬性必填）

本 skill 从 `.localconfig/server.env` 读取所有远程执行参数，**不接受代码中
写死的默认值**。首次使用前，主 agent 必须确认这些变量已填，否则 SSH 调用
会抛 `[MISSING_SECRET]` 错误并终止。详细填写方式见 `.localconfig/README.md`
及仓库根目录 `SECRETS.md`。

| 环境变量 | 说明 | 示例 | 必填 |
|----------|------|------|------|
| `RESMAX_SSH_HOST` | 服务器的 SSH 地址或 `~/.ssh/config` 别名 | `5090` / `user@192.168.1.100` | **是** |
| `RESMAX_SSH_REMOTE_DIR` | 服务器上存放脚本和缓存的工作目录 | `~/resmax_embedding_build` | 否（默认同示例） |
| `RESMAX_SSH_REMOTE_SCRIPT` | encode_query.py 的远程绝对/~ 路径 | `~/resmax_embedding_build/scripts/encode_query.py` | 否 |
| `RESMAX_SSH_CONDA_ENV` | 含 torch/transformers/numpy 的 conda env 名 | `llm` | 否（默认 `llm`） |
| `RESMAX_SSH_CONDA_INIT` | conda.sh 的远程路径（miniconda3 或 miniforge3） | `~/miniconda3/etc/profile.d/conda.sh` | 否 |

### 信息补充指引（首次使用或缺参数时的标准流程）

主 agent 在调用本 skill 时，若脚本 stderr 出现：

```
[MISSING_SECRET] {"missing_var": "RESMAX_SSH_HOST", ..., "env_file": ".localconfig/server.env", ...}
```

必须：

1. **立即终止当前 stage**，禁止猜测别名或复用示例值（如 `5090`）。
2. 向用户说明：本 skill 需要 SSH 到 GPU 服务器编码 embedding，请提供上表
   中的 `RESMAX_SSH_HOST`（以及其它未填项），并告知用户 `.localconfig/`
   已 gitignore，不会被提交。
3. 把用户答复追加到 `.localconfig/server.env`（不存在则从
   `.localconfig/server.env.example` 拷贝），`export VAR='...'` 格式。
4. 重新执行原命令；`secrets_loader` 会在下一次 import 时自动加载。

主 agent 在执行前还需要：
1. 将本地脚本和数据同步到 `$RESMAX_SSH_REMOTE_DIR`
2. 所有远程命令使用以下模板（从配置展开，不要硬编码）：

```bash
ssh $RESMAX_SSH_HOST \
  "source $RESMAX_SSH_CONDA_INIT && conda activate $RESMAX_SSH_CONDA_ENV && \
   cd $RESMAX_SSH_REMOTE_DIR && HF_HUB_OFFLINE=1 <command>"
```

**conda 初始化路径**：默认 `~/miniconda3/etc/profile.d/conda.sh`。若服务器
装的是 miniforge3，把 `RESMAX_SSH_CONDA_INIT` 改成
`~/miniforge3/etc/profile.d/conda.sh` 即可，无须改动任何代码。

**HF_HUB_OFFLINE=1**：embedding 模型已预缓存在服务器上，所有命令必须设置此环境变量，禁止联网访问 HuggingFace Hub。

## 核心能力

### 1. 缓存构建（build_cache_multigpu.py）

在 GPU 服务器上构建/增量更新 embedding 缓存。多 GPU 并行编码，INT8 量化加载模型。

**增量与维度校验逻辑**（脚本内置，无需 agent 干预）：
- 如果输出路径已有缓存，脚本自动加载并对比 paper_ids，仅编码新增论文，合并后保存
- 如果指定了 `--dim` 且与已有缓存维度不一致，自动全量重建
- 如果缓存已包含所有论文，输出 `cache is up-to-date` 并跳过

**前置检查（硬性）**：

1. SSH 连接服务器，确认能正常连通
2. 运行 `nvidia-smi` 查看各 GPU 的显存占用和进程情况
3. 选择空闲 GPU（显存占用 < 10%），通过 `--gpus` 参数指定

```bash
# Load server params from .localconfig/server.env (agent may also do this
# programmatically via secrets_loader; the shell variant is shown for
# manual debugging).
source .localconfig/server.env

ssh "$RESMAX_SSH_HOST" nvidia-smi

# 同步脚本和数据
rsync -avz $SKILL_ROOT/scripts/ "$RESMAX_SSH_HOST:$RESMAX_SSH_REMOTE_DIR/scripts/"
rsync -avz $SKILL_ROOT/config/  "$RESMAX_SSH_HOST:$RESMAX_SSH_REMOTE_DIR/config/"
rsync -avz paper_database/accepted_index.csv "$RESMAX_SSH_HOST:$RESMAX_SSH_REMOTE_DIR/accepted_index.csv"

# 构建缓存
ssh "$RESMAX_SSH_HOST" "source $RESMAX_SSH_CONDA_INIT && conda activate $RESMAX_SSH_CONDA_ENV && \
  cd $RESMAX_SSH_REMOTE_DIR && HF_HUB_OFFLINE=1 python3 scripts/build_cache_multigpu.py \
  --accepted accepted_index.csv \
  --out .embedding_cache/qwen3_8b.npz \
  --gpus 0,1,2,3"

# 同步缓存回本地
rsync -avz "$RESMAX_SSH_HOST:$RESMAX_SSH_REMOTE_DIR/.embedding_cache/qwen3_8b.npz" paper_database/embedding_cache/qwen3_8b.npz
```

| 参数 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `--accepted` | 是 | accepted_index.csv 路径 | — |
| `--out` | 否 | 输出 .npz 路径 | `paper_database/embedding_cache/qwen3_8b.npz` |
| `--model` | 否 | embedding 模型名 | `Qwen/Qwen3-Embedding-8B` |
| `--batch-size` | 否 | 批大小 | `32` |
| `--max-length` | 否 | 最大 token 长度 | `8192` |
| `--dim` | 否 | 截断维度（0=全维度） | `0`（全维度，不截断） |
| `--gpus` | 否 | 逗号分隔的 GPU ID（必须选择空闲 GPU） | `0,1,2,3` |
| `--instruction` | 否 | query 指令前缀 | 空 |

**输出日志示例**：

增量模式（有新增论文）：
```
[main] 59844 papers loaded
[main] existing cache: 50000 papers, dim=4096
[main] incremental: 9844 new papers to encode, 50000 cached
[main] all GPUs done in 120.0s
[main] merged: 50000 existing + 9844 new = 59844 total
[main] saved: .embedding_cache/qwen3_8b.npz (437.7 MB), shape: (59844, 4096)
```

维度不匹配（自动全量重建）：
```
[main] 59844 papers loaded
[main] dimension mismatch: cache=1024, target=4096. Full rebuild.
[main] all GPUs done in 618.0s
[main] saved: .embedding_cache/qwen3_8b.npz (437.7 MB), shape: (59844, 4096)
```

缓存已是最新：
```
[main] 59844 papers loaded
[main] existing cache: 59844 papers, dim=4096
[main] cache is up-to-date, nothing to encode.
```

**增量 / 校验 / 差异** 由 `build_cache_multigpu.py` 自己做（见上方增量逻辑说明），以及 `resmax-database/scripts/validate_database.py` 的 `embedding` 节（paper_id 重叠率、维度、NaN 等）。本 skill 不再暴露独立的 `embedding_cache.py` 库 API。

### 2. 查询编码（encode_query.py）

将单条查询文本编码为 embedding 向量，输出 JSON 到 stdout。设计为在 GPU 服务器上运行，`resmax-survey` 通过 SSH 远程调用。

```bash
source .localconfig/server.env
ssh "$RESMAX_SSH_HOST" "source $RESMAX_SSH_CONDA_INIT && conda activate $RESMAX_SSH_CONDA_ENV && \
  HF_HUB_OFFLINE=1 python3 $RESMAX_SSH_REMOTE_SCRIPT --query 'your research topic'"
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--query` | 是（或 positional） | 查询文本。可通过 `--query <text>` 或第一个 positional 参数提供 |
| `--model` | 否 | 模型名（默认 `Qwen/Qwen3-Embedding-8B`） |
| `--device` | 否 | 设备（默认 `auto`，按 nvidia-smi 选择空闲 GPU） |
| `--dim` | 否 | 截断维度（默认 0，全维度） |

## 输出

| 文件 | 说明 |
|------|------|
| `paper_database/embedding_cache/qwen3_8b.npz` | Embedding 缓存（keys: `embeddings`, `paper_ids`, `meta`） |

## .npz 缓存格式

| Key | 类型 | 说明 |
|-----|------|------|
| `embeddings` | float32 ndarray `[N, D]` | 论文 embedding 矩阵 |
| `paper_ids` | str ndarray `[N]` | 对应的 paper_id 列表 |
| `meta` | JSON str | 模型名、维度、构建时间等元信息 |

## 配置文件

### config/default_config.json

```json
{
  "embedding": {
    "model_name": "Qwen/Qwen3-Embedding-8B",
    "dimension": 0,
    "batch_size": 64,
    "instruction_prefix": "Instruct: Retrieve academic papers relevant to the given research topic\nQuery: ",
    "cache_dir": "paper_database/embedding_cache",
    "cache_filename": "qwen3_8b.npz"
  }
}
```
