---
name: resmax-survey
description: 从 resmax 基础文献库构建方向级 survey 与 ResearchPack，包括宏观候选检索、子方向选择、证据抽取和 reviewer-pressure ROI lens。
---

# resmax-survey

## 使用边界

用于文献调研、方向筛选和 ResearchPack 构建。生产输出默认写入 `literature_research/<direction_slug>/`；smoke / clean-room 验证优先写 `/tmp`。

生产执行默认交互式：研究约束、子方向选择、source 降级、ROI unknown / reviewer blocker 都必须先问用户。只有用户明确说 test/dev/debug/smoke，才允许配合 opt-in flag 自动跑完整流程。

本 skill 只产出 survey、evidence、gap/ROI artifacts；不生成 idea、final recommendation 或 experiment plan。

## 前置检查

- `paper_database/accepted_index.csv` 存在。
- 生产执行前数据库 validator 必须 `overall=PASS`。
- 生产检索需要可用 embedding cache；缺失 cache 只允许 smoke 降级。
- ROI lens 需要真实 review cache；缺失时先恢复 reviews。
- `.agents/skills/_shared/resmax_core/corpus_api.py` 是只读 data plane，不写回数据库。

```bash
python3 .agents/skills/resmax-database/scripts/ensure_reviews_available.py \
  --csv paper_database/accepted_index.csv \
  --reviews-dir paper_database/reviews \
  --package-dir paper_database/hf_export/reviews

python3 .agents/skills/resmax-database/scripts/validate_database.py \
  --csv paper_database/accepted_index.csv \
  --cache paper_database/embedding_cache/qwen3_8b.npz \
  --manifest paper_database/manifest.json
```

## 线性流程

先收集 `research goal / target venue / time-compute-team budget / non-goals`。缺失时停止确认，不要用隐含目标做 ROI 优化。

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 compile-spec \
  --intent "研究意图" \
  --out-dir literature_research/<direction_slug>
```

`compile-spec` 只写 spec 阶段产物：`survey_v2/spec/research_spec.json`、`source_policy.json`、`query_planner_request.json` 和 `query_planner_prompt.md`；不得自动生成 `query_families.jsonl`。执行 skill 的主 agent 必须读取 `query_planner_prompt.md`，调用一个 subagent 只生成 query plan，不允许 subagent 检索。subagent 输出必须保存为 `survey_v2/spec/query_planner_agent_output.json`，再用校验命令包装成最终 `query_families.jsonl`；校验失败必须停止，不得回退到规则 query 或旧 anchor 逻辑。

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 plan-queries \
  --spec literature_research/<direction_slug>/survey_v2/spec/research_spec.json \
  --agent-output literature_research/<direction_slug>/survey_v2/spec/query_planner_agent_output.json \
  --out literature_research/<direction_slug>/survey_v2/spec/query_families.jsonl

PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 retrieve-macro \
  --spec literature_research/<direction_slug>/survey_v2/spec/research_spec.json \
  --accepted paper_database/accepted_index.csv \
  --embedding-cache paper_database/embedding_cache/qwen3_8b.npz \
  --embedding-provider ssh \
  --require-embedding \
  --out-dir literature_research/<direction_slug>

PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 validate \
  --dir literature_research/<direction_slug>
```

让用户从 `survey_v2/macro/subdirection_map.json` 或 `survey_v2/macro/subdirection_roi_table.csv` 选择 `subdirection_id`。生产默认不自动选择；自动选择只允许 test/dev/debug/smoke 并显式传 `--allow-auto-select`。

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 build-pack \
  --macro-dir literature_research/<direction_slug> \
  --subdirection-id <chosen_subdirection_id> \
  --out-dir literature_research/<direction_slug>

PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 build-roi-lens \
  --pack literature_research/<direction_slug>/research_pack \
  --accepted paper_database/accepted_index.csv \
  --reviews paper_database/reviews \
  --out literature_research/<direction_slug>

python3 .agents/skills/_shared/resmax_core/validators/validate_research_pack.py \
  --pack literature_research/<direction_slug>/research_pack
```

ROI lens 完成后，让用户审核 high-priority gaps 的 unknown、reviewer blockers 和 follow-up retrieval targets；未确认前不要交给 idea 生成。

## 可拆命令

需要手动拆开 source 准备时：

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 select-subdirection \
  --macro-dir literature_research/<direction_slug> \
  --subdirection-id <chosen_subdirection_id> \
  --out-dir literature_research/<direction_slug>

PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 materialize-sources \
  --macro-dir literature_research/<direction_slug> \
  --out-dir literature_research/<direction_slug>
```

