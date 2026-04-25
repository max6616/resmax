# Resmax 科研 Agent Skill 体系规划

更新日期：2026-04-25

本文分三层：

1. **项目总览**：给执行中的 agent 反复回看，防止长任务偏离主线。
2. **Skill 编写计划**：基于当前 Resmax 代码边界和可迁移实践，拆成可实现、可验收的 skill backlog。
3. **机制吸收与 Resmax 原生设计**：参考 `RESMAX_RESEARCH_AGENT_MECHANISM_SURVEY.md`，只保留值得借鉴的机制，并进一步设计更贴合 Resmax 的方案。

---

# 第一部分：项目总览

## 1. 北极星

Resmax 的目标不是生成更长的论文列表，也不是追求一键自动写论文。

核心目标：

> 在纯净 AI 顶会/顶刊文献库和可追溯证据链基础上，识别投入产出比最高的研究方向，并把方向落到可执行、可投稿、可复现的研究计划。

短期产品形态：

```text
evidence state machine
  -> gap / contradiction mining
  -> evidence-backed ROI ranking
  -> idea tournament
  -> claim-driven experiment planning
```

明确不追求：

```text
one command -> final paper
```

原因：

- AI 顶会研究的瓶颈不是写作，而是方向选择、idea 质量、实验性价比和 reviewer risk。
- 开放 CV/graphics/LLM 方向通常无法像 toy ML benchmark 一样用单一指标闭环。
- 如果没有强 evidence chain 和 harness engineering，全自动 pipeline 只会更快地产生不可验证结论。

## 2. ROI 不是一个黑箱分数

ROI 是系统设计约束，不是先验精确数学公式。

一个方向值得投入，必须能解释：

```text
positive signals:
  publication_upside
  novelty_headroom
  evidence_confidence
  benchmark_leverage
  implementation_reuse
  story_clarity
  information_gap

difficulty signals:
  sota_pressure
  baseline_burden
  compute_cost
  data_friction
  engineering_risk
  timeline_risk
  review_risk
```

执行约束：

- 不把优势信号和难度信号混成一个无法解释的总分。
- `unknown` 不等于 0 分；`unknown` 表示证据缺失，应该触发补证据或降低置信度。
- 任何强推荐都必须能给出证据链、竞品/基线、实验代价、SOTA 压力和失败风险。
- 最终 idea 必须落到 dataset、benchmark、baseline、metric、ablation、visualization 和投稿叙事。

## 3. 当前项目事实

当前 `paper_database/accepted_index.csv` 覆盖：

```text
rows: 68,951
abstract_raw: 100.00%
source_text_url: 100.00%
pdf_url: 82.34%
recent rows:
  2024: 26,429
  2025: 31,172
  2026: 11,350
```

`source_text_status` 分布：

```text
pdf_available: 56,777
publisher_landing_only: 7,453
official_landing_only: 4,621
source_listing_only: 100
```

结论：

- 标题/摘要级 embedding 足够支撑粗召回和早期聚类。
- 仅靠标题/摘要不能可靠判断 method transfer、benchmark opportunity、baseline burden、compute cost、SOTA pressure。
- Full-text 建设必须按 ROI 分层推进，先做方向相关候选，不做盲目全库解析。

## 4. 总体架构

```text
resmax-database
  accepted_index.csv
  reviews/
  source_text contract
  future: fulltext / section / evidence span layer
        |
        v
resmax-embedding
  paper-level embedding cache
  future: section-level embedding cache
        |
        v
resmax-survey
  broad retrieval
  subdirection map
  focused evidence extraction
  EvidenceCard
  ClaimGraph
  GapMap
  research_pack/
        |
        v
resmax-idea
  gap-driven idea generation
  cross-model critique
  tournament / evolution
  claim-driven experiment plan

harness engineering principles apply across all layers:
  repository knowledge as system of record
  progressive context delivery
  tool/action-space design
  schema validators and mechanical checks
  eval feedback sensors
  state recovery and activity logs
  human approval gates
  cross-model review loops
```

这里的 harness engineering 是一种设计理念，不是一个单独 skill、目录或 benchmark。它要求每个 skill、schema、脚本和产物都考虑：agent 如何拿到正确上下文、如何被约束动作空间、如何由机械检查兜底、如何从失败中恢复，以及如何把人类判断转成可复用反馈。

## 5. Skill 边界

### `resmax-database`

职责：

- 维护纯净 AI 领域高质量文献库。
- 维护 authoritative metadata。
- 维护 `accepted_index.csv`、review cache、source text 字段和 manifest。
- 建设 future full-text / section-text / evidence span 数据层。

不负责：

