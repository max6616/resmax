---
name: resmax-embedding
description: 在 GPU 服务器上为 accepted_index.csv 构建或刷新论文 embedding 缓存，供 resmax-survey 的语义检索使用。
---

# resmax-embedding

## 何时使用

用于构建或刷新 `paper_database/embedding_cache/qwen3_8b.npz`。上游是 `resmax-database`，下游是 `resmax-survey`。

## 前置条件

- `paper_database/accepted_index.csv` 已由 `resmax-database` 规范化。
- `.localconfig/server.env` 配置了 `RESMAX_SSH_HOST` 等远程 GPU 参数。
- 生产前先确认 GPU 空闲，不盲目启动长任务。

## 最小流程

```bash
SKILL_ROOT=.agents/skills/resmax-embedding
source .localconfig/server.env

ssh "$RESMAX_SSH_HOST" nvidia-smi

rsync -avz $SKILL_ROOT/scripts/ "$RESMAX_SSH_HOST:$RESMAX_SSH_REMOTE_DIR/scripts/"
rsync -avz paper_database/accepted_index.csv "$RESMAX_SSH_HOST:$RESMAX_SSH_REMOTE_DIR/accepted_index.csv"

ssh "$RESMAX_SSH_HOST" "source $RESMAX_SSH_CONDA_INIT && conda activate $RESMAX_SSH_CONDA_ENV && \
  cd $RESMAX_SSH_REMOTE_DIR && HF_HUB_OFFLINE=1 python3 scripts/build_cache_multigpu.py \
  --accepted accepted_index.csv \
  --out .embedding_cache/qwen3_8b.npz \
  --gpus 0,1,2,3"

rsync -avz "$RESMAX_SSH_HOST:$RESMAX_SSH_REMOTE_DIR/.embedding_cache/qwen3_8b.npz" \
  paper_database/embedding_cache/qwen3_8b.npz

python3 .agents/skills/resmax-database/scripts/normalize_database.py \
  --csv paper_database/accepted_index.csv \
  --manifest paper_database/manifest.json

python3 .agents/skills/resmax-database/scripts/validate_database.py \
  --csv paper_database/accepted_index.csv \
  --cache paper_database/embedding_cache/qwen3_8b.npz \
  --manifest paper_database/manifest.json
```

## 缓存契约

`.npz` 必须包含：

- `embeddings`: float32 `[N, D]`
- `paper_ids`: safe string dtype，不允许 object dtype / pickle-only
- `meta`: JSON 字符串，至少包含 `model_name`、`dimension`、`count`、`accepted_csv_sha256`

默认目标是覆盖所有 queryable rows：`paper_id` 非空且摘要不是空值/占位符。旧缓存如果需要 `allow_pickle=True` 读取，应视为需要重建。

## 参考资料

- 旧完整手册：`references/legacy_full_manual.md`
- 远程配置说明：仓库根目录 `SECRETS.md` 和 `.localconfig/README.md`