其他子命令只在需要定位问题时使用：`plan-queries`、`extract-evidence`、`compile-tension`、`extract-reviewer-pressure`、`assign-paper-roles`、`validate-pack`、`validate-roi-pack`。

## 核心产物

- `survey_v2/spec/`: `research_spec.json`, `source_policy.json`
- `survey_v2/macro/`: query families, retrieval trace, candidates, subdirection map/table, macro report, manifest
- `research_pack/`: manifest, evidence spans/cards, claim graph, gap map, reviewer pressure notes, paper roles, ROI lens, risk register, seed constraints, missing/source reports

Markdown files are display-only. JSON/JSONL/CSV plus manifest hashes are the downstream contract.

## 硬规则

- 只处理 selected subdirection 的 top candidates；不要对全库做 full-text 解析。
- 生产 source cache 写入 `paper_database/source_cache/<safe_paper_id>/`；单次调研目录只保存引用、manifest hash 和 reports。
- Source 解析先复用全局 cache，再尝试官方/OA/arXiv/OpenReview/DOI/PDF/title-only search。若生产 `build-pack` 在 G2 source gate 失败，必须读取 `source_materialization_report.json` 中的 `web_search_replenishment`，对每篇缺失 source 执行合法通用 web search（搜索引擎/浏览器检索官方项目页、publisher open PDF、arXiv/OpenReview、作者主页、机构库、GitHub release 等公开来源），并把可用全文补入全局 source cache。补入 cache 后用下列命令记录公开来源 provenance，再重跑 `build-pack`；只有通用 web search 也无法获得 readable source 时，才停下询问用户是否切换子方向、提供 manual/MinerU cache、显式批准 Sci-Hub，或显式允许 abstract fallback。

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 record-source-replenishment \
  --pack literature_research/<direction_slug>/research_pack \
  --paper-id <paper_id> \
  --source-url <legal_public_source_url>
```
- Sci-Hub 默认关闭；只有用户显式批准才可启用。
- 无法 materialize readable source 时，必须写 missing/source reports 和 web search 补源记录；生产运行不得把 OA/title-only resolver 失败等同于已完成通用 web search。
- `abstract_fallback` 只有显式批准后才能继续，且只能作为 weak/degraded evidence。
- 生产 ResearchPack 要求 selected candidates readable source coverage 至少 95%，且不能全部来自 abstract fallback。
- `EvidenceCard` 必须引用 `EvidenceSpan`；`GapMap` 必须引用 claim/evidence，或显式使用 `missing_evidence`。
- reviewer pressure 优先来自真实 review cache；推断项必须标记 `inferred`。
- reviewer objection 只进入 gap/ROI lens 和 seed constraints，不直接生成 idea。
- ROI 保留多维向量、unknowns、blockers 和 confidence；不得用单一总分排序。
- `unknown` 不当作 0 分；必须降低 confidence 或生成 follow-up retrieval target。

## 旧 literature-list 路径

仅在需要旧 `research_index.csv` / `literature_list.md` 工作流时使用：

```bash
SKILL_ROOT=.agents/skills/resmax-survey

python3 $SKILL_ROOT/scripts/search_literature.py \
  --accepted paper_database/accepted_index.csv \
  --direction "研究方向描述" \
  --keywords "关键词1,关键词2,关键词3" \
  --out-dir literature_research/<direction_slug>

python3 $SKILL_ROOT/scripts/stage5_5_deepcheck.py \
  --dir literature_research/<direction_slug> \
  --accepted paper_database/accepted_index.csv \
  --grades S
```

旧路径的评分结果写入 `scores_raw.json` 后，用 `subagent_scorer.apply_scores()` 回写，不手工改 CSV。Sci-Hub fallback 同样默认关闭。

Smoke 降级命令：

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

日志必须标记 `Degraded mode`，且不能出现 `## Errors`；生产运行不得使用缺失 cache 降级。

## 失败处理

- validator FAIL：回到 `resmax-database` 或 `resmax-embedding`，不要绕过生产门槛。
- review JSON 缺失：先运行 `ensure_reviews_available.py`；下载、校验或解压失败时停止。
- embedding 缺失：生产停止；smoke 可继续关键词路径并标记 degraded。
- PDF 缺失：优先检查 `pdf_status`、`pdf_source` 和 missing PDF report，不要默认使用灰色来源。

## 参考

- 旧完整手册：`references/legacy_full_manual.md`
- 评分 prompt/JSON 细节：`scripts/search_literature_lib/subagent_scorer.py`
- 开源 deepcheck 细节：`scripts/stage5_5_deepcheck.py --help`