- 不做具体研究方向排序。
- 不生成研究 idea。
- 不把 subagent 总结当作 authoritative abstract 或 metadata。

### `resmax-embedding`

职责：

- 为 queryable papers 构建 paper-level embedding cache。
- 保证 cache 与 `accepted_index.csv` 的 `paper_id` 和内容 hash 对齐。
- 未来扩展 section-level embedding，但必须独立版本化。

不负责：

- 不决定方向 ROI。
- 不负责正文解析。

### `resmax-survey`

职责：

- 从模糊研究兴趣开始，构建领域地图。
- 粗到细地检索、聚类、抽取、排序文献。
- 识别子方向、技术路线、benchmark 机会、方法迁移机会、实验成本和 SOTA 压力。
- 输出 `research_pack/`，作为 `resmax-idea` 的主要输入资产。

不负责：

- 不直接编造最终研究 idea。
- 不在证据不足时强行给高置信结论。
- 不绕过 database validator 进入生产调研。

### `resmax-idea`

职责：

- 消费 `research_pack/`。
- 生成、比较、反驳、进化研究假设。
- 规划实验、baseline、dataset、metric、ablation、visualization、投稿叙事。
- 输出 idea ranking、risk register、experiment plan。

不负责：

- 不重新做泛化检索，除非 `research_pack` 明确标记缺证据。
- 不绕过 survey evidence chain 直接下结论。
- 不自动执行大规模实验，除非用户明确进入实验执行 skill。

## 6. 执行主线

```text
Round 0: Seed Intent
  输入一句话或聊天上下文
  输出 ResearchBrief + SourcePolicy
  重点是发现 unknowns、constraints、可信来源策略

Round 1: Macro Survey
  使用 title / abstract / metadata 做 broad retrieval
  输出 subdirection_map.md 和 subdirection_roi_table.csv
  只能给 rough ROI，不给强 idea 推荐

Round 2: Focused Evidence Survey
  用户选择 1-N 个子方向
  对 top candidates 启用 targeted full-text / section extraction
  输出 EvidenceCard、paper_attribute_table 和 evidence_spans

Round 3: ClaimGraph / GapMap
  把 EvidenceCard 编译成 claim nodes 和 evidence-backed tension
  识别 contradiction、missing evidence、benchmark blind spot、reviewer pressure

Round 4: Research Pack
  固化方向、候选论文、角色、证据、baseline、benchmark、风险
  输出 research_pack/

Round 5: Idea Tournament
  resmax-idea 基于 GapMap 和 research_pack 生成候选 idea
  通过 cross-model critique、adversarial review、proximity/diversity 去重排序

Round 6: Experiment Planning
  把 top idea 转成 claim-driven 实验计划
  进入实验执行前必须有 human gate
```

## 7. 长任务不偏离主线的硬规则

执行 agent 应反复回看这些规则：

1. **Evidence first**：强结论必须绑定 evidence id。没有证据就输出 `unknown` 或 `insufficient_evidence`。
2. **Feedback before claim**：没有 eval feedback sensor，不能声称优于 web chat / deep research。
3. **Human gates**：Round 1 子方向选择、Round 2 最终方向选择、idea tournament 后实验投入，必须允许用户干预。
4. **Smallest adequate mechanism**：优先最小足够机制，不堆 skill、不堆 agent、不堆 UI。
5. **Claim-driven experiments**：实验服务于 claim，不服务于“看起来完整”。
6. **Cross-model critique where it matters**：对 idea、claim、reviewer risk 使用不同模型或不同 agent 审查，减少单模型自证循环。
7. **Persistent negative memory**：失败 idea、低 ROI 方向、不可复现实验、审稿高风险点必须长期保存，避免重复犯错。
8. **Reproducible artifacts**：每阶段产物必须可重新读取、可校验、可恢复，不依赖一次对话上下文。
9. **No gray fallback by default**：灰色 PDF fallback 默认关闭，必须用户显式授权。
10. **State before prose**：报告必须由 ResearchBrief、SourcePolicy、EvidenceCard、ClaimGraph、GapMap 等状态产物生成，不让自然语言总结成为唯一事实源。
11. **Do not optimize locally into a dead end**：长任务发现目标/路径有偏差时，停止并回到北极星，而不是继续修补局部产物。

---

# 第二部分：Skill 编写计划

## 8. 当前代码边界审计

现有项目已经有三条主线 skill：

```text
.agents/skills/resmax-database/
  build_accepted_index.py
  enrich_all.py
  normalize_database.py
  validate_database.py
  ensure_reviews_available.py
  package_reviews_for_hf.py
  restore_reviews_from_hf.py

.agents/skills/resmax-embedding/
  build_cache_multigpu.py
  encode_query.py

.agents/skills/resmax-survey/
  search_literature.py
  stage5_5_deepcheck.py
  search_literature_lib/
```

