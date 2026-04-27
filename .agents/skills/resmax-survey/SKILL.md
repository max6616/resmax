---
name: resmax-survey
description: 从 resmax 基础文献库检索指定研究方向的相关论文，生成方向级 research_index、评分结果、开源深查提示和文献列表。
---

# resmax-survey

## Interaction Policy

Production/default execution is interactive. The agent must stop at Human Gates and ask the user before changing the research route, evidence strength, review cost, experiment cost, or long-term memory. Non-interactive full pipeline execution is allowed only when the user explicitly says test/dev/debug/smoke, and the command still needs the matching opt-in flag such as `--allow-auto-select` or `--allow-abstract-fallback`.

Before Phase 2 production work, ask for G0 constraints: research goal, target venue, time/compute/team budget, and non-goals. If they are missing, stop and clarify instead of optimizing ROI against an implicit target.

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

python3 .agents/skills/resmax-database/scripts/ensure_reviews_available.py \
  --csv paper_database/accepted_index.csv \
  --reviews-dir paper_database/reviews \
  --package-dir paper_database/hf_export/reviews

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

## V2 开发说明

- 后续 macro survey / evidence-first 流程应优先通过 `.agents/skills/_shared/resmax_core/corpus_api.py` 读取 `accepted_index.csv`、review JSON、source text status 和 embedding cache metadata。
- `corpus_api.py` 是只读 data plane：不提供 write/update/delete，也不把 keyword hit、citation count 或 embedding similarity 当作 ROI。
- 开发和 eval smoke 优先使用 `.agents/skills/resmax-survey/eval/run_baseline.py` 与 fixture spec；生产 survey 仍必须先满足数据库 validator 门槛。
- Phase 2 macro survey 入口为：

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 compile-spec \
  --intent "研究意图" \
  --out-dir literature_research/<direction_slug>

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

V2 macro 输出只允许作为 broad candidate set、subdirection map 和 low-confidence rough ROI；不得在 Phase 2 产出 final idea、strong recommendation 或 experiment plan。

生产 Phase 2 不能静默退化为 keyword-only：hybrid/semantic query 必须写入 `survey_v2/macro/query_embedding_trace.jsonl`，并在 `manifest.json` 记录 provider、维度、成功/失败数量。长执行命令必须持续打印阶段性进度，包括 corpus/embedding metadata 加载、query embedding 编码、逐 query 检索、candidate 聚合和 subdirection 聚类。

## V2 Phase 3 ResearchPack

Phase 3 入口在同一个 `resmax_survey_v2` package 下，不新增 skill 或平台层。它只消费 Phase 2 的 macro pack，对选定子方向的 top candidates 做 targeted evidence extraction：

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 build-pack \
  --macro-dir literature_research/<direction_slug> \
  --subdirection-id <chosen_subdirection_id> \
  --out-dir /tmp/resmax_research_pack

python3 .agents/skills/_shared/resmax_core/validators/validate_research_pack.py \
  --pack /tmp/resmax_research_pack/research_pack
```

可拆开的子命令为 `select-subdirection`、`extract-evidence`、`compile-tension`、`build-pack`、`validate-pack`。

生产路径必须停在 G1，让用户从 `survey_v2/macro/subdirection_map.json` 或 `survey_v2/macro/subdirection_roi_table.csv` 选择 `subdirection_id`。`build-pack` 和 `select-subdirection` 没有 `--subdirection-id` 时会失败；自动选择 top rough ROI 只允许显式传 `--allow-auto-select`，并且只应用于用户已声明的 test/dev/debug/smoke 路径。

生产路径必须先对 selected candidates 执行 targeted source materialization。`build-pack` 默认会在 `select-subdirection` 之后运行该步骤；手动拆阶段时使用：

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 select-subdirection \
  --macro-dir literature_research/<direction_slug> \
  --subdirection-id <chosen_subdirection_id> \
  --out-dir literature_research/<direction_slug>

PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 materialize-sources \
  --macro-dir literature_research/<direction_slug> \
  --out-dir literature_research/<direction_slug>
```

该步骤只处理 selected subdirection 的候选论文。生产默认把可复用论文资产写入全局 cache `paper_database/source_cache/<safe_paper_id>/`，包括 `paper.pdf`、`paper.pdftxt`、`paper.tex`、`paper.md` 或 `manual.md`；单次调研目录只保存 ResearchPack 引用、manifest hash 和 materialization report。后续方向检索到同一论文时必须优先复用全局 cache，再尝试官方/OA/arXiv/OpenReview/DOI/PDF/title-only search 补全。临时 fixture 或 repo 外 smoke 可以继续使用该调研目录下的 `survey_v2/paper_sources/`，避免污染生产 cache。

Sci-Hub 默认关闭；不得对全库做 full-text 解析。若无法 materialize readable source，必须写入 `source_materialization_report.json` 和 missing reports，并停在 G2 让用户选择补 source、允许 MinerU/manual cache、允许 Sci-Hub、改方向或显式继续 degraded evidence。`abstract_fallback` 只有显式 `--allow-abstract-fallback` 或明确对话批准后才能继续，且只能作为 weak/degraded evidence，不可支撑 strong claim 或替代 full-text gate。生产 ResearchPack validator 要求 selected candidates 的 readable source coverage 至少 95%，且不能出现“全部 evidence 都来自 abstract fallback”的通过状态。

