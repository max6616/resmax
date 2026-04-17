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
SKILL_ROOT=.cursor/skills/resmax-embedding
```

## 触发词

"build cache", "build embedding", "更新embedding", "构建缓存", "增量更新缓存"

## 主 agent 行为约束

1. **禁止主 agent 读取 `$SKILL_ROOT/scripts/` 下的任何源码**。脚本是黑盒工具，本文档是其 API 文档。
2. **前置检查是硬性要求**：每次构建前必须先确认 GPU 可用性，禁止盲目启动。

## 核心能力

### 1. 缓存构建（build_cache_multigpu.py）

在 GPU 服务器上构建/增量更新 embedding 缓存。多 GPU 并行编码，INT8 量化加载模型。

**前置检查（硬性）**：

1. SSH 连接服务器，确认能正常连通
2. 运行 `nvidia-smi` 查看各 GPU 的显存占用和进程情况
3. 选择空闲 GPU（显存占用 < 10%），通过 `--gpus` 参数指定，避开有高占用的 GPU 以免影响其他用户

```bash
ssh <server> nvidia-smi

python3 $SKILL_ROOT/scripts/build_cache_multigpu.py \
  --accepted paper_database/accepted_index.csv \
  --out paper_database/embedding_cache/qwen3_8b.npz \
  --gpus 0,1
```

| 参数 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `--accepted` | 是 | accepted_index.csv 路径 | — |
| `--out` | 否 | 输出 .npz 路径 | `paper_database/embedding_cache/qwen3_8b.npz` |
| `--model` | 否 | embedding 模型名 | `Qwen/Qwen3-Embedding-8B` |
| `--batch-size` | 否 | 批大小 | `64` |
| `--max-length` | 否 | 最大 token 长度 | — |
| `--dim` | 否 | 截断维度（0=全维度） | `0`（全维度，不截断） |
| `--gpus` | 否 | 逗号分隔的 GPU ID（必须选择空闲 GPU） | 自动检测 |
| `--instruction` | 否 | query 指令前缀 | 见 config |

### 2. 增量更新与校验（embedding_cache.py）

提供缓存的增量更新和完整性校验功能，可作为库导入使用。

主要函数：
- `incremental_update(csv_path, cache_path)` — 对比 CSV 与缓存，仅编码新增论文并合并
- `verify_cache(cache_path)` — 校验缓存完整性（NaN/Inf/范数/重复检测）
- `diff_cache_vs_index(csv_path, cache_path)` — 返回缓存与索引的差异统计

### 3. 查询编码（encode_query.py）

将单条查询文本编码为 embedding 向量，输出 JSON 到 stdout。设计为在 GPU 服务器上运行，resmax-survey 通过 SSH 远程调用。

```bash
python3 $SKILL_ROOT/scripts/encode_query.py --query "your research topic"
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--query` | 是 | 查询文本 |
| `--model` | 否 | 模型名（默认 `Qwen/Qwen3-Embedding-8B`） |
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