当前 `resmax-survey` v1 能做：

- database validator gate。
- review cache availability gate。
- keyword + paper-level embedding 双路召回。
- candidate merge / metadata enrichment。
- subagent scoring 写入 `scores_raw.json`。
- `apply_scores()` 统一回写 `research_index.csv`。
- S/A 论文的 paper source cache 和 repo deepcheck prompt。

当前缺口：

- 没有 `research_intent` schema。
- 没有 `ResearchBrief` / `SourcePolicy` schema。
- 没有 query family generator。
- 没有 subdirection clustering / field map。
- 没有 role-aware retrieval 和 role-aware scoring。
- 没有 `EvidenceCard`。
- 没有 `ClaimGraph`。
- 没有 `GapMap` / contradiction mining。
- 没有 body-level evidence span store。
- 没有 `research_pack/` validator。
- 没有把 harness engineering 系统性嵌入 survey / idea：eval sensor、activity log、state recovery、mechanical checks、human gates 仍未形成一致 contract。
- 没有 `resmax-idea`。

## 9. 实施原则

不建议立即新建一整套平台。更低成本路径：

1. **保留现有 `resmax-survey` v1 作为 baseline**。
2. **新增 schema / validator / artifact layout，再扩展管线**。
3. **先做 4DGS 或 3DGS editing pilot，不先做全领域泛化**。
4. **先把最低限度 harness engineering 约束嵌入现有 skill，让 Round 1 的收益、失败和漂移可观察，再推进 full-text 和 idea tournament**。
5. **把外部 harness engineering 的机制吸收进 Resmax 数据合同、脚本和产物规范，而不是引入整套平台或新增“harness 层”**。

## 10. 建议新增目录

```text
.agents/skills/resmax-survey/
  schemas/
    research_brief.schema.json
    source_policy.schema.json
    research_intent.schema.json
    query_family.schema.json
    subdirection.schema.json
    evidence_card.schema.json
    claim_graph.schema.json
    gap_map.schema.json
    paper_attribute.schema.json
    evidence_span.schema.json
    research_pack.schema.json
  scripts/
    generate_intent.py
    generate_query_families.py
    cluster_subdirections.py
    build_subdirection_map.py
    build_evidence_cards.py
    build_claim_graph.py
    mine_gap_contradictions.py
    extract_paper_attributes.py
    build_research_pack.py
    validate_research_pack.py
    run_survey_eval.py
    update_negative_memory.py
  references/
    v2_artifact_contract.md
    v2_scoring_rubric.md
    evidence_state_machine.md
    source_policy.md

.agents/skills/resmax-idea/
  SKILL.md
  schemas/
    idea_card.schema.json
    idea_tournament.schema.json
    experiment_plan.schema.json
  scripts/
    validate_idea_report.py
    render_radar_data.py
    run_idea_eval.py
  references/
    idea_tournament_protocol.md
    adversarial_review_rubric.md
    claim_driven_experiment_plan.md
```

不新增 `.agents/harness/`。Harness engineering 作为约束嵌入现有目录：

- eval sensors 放在对应 skill 的 `scripts/run_*_eval.py` 和 `references/*_eval_protocol.md`。
- human gates 放在 `SKILL.md` 的执行协议和每轮产物 manifest 中。
- activity logs、state files、missing reports 放在每次 survey / idea 的输出目录中。
- mechanical checks 放在 validator 脚本中。
- failure recovery 写入对应 skill 的 `references/failure_recovery.md`。

## 11. Phase 0：Schema 与 Validator

目标：

- 先定义可校验 contract，再让 agent 生成内容。
- 防止大模型输出变成不可复用 markdown。

产物：

```text
schemas/research_brief.schema.json
schemas/source_policy.schema.json
schemas/research_intent.schema.json
schemas/query_family.schema.json
schemas/subdirection.schema.json
schemas/evidence_card.schema.json
schemas/claim_graph.schema.json
schemas/gap_map.schema.json
schemas/evidence_span.schema.json
schemas/research_pack.schema.json
scripts/validate_research_pack.py
references/v2_artifact_contract.md
references/evidence_state_machine.md
```

关键设计：

- 所有 schema 必须有 `schema_version`。
- 所有结论字段必须有 `evidence_ids` 或 `evidence_status`。
- `unknown`、`not_applicable`、`not_found` 必须区分。
- 数值字段不能用 `unknown` 字符串；使用 `null` + `evidence_status`。
- Markdown 是展示层，不是主数据层。
- `EvidenceCard` 是最终推理的最小证据单元；raw chunk、abstract、web snippet 不能直接支撑强 claim。
- `ClaimGraph` 是 idea 生成的中间层；idea 不能直接从 paper list 或 topic list 随机生成。