Phase 3 输出目录为 `research_pack/`，事实源是 JSON/JSONL 和 manifest hash；`coverage_report.md` 与 `field_map.md` 只是可读视图。生产默认不自动选择子方向，必须显式传 `--subdirection-id`。test/dev/debug/smoke 可显式传 `--mode smoke --allow-auto-select` 让命令选择 top rough ROI 子方向并标记 `auto_selected=true`。候选数遵循 `ResearchSpec.budget_policy.max_targeted_evidence_candidates`，默认不超过 30。

边界：

- 只处理 selected subdirection top candidates，不做全库 full-text 解析。
- 生产执行必须先尝试 materialize selected candidates 的 `paper_database/source_cache/<safe_paper_id>/paper.tex`、`paper.pdftxt`、`paper.md` 或 `manual.md` 缓存；Sci-Hub 默认关闭，MinerU 只消费已有 markdown cache。
- 缺失 source/PDF 写入 `missing_source_report.json` 和 `missing_pdf_report.json`，不得静默跳过。
- `EvidenceCard` 必须引用 `EvidenceSpan`；`GapMap` 必须引用 claim/evidence，或显式使用 `missing_evidence`。
- 本阶段只生成 `EvidenceSpan`、`EvidenceCard`、`ClaimGraph`、`GapMap` 和 pack manifest，不生成 idea、final recommendation 或 experiment plan。

## V2 Phase 4 Reviewer-Pressure ROI

Phase 4 仍在同一个 `resmax_survey_v2` package 和既有 `research_pack/` contract 内演进，不新增 `resmax-review` 或新的 skill。它消费 Phase 3 pack、review cache 和 metadata，输出 reviewer pressure notes、paper roles、role-aware matrices、ROI lens、risk register 和 Phase 5 idea seed constraints：

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 build-roi-lens \
  --pack literature_research/<direction_slug>/research_pack \
  --accepted paper_database/accepted_index.csv \
  --reviews paper_database/reviews \
  --out /tmp/resmax_roi_pack

python3 .agents/skills/_shared/resmax_core/validators/validate_research_pack.py \
  --pack /tmp/resmax_roi_pack/research_pack
```

可拆开的子命令为 `extract-reviewer-pressure`、`assign-paper-roles`、`build-roi-lens`、`validate-roi-pack`。

Phase 4 输出包括：

- `reviewer_pressure_notes.jsonl`
- `paper_roles.json`
- `baseline_matrix.csv`
- `benchmark_matrix.csv`
- `implementation_matrix.csv`
- `gap_roi_table.csv`
- `roi_lens.json`
- `risk_register.md`
- `idea_seed_constraints.md`

边界：

- reviewer pressure 优先来自真实 `paper_database/reviews` cache；任何推断项必须显式标记 `inferred`。
- reviewer objection 只进入 gap/ROI lens 和 seed constraints，不直接生成 idea。
- ROI 保留 positive dimensions、difficulty dimensions、unknowns、reviewer blockers 和 confidence；不得让单一 ROI 总分统治排序。
- `unknown` 不当作 0 分；必须降低 confidence 或生成 follow-up retrieval target。
- Phase 4 后停在 G3，让用户审核高优先 gap 的 unknown 和 reviewer blockers 是否可接受；未确认前不得把 unknown 当作可继续的低成本风险。
- `risk_register.md` 和 `idea_seed_constraints.md` 是展示/交接层；`roi_lens.json`、`reviewer_pressure_notes.jsonl`、`paper_roles.json` 和 manifest hash 是事实源。

## Agent 阶段输出

- `scores_raw.json`：Stage 5 subagent 原始评分。
- `deepcheck_reviews.json` / `deepcheck_results.md`：Stage 5.5 开源质量深查。
- `paper_database/source_cache/<safe_paper_id>/`：生产可复用 TeX/PDF text/MinerU MD/manual source cache。
- `survey_v2/paper_sources/<paper_id>/`：仅作为旧调研目录或 fixture 兼容 fallback。

## 失败处理

- validator FAIL：回到 `resmax-database` 或 `resmax-embedding`，不要绕过生产门槛。
- review JSON 缺失：先运行 `resmax-database/scripts/ensure_reviews_available.py`；它会优先使用本地解压目录，其次从本地 HF package 还原，再尝试按 `RESMAX_HF_DATASET_REPO` / `--hf-repo-id` 从 Hugging Face 下载 package。下载、校验或解压失败时停止生产流程并显式报告，不得静默忽略 review。
- embedding 缺失：生产停止；开发 smoke 可继续关键词路径并在日志标明 degraded。
- PDF 缺失：优先检查 `pdf_status`、`pdf_source` 和 `deepcheck_missing_pdf.json`，不要默认使用灰色来源。

## 参考资料

- 旧完整手册：`references/legacy_full_manual.md`
- 评分 prompt/JSON 细节：`scripts/search_literature_lib/subagent_scorer.py`
- Stage 5.5 细节：`scripts/stage5_5_deepcheck.py --help`
