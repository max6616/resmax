---
name: resmax-survey
description: 从 resmax 基础文献库检索指定研究方向的相关论文，生成方向级 research_index、评分结果、开源深查提示和文献列表。
---

# resmax-survey

## 何时使用

用于“检索文献 / 文献调研 / 找相关论文 / literature search”。输入是研究方向和关键词，生产输出默认在 `literature_research/<direction_slug>/`；开发 smoke / clean-room 验证优先写 `/tmp`，避免把测试产物混入项目目录。

## 前置条件

- `paper_database/accepted_index.csv` 存在。
- 生产执行必须先跑 `resmax-database/scripts/validate_database.py`，且 `overall=PASS`。
- 检索/深查读取 `source_text_status` 和 `source_text_url`；`pdf_url` 只表示直链 PDF，不代表唯一原文锚点。
- 开发 smoke 可以显式使用缺失 embedding cache 走关键词降级路径，但不能把该结果当生产验收。

## 最小流程

```bash
SKILL_ROOT=.agents/skills/resmax-survey

python3 .agents/skills/resmax-database/scripts/validate_database.py \
  --csv paper_database/accepted_index.csv \
  --cache paper_database/embedding_cache/qwen3_8b.npz \
  --manifest paper_database/manifest.json

python3 $SKILL_ROOT/scripts/search_literature.py \
  --accepted paper_database/accepted_index.csv \
  --direction "研究方向描述" \
  --keywords "关键词1,关键词2,关键词3" \
  --out-dir literature_research/<direction_slug>
```

`search_literature.py` 执行 Stage 1-4：关键词/embedding 双路召回、去重、元信息补充、轻量开源 passthrough、未评分文档和 `research_index.csv`。

开发 smoke 的完整降级命令：

```bash
python3 $SKILL_ROOT/scripts/search_literature.py \
  --accepted paper_database/accepted_index.csv \
  --direction smoke_test_scene_graph \
  --keywords scene,graph \
  --out-dir /tmp/resmax_survey_smoke \
  --cache-path /tmp/resmax_missing_embedding_cache_DO_NOT_CREATE.npz \
  --keyword-top-k 3 \
  --embedding-top-k 3 \
  --max-candidates 3
```

该命令必须在日志中标记 `Degraded mode`，但不能出现 `## Errors`；生产运行不得使用缺失 cache 降级。

## Agent 阶段

- Stage 5 评分必须委派给 subagent/orchestrator，主 agent 不逐篇长 context 评分。
- 评分结果写入 `scores_raw.json` 后，用 `subagent_scorer.apply_scores()` 统一回写，不手工改 CSV。
- Stage 5.5 深查使用：

```bash
python3 $SKILL_ROOT/scripts/stage5_5_deepcheck.py \
  --dir literature_research/<direction_slug> \
  --accepted paper_database/accepted_index.csv \
  --grades S
```

Sci-Hub 灰色 fallback 默认关闭；只有用户显式要求时才传 `--enable-sci-hub`。

## Stage 1-4 输出

- `research_index.csv`：方向级候选、评分和 deepcheck 字段。
- `literature_list.md`：未评分或已评分文献列表。
- `filter_log.md` / `filter_log_state.json`：可读日志和可恢复状态。
- `deepcheck_prompts.json`：后续 repo-review/deepcheck 的 subagent prompt。

## Agent 阶段输出

- `scores_raw.json`：Stage 5 subagent 原始评分。
- `deepcheck_reviews.json` / `deepcheck_results.md`：Stage 5.5 开源质量深查。
- `paper_sources/<paper_id>/`：TeX/PDF text/MinerU MD 缓存。

## 失败处理

- validator FAIL：回到 `resmax-database` 或 `resmax-embedding`，不要绕过生产门槛。
- embedding 缺失：生产停止；开发 smoke 可继续关键词路径并在日志标明 degraded。
- PDF 缺失：优先检查 `pdf_status`、`pdf_source` 和 `deepcheck_missing_pdf.json`，不要默认使用灰色来源。

## 参考资料

- 旧完整手册：`references/legacy_full_manual.md`
- 评分 prompt/JSON 细节：`scripts/search_literature_lib/subagent_scorer.py`
- Stage 5.5 细节：`scripts/stage5_5_deepcheck.py --help`