验收：

```text
python3 .agents/skills/resmax-survey/scripts/validate_research_pack.py \
  --pack /tmp/resmax_pack_smoke
```

smoke pack 必须能验证失败和验证通过两种情况。

## 12. Phase 1：Harness Engineering 约束先行

目标：

- 把“不能比 web chat / Deep Research 差”变成可测反馈。
- 让 agent 的上下文、动作空间、失败恢复和人工干预都在 skill 设计中可观察、可控制。
- 避免先开发四个阶段，最后才发现没有收益或无法复盘失败。

Harness engineering 关注面：

```text
context delivery:
  RESMAX_RESEARCH_AGENT_PLAN.md as high-level map
  SKILL.md as executable protocol
  schemas / references as deeper source of truth

tool/action space:
  deterministic scripts for retrieval, validation, scoring, rendering
  no hand-edited CSV for generated fields
  no gray fallback without explicit user approval

mechanical enforcement:
  schema validators
  artifact consistency checks
  evidence coverage checks
  accepted_index / embedding cache hash checks

feedback sensors:
  current v1 baseline
  pure keyword / pure embedding baselines
  web chat / deep research saved baseline outputs
  unsupported claim rate
  evidence support rate
  human preference notes

state and recovery:
  manifest.json
  activity_log.jsonl
  missing_source reports
  resume state for long extraction / tournament loops

human oversight:
  Round 1 subdirection choice
  Round 2 final direction choice
  idea tournament decision
  experiment execution approval
```

最小 eval set：

```text
pilot_4dgs_editing.jsonl
  5-10 个 seed
  每个 seed 包含：
    user_intent
    target_venue
    timeline_weeks
    compute_budget
    known_must_read_papers
    expected_roles:
      direct_baseline
      method_donor
      benchmark_opportunity
      implementation_reference
      negative_evidence
```

Baseline：

- current `resmax-survey` v1。
- pure paper-level embedding。
- pure keyword。
- fixed web chat / deep research outputs。

关键指标：

```text
role_recall@50
must_read_miss_rate
subdirection_coverage
unsupported_claim_rate
unknown_when_missing_rate
top_30_experiment_usefulness
human_preference
```

验收：

- eval sensor 能固定输入、固定输出、固定评分脚本。
- baseline 输出被保存，不能只保存摘要。
- V2 的任何收益声明都必须引用 eval run id 和 activity log。
- 长任务中断后能从 manifest / state 文件恢复，而不是依赖对话上下文。

## 13. Phase 2：ResearchBrief / SourcePolicy / Round 1

目标：

- 从用户模糊兴趣生成 ResearchBrief 和 SourcePolicy。
- 从 intent 生成 query families。
- 用 paper-level 数据做 broad retrieval 和子方向地图。

新增脚本：

```text
generate_research_brief.py
generate_source_policy.py
generate_intent.py
generate_query_families.py
cluster_subdirections.py
build_subdirection_map.py
```

输入：

```json
{
  "seed_goal": "4DGS editing",
  "target_venue": "CVPR/ICCV",
  "timeline_weeks": 8,
  "compute_budget": "1x4090",
  "team_size": 1
}
```

输出：

```text
survey_round_1/
  research_brief.json
  source_policy.json
  query_families.json
  broad_candidates.csv
  topic_clusters.json
  subdirection_map.md
  subdirection_roi_table.csv
  evidence_notes.md
```

重要限制：

- Round 1 只能给 rough ROI。
- 涉及 benchmark、compute、baseline burden 的结论必须标记 `evidence_status=weak`，除非已有 full-text 或 repo evidence。
- 如果用户 profile 缺失，允许继续 broad survey，但不允许输出强排序。
- SourcePolicy 必须区分 authoritative paper、review discussion、benchmark/code repo、blog/news 等 source tier。
- 强 claim 必须来自 primary source 或由 primary source 支撑的 EvidenceCard。

## 14. Phase 3：Targeted Full-Text 与 EvidenceCard

目标：

- 只对 selected subdirection 的 top candidates 做正文解析。
- 支撑 dataset / benchmark / baseline / metric / compute / limitation 抽取。
- 把 raw text / table / caption / review / repo signal 压成可推理的 EvidenceCard。

复用现有：

- `stage5_5_deepcheck.py`
- `paper_sources/<paper_id>/`
- `source_text_status`
- `source_text_url`
- `deepcheck_missing_source.json`
- `deepcheck_missing_pdf.json`

新增：

```text
evidence_cards.jsonl
extract_paper_attributes.py
evidence_spans.jsonl
paper_attribute_table.parquet
section_cache_manifest.json
```

Full-text source priority：

```text
1. arXiv TeX source when available
2. official / OA PDF text layer
3. MinerU fallback for selected candidates
4. manual only when explicitly requested
```

字段约束：

```json
{
  "evidence_id": "",
  "paper_id": "",
  "source_type": "paper|review|benchmark|code|issue|blog|manual",
  "claim": "",
  "scope": "",
  "support_type": "supports|contradicts|context|baseline|negative|risk",
  "strength": "strong|medium|weak",
  "quote_or_table_ref": "",
  "source_path": "",
  "section": "",
  "page": null,
  "extractor": "parser|regex|llm|metadata|manual",
  "checked_at": ""
}
```

验收：

- 每个 body-level 字段都有 evidence status。
- final pack 中的 direct baseline / dataset / metric / compute estimate 不能只有 LLM 总结。
- 没解析成功的论文必须进入 missing report，而不是静默跳过。
- 被丢弃或降权的证据也要记录原因，防止 confirmation bias。

## 15. Phase 4：ClaimGraph / GapMap / Role-Aware Ranking

目标：

- 把 EvidenceCard 编译成 ClaimGraph。
- 从 claim tension 中挖 gap / contradiction / benchmark blind spot。
- 从“相关性排序”升级为“论文角色 + 证据张力 + ROI 信号 + 用户约束”的排序。

Claim node：

```json
{
  "claim_id": "",
  "canonical_claim": "",
  "scope": "",
  "supporting_evidence_ids": [],
  "contradicting_evidence_ids": [],
  "confidence": "high|medium|low|unknown",
  "status": "supported|contested|under_evidenced|stale|unknown"
}
```

Gap node：

```json
{
  "gap_id": "",
  "gap_type": "contradiction|missing_evidence|benchmark_blind_spot|method_transfer|reviewer_pressure|resource_arbitrage",
  "claim_ids": [],
  "evidence_ids": [],
  "why_interesting": "",
  "minimum_experiment_to_resolve": "",
  "roi_hypothesis": "",
  "risk_level": "low|medium|high"
}
```

Paper roles：

```text
direct_baseline
method_donor
benchmark_opportunity
dataset_source
implementation_reference
negative_evidence
survey_or_taxonomy
theory_or_mechanism
visualization_reference
reviewer_expectation_reference
```

新增产物：

```text
claim_graph.json
gap_map.json
gap_candidates.md
negative_memory_delta.jsonl
```

Research pack layout：

```text
research_pack/
  manifest.json
  research_intent_final.json
  research_index.csv
  evidence_cards.jsonl
  claim_graph.json
  gap_map.json
  paper_roles.json
  paper_attribute_table.parquet
  evidence_spans.jsonl
  field_map.md
  roi_model.json
  risk_register.md
  benchmark_matrix.csv
  baseline_matrix.csv
  compute_estimate.md
  idea_seed_constraints.md
```

`manifest.json` 至少包含：

```json
{
  "pack_id": "",
  "schema_version": "0.1",
  "created_at": "",
  "accepted_index_sha256": "",
  "embedding_cache_meta": {},
  "source_counts": {},
  "evidence_counts": {},
  "eval_run_id": null,
  "activity_log_path": "",
  "mechanical_checks": {}
}
```

验收：

- `validate_research_pack.py` PASS。
- 所有强排序项能追溯到 evidence ids。
- 如果 evidence 不足，输出 `insufficient_evidence`，不生成强推荐。
- idea seed 必须来自 GapMap 或明确标记为 human-provided，不允许从 paper list 直接自由联想。

## 16. Phase 5：`resmax-idea`

目标：

- 基于 GapMap 和 research pack 生成和筛选研究 idea。
- 引入跨模型/跨 agent 批评，减少单模型自证偏差。
- 用 pairwise / proximity / lineage 替代单点绝对评分。

输入：

```text
research_pack/
  gap_map.json
  claim_graph.json
  evidence_cards.jsonl
```

输出：

```text
idea_report/
  manifest.json
  idea_cards.json
  idea_rankings.md
  tournament_trace.jsonl
  direction_radar_data.json
  experiment_plan.md
  baseline_plan.csv
  dataset_metric_plan.csv
  ablation_plan.md
  visualization_plan.md
  risk_register.md
  reviewer_rebuttal_prep.md
```

Idea card schema：

```json
{
  "idea_id": "",
  "claim": "",
  "problem_anchor": "",
  "source_gap_ids": [],
  "source_claim_ids": [],
  "why_now": "",
  "mechanism": "",
  "direct_baselines": [],
  "method_donors": [],
  "benchmark_opportunities": [],
  "core_experiments": [],
  "ablation_plan": [],
  "visualization_plan": [],
  "estimated_compute": "",
  "estimated_timeline": "",
  "expected_failure_modes": [],
  "reviewer_attack_points": [],
  "evidence_ids": [],
  "lineage": {
    "parent_idea_ids": [],
    "mutation_reason": ""
  },
  "status": "candidate|rejected|refine|proceed|insufficient_evidence"
}
```

Tournament protocol：

```text
Generate
  -> Novelty Check
  -> Feasibility Check
  -> Pairwise Comparison
  -> Adversarial Review
  -> Proximity / Diversity Dedup
  -> Evolve
  -> Meta Review
  -> PROCEED / REFINE / PIVOT / INSUFFICIENT_EVIDENCE
```

硬门槛：

- 核心 idea 至少绑定 2 篇 direct baseline。
- 至少绑定 2 篇 method donor 或 adjacent-domain transfer paper。
- 至少绑定 1 个 benchmark / dataset / metric 机会。
- 至少给出 1 条 negative evidence 或 reviewer risk。
- 必须给出 baseline / dataset / metric / ablation / visualization plan。
- 不满足时输出 `insufficient_evidence`。
- 相似 idea 必须先互相比，逼出机制差异；表达更完整不等于更好。
- evolution 不覆盖父 idea，必须生成 child idea 并保留 lineage。

## 17. Phase 6：Claim-Driven Experiment Plan

不建议 `resmax-idea` 直接执行实验。先只产出 experiment plan。

Experiment plan 必须回答：

- Primary claim 是什么？
- Supporting claim 是否必要？
- 哪个实验最小但足以改变 reviewer belief？
- 哪些 baseline 是 must-run，哪些只是 appendix？
- 哪些 ablation 是 claim-critical，哪些是 nice-to-have？
- 失败结果如何解释？

执行前 human gate：

```text
PROCEED: 进入实验执行 skill
REFINE: 回到 idea tournament 或 focused survey 补证据
PIVOT: 回到 Round 1 / Round 2 选择新方向
STOP: 记录低 ROI / 失败原因到 persistent memory
```

## 18. 开放问题

需要在 Phase 0/1 解决：

1. `user_profile` 是否作为 ROI 排序必填项？建议：target venue、timeline、compute budget 至少要有显式默认或 `unknown`。
2. Round 1 broad retrieval 候选规模是 300、500 还是 1000？建议由 eval sensor pilot 测。
3. section-level embedding 使用同一个 Qwen3-Embedding-8B 还是轻量模型？建议先不训练新模型，先用现有模型 + sparse index。
4. full-text parsing fallback 顺序如何固化？建议先按 TeX、OA PDF text、MinerU selected fallback。
5. web chat baseline 选哪些系统？建议先固定 2 个：ChatGPT Deep Research 和 Perplexity/Gemini 中一个，保存完整输出和日期。
6. Harness engineering 的最低约束应嵌入哪些现有产物？建议先做 eval outputs、activity logs、artifact checks、failure recovery 和 human gate manifest，不做独立目录或 skill。

---

# 第三部分：机制吸收与 Resmax 原生设计

本部分参考 `RESMAX_RESEARCH_AGENT_MECHANISM_SURVEY.md`，但不复述调研。目标是回答：

1. 哪些机制值得直接吸收？
2. 哪些机制只适合作为启发，不应照搬？
3. Resmax 应如何利用自身文献库、review cache、source_text contract 和 embedding cache，设计超越公开项目的机制？

## 19. 值得吸收的机制

### 19.1 ResearchBrief / SourcePolicy

值得吸收。

原因：

- Resmax 的输入经常是“我想做 4DGS”这种模糊意图。
- 如果不先编译成 ResearchBrief，后续检索、ROI 和 idea tournament 都会漂移。
- SourcePolicy 能把 idea 生成约束到可信信息分布，而不是 web synthesis 或模型自由联想。

落地：

- `research_brief.json` 作为 Round 0 的主产物。
- `source_policy.json` 规定 source tier、claim 支撑门槛、web fallback 边界。
- 缺失的 target venue、timeline、compute budget、team profile 标记为 `unknown`，但强 ROI 排序必须降置信度。

### 19.2 EvidenceCard

强烈吸收。

原因：

- Resmax 当前已有 `abstract_raw`、`source_text_url`、review cache 和部分 `paper_sources/`，但还缺少“可推理证据单元”。
- raw PDF chunk、abstract、web snippet 都太粗，不能直接支撑强 claim。

落地：

- `evidence_cards.jsonl` 成为 focused survey 的核心产物。
- 每个 EvidenceCard 必须保留 `paper_id`、source type、claim、scope、support type、strength、原文定位。
- 被丢弃证据也记录 discard reason，避免 confirmation bias。

### 19.3 ClaimGraph / GapMap

强烈吸收，并作为 Resmax 的核心差异点。

原因：

- Resmax 不应从 paper list 直接生成 idea。
- 高价值 idea 更多来自 claim 之间的张力：矛盾、未验证假设、benchmark blind spot、reviewer pressure、resource arbitrage。

落地：

- `claim_graph.json` 维护 canonical claim、scope、supporting / contradicting evidence。
- `gap_map.json` 维护 gap type、claim ids、evidence ids、minimum experiment、ROI hypothesis。
- `resmax-idea` 只能从 GapMap 或 human-provided idea seed 生成候选 idea。

### 19.4 Perspective / Moderator

吸收，但不做成多 agent 装饰。

原因：

- STORM / Co-STORM 的价值不是“多人聊天”，而是 perspective 控制问题覆盖。
- Resmax 应把 perspective 变成 query family、evidence branch 和 unused evidence 检查。

落地：

- Round 1 生成 `perspective_questions.json`。
- 视角至少包括 method、benchmark、implementation、reviewer、transfer。
- Moderator 不是一个聊天角色，而是 `unused_evidence_notes.md` + `missing_perspectives` 检查。

### 19.5 Idea Tournament / Cross-Model Critique

吸收，但必须基于 GapMap 和 EvidenceCard。

原因：

- 前沿 idea 没有稳定 ground truth，单点绝对评分不可靠。
- 相似 idea 的细粒度差异只有 pairwise comparison 才容易暴露。

落地：

- idea card 必须引用 `source_gap_ids`、`source_claim_ids`、`evidence_ids`。
- reviewer 只看 evidence package，不看 generator 自我包装。
- evolution 生成 child idea，保留 lineage，不覆盖父 idea。
- `tournament_trace.jsonl` 记录比较、淘汰和演化原因。

### 19.6 Problem Anchor / Claim-Driven Experiment

强烈吸收。

原因：

- 这是防止“被 reviewer 一批评就加模块 / 换问题”的关键。
- 实验计划必须回答 claim，而不是罗列 benchmark。

落地：

- `problem_anchor` 写入 `research_brief.json`、`research_pack/` 和每个 idea card。
- experiment plan 先写 claim map，再写 experiment blocks。
- 每个实验块必须说明 tested claim、anti-claim、minimum convincing evidence、failure interpretation。

### 19.7 Trace / Eval / Negative Memory

吸收，但作为 harness engineering 思想嵌入产物，不新增独立 harness 层。

原因：

- 没有 trace，skill 修改只能靠感觉。
- 没有 negative memory，系统会反复生成语义上诱人的失败方向。

落地：

- 每轮 survey / idea 输出 `activity_log.jsonl`。
- `negative_memory_delta.jsonl` 记录 rejected idea、low ROI gap、failed evidence path、reviewer attack points。
- eval 输出作为 feedback sensor，不作为单独 skill。

## 20. 不应照搬的部分

### 20.1 不照搬通用 autonomous research platform

原因：

- Resmax 的核心资产是 curated AI paper database，不是通用 browser agent。
- 引入通用平台会稀释 source contract、schema validator 和本地 artifact 优势。

替代：

- 只吸收机制，把机制写入现有 skill 和 scripts。

### 20.2 不急于自动实验执行

原因：

- CV/graphics/LLM 研究的实验环境复杂度高。
- 没有 claim graph 和 small empirical gate，自动执行容易把算力花在低 ROI 方向。

替代：

- `resmax-idea` 先输出 claim-driven experiment plan。
- 实验执行作为后续独立 skill，只在 human gate 后进入。

### 20.3 不把 multi-agent 当作目标

原因：

- 多 agent 本身不产生质量。
- 没有共享 evidence state，多 agent 会制造更多自然语言噪声。

替代：

- 先建设共享状态：ResearchBrief、EvidenceCard、ClaimGraph、GapMap。
- 再在 idea tournament 和 review risk 上使用 cross-model critique。

## 21. Resmax 原生机制：Evidence-Tension State Machine

公开项目大多把 research agent 做成“任务流”：

```text
plan -> search -> summarize -> write
```

Resmax 应该做成“证据张力状态机”：

```text
ResearchBrief
  -> SourcePolicy
  -> RetrievalTrace
  -> EvidenceCard
  -> ClaimGraph
  -> GapMap
  -> ROI Lens
  -> Idea Tournament
  -> Claim-Driven ExperimentPlan
  -> Negative Memory
```

关键差异：

- idea 不是从 prompt 生成，而是从 evidence tension 编译出来。
- ranking 不是相关性排序，而是 gap 的可解决性、可投稿性、实验代价和 reviewer pressure 的联合判断。
- report 不是事实源，状态文件才是事实源。

## 22. Resmax 原生机制：Reviewer-Pressure ROI Lens

这是 Resmax 相比通用项目的独特机会，因为 Resmax 已经维护 review cache。

公开项目通常只根据论文文本和通用 reviewer prompt 估计风险。Resmax 可以进一步引入：

```text
review_score_mean
review_confidence_mean
reviewer objections
acceptance type
venue / year
source_text_status
code / dataset availability
```

设计：

```text
ReviewerPressure(gap)
  = recurring reviewer objections in related papers
  + missing baseline patterns
  + reproducibility complaints
  + novelty / significance pressure
  + venue-specific expectation
```

用途：

- 在 GapMap 中标记 `reviewer_pressure`。
- 在 idea tournament 中生成 `reviewer_attack_points`。
- 在 experiment plan 中优先安排能降低 reviewer pressure 的实验。

这比公开项目的 generic adversarial reviewer 更贴近 Resmax，因为它利用了真实 review 分布。

## 23. Resmax 原生机制：Source-Weighted Gap Mining

不是所有 gap 都同等可信。Resmax 应按 source weight 挖 gap：

```text
strong:
  accepted paper full text
  official benchmark / leaderboard
  OpenReview review discussion
  official code / issue

medium:
  arXiv preprint
  project page
  Semantic Scholar / OpenAlex metadata

weak:
  blog
  social media
  model-generated summary
```

机制：

- Gap 的 `confidence` 由 supporting / contradicting EvidenceCard 的 source weight 决定。
- weak source 可以触发 query expansion，但不能支撑强 idea。
- 缺失 source 不是空白，而是 `missing_evidence`，可转成下一轮 retrieval target。

这比普通 RAG 更适合科研，因为它区分“读到了”和“足以支撑 claim”。

## 24. Resmax 原生机制：Negative Memory as Source Policy

负记忆不只是归档失败，它应该反过来影响检索和生成。

设计：

```text
negative_memory_delta.jsonl:
  rejected_idea
  low_roi_gap
  failed_experiment
  impossible_baseline
  missing_data_blocker
  reviewer_attack_unresolved
```

在下一轮中：

- SourcePolicy 读取 negative memory，生成 exclude terms 和 caution terms。
- GapMap 标记类似失败路径。
- Idea Tournament 对重复 idea 直接降权或要求说明 difference。

这比公开项目的 idea archive 更强，因为它进入 SourcePolicy，而不是只存在于历史记录中。

## 25. Resmax 原生机制：Minimum Experiment to Change Belief

实验计划不应问“还要跑哪些实验”，而应问：

```text
哪个最小实验能改变 reviewer belief？
```

每个 GapMap node 应提前生成：

```json
{
  "minimum_experiment_to_resolve": "",
  "expected_belief_update": "",
  "cost": "",
  "risk": "",
  "fallback_if_negative": ""
}
```

Idea Tournament 不只比较 idea 本身，还比较：

- 解决该 gap 的最小实验是否便宜。
- 负结果是否仍有信息价值。
- baseline 是否能复现。
- 结果能支撑多强 claim。

这把 ROI 从“方向偏好”变成“证据更新效率”。

## 26. 对当前实施顺序的修正

原计划的顺序应调整为：

```text
P0: Schema + validator
  ResearchBrief
  SourcePolicy
  EvidenceCard
  ClaimGraph
  GapMap

P1: Eval sensor + activity log
  v1 baseline
  web/deep-research baseline
  evidence support rate
  unsupported claim rate

P2: resmax-survey V2 Round 0/1
  ResearchBrief
  SourcePolicy
  query families
  broad subdirection map

P3: Targeted evidence state
  full-text selected candidates
  EvidenceCard
  ClaimGraph
  GapMap

P4: ResearchPack
  role-aware ranking
  reviewer-pressure ROI
  negative memory delta

P5: resmax-idea
  gap-driven idea tournament
  cross-model reviewer
  proximity / lineage

P6: Claim-driven experiment plan
  minimum experiment to change belief
  anti-claim
  human gate
```

这条路径比公开项目更贴合 Resmax：它不是更大的聊天机器人，而是一个以 AI 顶会文献库为核心的证据状态机。
