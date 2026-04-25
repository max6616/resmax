# 科研 Agent 机制调研：面向 Resmax 的设计原则

更新日期：2026-04-25

本文不是按项目逐个介绍，而是按可迁移机制组织。目标是回答三个问题：

1. 一个高质量前沿 idea 应该从哪里产生？
2. 一个细致、可执行、可投稿的实验方案应该怎样被构造？
3. 多个优秀科研 agent 项目背后有哪些共同底层原理？

调研对象包括 ARIS、OpenAI Deep Research、STORM / Co-STORM、GPT Researcher、LangChain Open Deep Research、Hugging Face Open Deep Research / smolagents、PaperQA2 / WikiCrow / OpenScholar、Sakana AI Scientist、Google AI Co-Scientist。

核心结论：

```text
strong research agent
  != bigger chat loop
  != more web search
  != one model brainstorming longer

strong research agent
  = evidence-first state machine
  + claim graph
  + gap / contradiction mining
  + adversarial idea tournament
  + claim-driven experiment planning
  + small empirical gates
  + persistent negative memory
```

---

## 1. Intent 编译：从模糊愿望到可执行研究任务

### 理念

科研 agent 的第一个瓶颈不是生成能力，而是目标表达不充分。

用户通常给出的是模糊愿望：

```text
我想做一个前沿、有理论贡献、能投顶会的方向
```

这句话缺少：

- 目标领域边界。
- 目标 venue / reviewer expectation。
- 理论偏好。
- 可用算力、数据、代码基础。
- 不接受的方向。
- 预期产物形态。
- 风险容忍度。

OpenAI Deep Research、LangChain Open Deep Research、Google AI Co-Scientist 都把这个问题前置处理：先澄清、改写、编译，再开始研究。

### 技术框架

建议抽象成：

```text
RawIntent
  -> Clarification
  -> ResearchGoalConfig
  -> SourcePolicy
  -> ResearchBrief
```

关键 artifact：

```json
{
  "goal": "",
  "scope": "",
  "target_venue": "",
  "theory_preference": [],
  "resource_constraints": {},
  "allowed_sources": [],
  "blocked_sources": [],
  "evaluation_criteria": [],
  "forbidden_directions": [],
  "open_questions": []
}
```

### 实现细节

- `Clarification Gate`：目标、范围、约束不足时不进入调研。
- `ResearchBrief` 必须是后续所有 agent 的 north star。
- 不允许 agent 静默补全关键条件；缺失字段标记为 `unknown`。
- `SourcePolicy` 先于检索生成，决定哪些信息源可用、优先、禁用。
- 对 Resmax 来说，source priority 应是：
  1. 本地 `accepted_index.csv` 与 review cache。
  2. 近两年 AI 顶会/顶刊论文。
  3. 官方 benchmark / leaderboard / code repo。
  4. 论文正文 method / experiment / appendix。
  5. web / blog 只作为补充。

### 补足的能力

这个机制补足的是 **目标约束能力**。

没有它，后续 idea generation 会变成单模型自由联想。自由联想看起来多样，但不受 venue、资源、证据和失败风险约束，很难产出可投入方向。

### 为什么更简单机制不够

简单地把用户 prompt 直接交给 deep research 或 LLM brainstorming 有两个问题：

1. 模型会把缺失约束隐式补齐，用户很难发现。
2. 后续评审没有固定参照物，idea 被批评后很容易漂移到另一个问题。

因此 intent 编译不是礼貌性提问，而是科研任务的 contract。

---

## 2. Source Policy：让 idea 从可信信息分布中产生

### 理念

高质量 idea 的输入分布比生成模型本身更重要。

OpenAI Deep Research 强调可控来源和 citation trace；PaperQA2 / OpenScholar 强调 scientific RAG 的 metadata-aware retrieval；GPT Researcher 和 LangChain Open Deep Research 强调 source tracking。共同点是：先约束信息源，再综合。

### 技术框架

```text
SourcePolicy
  -> RetrieverConfig
  -> RetrievalTrace
  -> EvidenceCard
```

`SourcePolicy` 不只是 allowed URL list，而应包括：

- source type：paper、benchmark、code、review、issue、blog。
- authority level：primary、official、secondary、unverified。
- temporal window：例如 2024-2026。
- venue filter。
- corpus filter。
- private corpus / public web 分阶段策略。
- source independence requirement。

### 实现细节

建议字段：

```json
{
  "preferred_sources": [
    "primary_paper",
    "official_benchmark",
    "source_code",
    "review_discussion"
  ],
  "blocked_sources": [
    "low_quality_blog",
    "uncited_summary"
  ],
  "freshness_window": "2024-2026",
  "require_primary_for_claims": true,
  "source_independence_min": 3,
  "private_public_mix_policy": "private_first_then_public"
}
```

检索时保存：

```json
{
  "query": "",
  "source": "",
  "source_type": "",
  "retrieved_at": "",
  "rank": 0,
  "reranker_score": 0.0,
  "reason_selected": "",
  "reason_dropped": ""
}
```

### 补足的能力

这个机制补足的是 **证据分布控制能力**。

科研 idea 的新颖性不是来自语言多样性，而是来自信息差：近期结果、反常 observation、被忽略限制、跨领域方法迁移、失败复现记录。

### 为什么更简单机制不够

“多搜几个网页”不能等价于 source policy。

原因：

- 多个网页可能共同复制同一个错误。
- 热门论文会被过度召回，低引用新线索会被淹没。
- web 摘要通常缺少实验条件、超参、失败边界。
- citation 存在不代表 citation 支持当前 claim。

因此 source policy 必须成为 schema，而不是 prompt 里的建议句。

---

## 3. EvidenceCard：把原始材料压成可推理证据单元

### 理念

PaperQA2 / OpenScholar 的核心启发是：不要让 LLM 直接拿 chunk 做科研判断。

PDF chunk、abstract、web snippet 太粗糙。它们需要先转成证据卡，明确：

- 论文到底主张了什么？
- 这个主张适用什么条件？
- 证据强度如何？
- 支持还是反驳某个 claim？
- 是否来自 method、result、appendix、discussion？

### 技术框架

```text
RawDocument
  -> section parsing
  -> chunk retrieval
  -> reranking
  -> contextual summarization
  -> EvidenceCard
```

建议 Resmax 后续采用类似 PaperQA2 的 RCS：

```text
RCS = re-ranking + contextual summarization
```

不是把 top chunk 直接塞进上下文，而是先生成 evidence card。

### 实现细节

`EvidenceCard` schema：

```json
{
  "evidence_id": "",
  "paper_id": "",
  "source_url": "",
  "section": "",
  "claim": "",
  "method": "",
  "result": "",
  "limitation": "",
  "scope": "",
  "variables": [],
  "support_type": "supports|contradicts|context|baseline|negative",
  "metadata": {
    "venue": "",
    "year": 0,
    "citation_count": null,
    "source_text_status": ""
  },
  "relevance_score": 0.0,
  "confidence": 0.0
}
```

关键实现规则：

- abstract 只用于粗召回，不用于最终 claim 支撑。
- method / experiment / appendix 优先用于实验计划。
- table 和 figure 需要结构化抽取或视觉检查。
- 每个 evidence card 必须保留原文定位。
- 被丢弃证据也应记录原因，防止 confirmation bias。

### 补足的能力

这个机制补足的是 **可验证推理能力**。

没有 evidence card，idea 生成会直接在自然语言材料上跳跃，无法检查某个假设到底来自哪条证据、证据条件是什么。

### 为什么更简单机制不够

普通摘要不够，因为摘要会抹掉科研最重要的细节：

- 实验条件。
- baseline 设置。
- 数据集限制。
- 失败模式。
- 作者实际 claim 的强弱。
- 结果是否只在某个 regime 成立。

EvidenceCard 的价值是把“读过论文”变成可查询、可验证、可组合的 evidence state。

---

## 4. ClaimGraph：把文献综述变成可计算假设空间

### 理念

PaperQA2 / OpenScholar、ARIS、Google AI Co-Scientist 都暗含一个共同点：idea 不应该从 topic list 里产生，而应该从 claim 之间的关系里产生。

关系包括：

- supports
- contradicts
- extends
- assumes
- fails_under
- tests
- invalidates
- leaves_gap

### 技术框架

```text
EvidenceCard
  -> ClaimNode
  -> ClaimGraph
  -> GapCluster
  -> ContradictionCase
  -> IdeaCandidate
```

### 实现细节

`ClaimNode`：

```json
{
  "claim_id": "",
  "claim": "",
  "scope": "",
  "assumptions": [],
  "variables": [],
  "supporting_evidence_ids": [],
  "contradicting_evidence_ids": [],
  "nearest_prior_work": [],
  "open_questions": []
}
```

`ClaimEdge`：

```json
{
  "source_claim_id": "",
  "target_claim_id": "",
  "relation": "supports|contradicts|extends|assumes|tests|invalidates",
  "evidence_ids": [],
  "confidence": 0.0
}
```

构图策略：

- 同一 technical claim 的不同表述要 canonicalize。
- claim 必须带 scope，避免伪矛盾。
- claim graph 中的 high-degree consensus 不一定是好 idea 来源。
- 低覆盖、高冲突、跨子领域桥接节点更值得生成 idea。

### 补足的能力

这个机制补足的是 **理论结构化能力**。

高质量理论 idea 往往不是“找一个没人做过的模块”，而是：

- 解释一个现有理论解释不了的 observation。
- 调和两个看似矛盾的结果。
- 发现一个共同假设在新 regime 下失效。
- 把 A 领域机制迁移到 B 领域 bottleneck。

这些都需要 claim-level 结构，而不是 paper-level 列表。

### 为什么更简单机制不够

普通 literature review 只回答“有哪些论文”，很难回答：

- 哪些 claim 互相冲突？
- 哪些 claim 共享同一个未验证假设？
- 哪个变量能区分两种解释？
- 哪些 benchmark 只验证了表象，没有验证机制？

ClaimGraph 是从“文献管理”到“科研推理”的关键跳跃。

---

## 5. Gap / Contradiction Mining：idea 的主要生成器

### 理念

PaperQA2 的 ContraCrow、OpenScholar 的 self-feedback retrieval、STORM 的 moderator、Google AI Co-Scientist 的 observation review 都指向同一件事：

```text
好 idea 不应来自空想，而应来自证据图里的张力。
```

张力包括：

- 文献矛盾。
- 方法迁移缺口。
- 共同但未验证假设。
- benchmark 覆盖缺口。
- 未解释 observation。
- 结果只在特定 regime 成立。
- reviewer 经常攻击但论文未解决的问题。

### 技术框架

```text
ClaimGraph
  -> contradiction detection
  -> gap clustering
  -> discriminating variable extraction
  -> pivotal experiment design
  -> IdeaCandidate
```

### 实现细节

`ContradictionCase`：

```json
{
  "case_id": "",
  "claim_a": "",
  "claim_b": "",
  "evidence_a": [],
  "evidence_b": [],
  "contradiction_score": 0.0,
  "is_pseudo_contradiction": false,
  "discriminating_variables": [
    "dataset",
    "model_scale",
    "training_recipe",
    "metric",
    "data_domain"
  ],
  "minimal_pivotal_experiment": ""
}
```

`GapCluster`：

```json
{
  "gap_id": "",
  "topic": "",
  "missing_evidence": "",
  "underexplored_variables": [],
  "nearest_papers": [],
  "why_now": "",
  "candidate_experiments": []
}
```

关键 gate：

- `Pseudo-Contradiction Gate`：排除术语差异、数据域差异、实验条件差异造成的伪矛盾。
- `Why-Now Gate`：解释为什么现在能做，过去为什么没做。
- `Pivotal Experiment Gate`：必须能提出区分解释的最小实验。

### 补足的能力

这个机制补足的是 **前沿问题发现能力**。

它让 agent 不再问“还有什么方向”，而是问：

```text
当前证据体系哪里不闭合？
哪个实验最便宜地改变 reviewer belief？
```

### 为什么更简单机制不够

让模型列 future work 不够。

原因：

- future work 往往是作者自我保护式表述。
- 热门但低 ROI 的方向会被反复推荐。
- 模型会偏向语义上“合理”的组合，而不是证据上有张力的位置。

Gap / contradiction mining 把 idea generation 从语言空间拉回证据空间。

---

## 6. Perspective / Moderator：系统性扩展问题视角

### 理念

STORM / Co-STORM 的关键不是“多 agent 更热闹”，而是让不同 perspective 控制问题生成，避免单一路径坍缩。

前沿科研中，单一视角经常漏掉：

- benchmark 视角。
- implementation 视角。
- reviewer risk 视角。
- theory mechanism 视角。
- method transfer 视角。
- negative result 视角。

### 技术框架

```text
ResearchBrief
  -> PerspectiveSet
  -> PerspectiveQuestion
  -> EvidenceTurn
  -> ModeratorIntervention
  -> MindMap / DirectionMap
```

### 实现细节

`Perspective`：

```json
{
  "role": "method|benchmark|theory|implementation|reviewer|transfer",
  "focus": "",
  "blind_spot": "",
  "question_templates": []
}
```

`QuestionTurn`：

```json
{
  "turn_id": "",
  "perspective": "",
  "question": "",
  "intent": "",
  "retrieved_evidence_ids": [],
  "new_concepts": [],
  "open_followups": []
}
```

Moderator 触发条件：

- 连续 N 轮没有新增 concept。
- 某个 branch 证据密度过高但 novelty 低。
- 有未使用但高相关证据。
- mind map 中存在高相关低覆盖节点。

### 补足的能力

这个机制补足的是 **覆盖能力与盲区发现能力**。

它不是为了模拟专家身份，而是为了强制系统从多个评价函数看同一问题。

### 为什么更简单机制不够

普通 prompt 写“从多个角度分析”不够。

原因：

- 模型会生成角度名，但不会让每个角度独立检索和追问。
- 多视角如果没有 moderator，会退化成重复观点。
- 没有 mind map，就无法判断哪些方向已经覆盖，哪些方向仍空白。

因此 perspective 必须驱动检索与证据状态，而不只是输出格式。

---

## 7. Idea Tournament：用竞争替代单点评分

### 理念

Google AI Co-Scientist 的 tournament、ARIS 的跨模型 adversarial review、Sakana 的 idea archive 共同说明：frontier idea 很难用一次绝对分数判断。

更可靠的方式是：

```text
generate many
  -> review independently
  -> compare similar candidates
  -> evolve children
  -> preserve lineage
  -> meta-review repeated failure modes
```

### 技术框架

```text
IdeaCandidate pool
  -> Proximity clustering
  -> Pairwise comparison
  -> Adversarial review
  -> Evolution
  -> Meta-review
  -> Ranking / routing
```

### 实现细节

`IdeaCandidate`：

```json
{
  "idea_id": "",
  "hypothesis": "",
  "mechanism": "",
  "novelty_source": "gap|contradiction|bridge|observation",
  "supporting_evidence": [],
  "contradicting_evidence": [],
  "nearest_prior_work": [],
  "assumptions": [],
  "testable_predictions": [],
  "minimal_experiment": "",
  "risk_register": []
}
```

`TournamentState`：

```json
{
  "idea_id": "",
  "lineage": [],
  "nearest_neighbors": [],
  "wins": 0,
  "losses": 0,
  "elo": 0,
  "comparison_rationales": [],
  "recurring_failure_patterns": [],
  "status": "candidate|refine|proceed|pivot|rejected|insufficient_evidence"
}
```

设计细节：

- 相似 idea 先互相比，逼出细粒度差异。
- reviewer 与 generator 隔离，最好跨模型。
- reviewer 只看 evidence package，不看 generator 自我包装。
- evolution 不覆盖父 idea，而是生成 child idea 重新参赛。
- Elo 只能作为 routing signal，不能当质量真理。

### 补足的能力

这个机制补足的是 **选择能力与偏差去相关能力**。

生成模型常见失败是：

- 喜欢自己刚生成的 idea。
- 把语言完整性误判为科学质量。
- 多个 idea 只是同一个想法改写。
- reviewer 给泛泛批评，不能推动进化。

Tournament 通过相对比较、近邻竞争、异构审稿和 lineage 追踪缓解这些问题。

### 为什么更简单机制不够

普通打分表不够。

原因：

- 前沿 idea 没有可靠 ground truth，绝对分数校准差。
- 不同 idea 之间的差异常在细节，只有 pairwise comparison 才容易暴露。
- 单轮 critique 只找问题，不负责产生改良候选。
- 没有 lineage，就无法知道一个 idea 为什么演化、是否偏离原问题。

---

## 8. Problem Anchor 与 Claim-Driven Experiment

### 理念

ARIS 的 `Problem Anchor` 和 claim-driven experiment 是实验计划中最重要的机制之一。

科研实验不是“把常见 benchmark 都跑一遍”，而是回答：

```text
这篇论文到底要让 reviewer 相信什么？
哪个最小实验能改变 reviewer belief？
哪个反证必须被排除？
```

### 技术框架

```text
ProblemAnchor
  -> ClaimMap
  -> AntiClaim
  -> MinimumConvincingEvidence
  -> ExperimentBlock
  -> ResultToClaim
```

### 实现细节

`ProblemAnchor`：

```json
{
  "bottom_line_problem": "",
  "must_solve_bottleneck": "",
  "non_goals": [],
  "constraints": [],
  "success_condition": ""
}
```

`ClaimMap`：

```json
{
  "primary_claim": "",
  "supporting_claims": [],
  "anti_claims_to_rule_out": [],
  "minimum_convincing_evidence": []
}
```

`ExperimentBlock`：

```json
{
  "experiment_id": "",
  "claim_tested": "",
  "dataset": "",
  "split": "",
  "task": "",
  "compared_systems": [],
  "primary_metric": "",
  "secondary_metrics": [],
  "setup_details": {},
  "success_criterion": "",
  "failure_interpretation": "",
  "table_or_figure_target": "",
  "priority": "must|nice|appendix|cut"
}
```

### 补足的能力

这个机制补足的是 **实验目标对齐能力**。

它让每个实验都有明确审稿意义：

- 支持哪个 claim？
- 排除哪个 alternative explanation？
- 失败后如何解释？
- 是 main paper 还是 appendix？

### 为什么更简单机制不够

benchmark matrix 不够。

原因：

- benchmark 多不等于 claim 清楚。
- 没有 anti-claim，实验只会支持自己，不会排除替代解释。
- 没有 failure interpretation，失败结果无法推动 pivot。
- 没有 Problem Anchor，reviewer 一批评就容易加模块、换问题。

---

## 9. Staged Experiment Lifecycle：从可行性到主张验证

### 理念

Sakana AI Scientist v1 / v2 和 ARIS 都显示：实验执行必须阶段化。

直接跑完整实验是高风险路径。更好的顺序是：

```text
sanity
  -> baseline reproduction
  -> feasibility prototype
  -> robust baseline / tuning
  -> main experiment
  -> ablation
  -> replication
  -> result-to-claim
```

### 技术框架

```text
ExperimentPlan
  -> RunOrder
  -> ExperimentNode tree
  -> Metrics / Plots / Logs
  -> ResultToClaim
```

### 实现细节

`ExperimentNode`：

```json
{
  "node_id": "",
  "parent_id": "",
  "stage": "sanity|baseline|prototype|main|hyperparam|ablation|replication|aggregation",
  "plan": "",
  "command": "",
  "metrics": {},
  "plots": [],
  "execution_log": "",
  "review_feedback": "",
  "status": "pending|running|buggy|valid|stopped"
}
```

关键 gate：

- `Baseline Gate`：baseline 不可复现，不进入主实验。
- `Sanity Gate`：数据、metric、训练流程不正常时停。
- `Ablation Gate`：核心机制必须有 remove / replace / sensitivity。
- `Replication Gate`：主结果必须多 seed 或多 split。
- `Plot Integrity Gate`：图表标签、legend、坐标轴、误导性可视化必须检查。
- `Result-to-Claim Gate`：结果只能支持对应强度的 claim。

### 补足的能力

这个机制补足的是 **实验成本控制与可复现能力**。

它避免 agent 在错误方向上花大算力，也避免把一次偶然结果包装成理论贡献。

### 为什么更简单机制不够

一次性生成完整实验计划不够。

原因：

- 早期最大不确定性通常是 feasibility，不是最终 SOTA。
- baseline 失败会让后续所有比较无意义。
- 主实验为正后才知道哪些 ablation 最关键。
- 图表和日志也是证据，不是写作装饰。

阶段化实验把科研投入变成 sequential decision process。

---

## 10. Code-as-Action 与确定性 artifact 操作

### 理念

Hugging Face smolagents 的 `CodeAgent` 提醒我们：复杂研究动作不适合全部用自然语言 tool call 表达。

统计、表格合并、schema validation、query expansion、dedup、plot data、ROI table 都应由代码完成。

### 技术框架

```text
LLM judgment
  -> code action
  -> deterministic artifact
  -> validation
  -> LLM interpretation
```

### 实现细节

适合代码化的部分：

- evidence card 去重。
- claim graph 构建。
- paper / evidence coverage 统计。
- idea proximity 计算。
- tournament trace 汇总。
- experiment budget 估算。
- result table 生成。
- schema validation。
- plot integrity rule check。

不适合代码化、仍需 LLM 判断的部分：

- claim 是否理论上有意义。
- gap 是否值得投入。
- reviewer risk 是否致命。
- 失败结果是否应 pivot。

### 补足的能力

这个机制补足的是 **确定性处理能力**。

科研 agent 不是所有事情都要交给 LLM。LLM 擅长判断和解释，不擅长稳定手算、格式校验、批量统计。

### 为什么更简单机制不够

纯 JSON tool calling 不够表达复杂控制流：

- 不能自然表达循环和条件。
- 变量复用差。
- 批量比较繁琐。
- 数据结构操作容易交回 LLM 手算。

但完全开放代码执行也危险。因此 CodeAgent 需要 sandbox、allowlist、timeout、trace。

---

## 11. Trace / Harness / Eval：让 agent 自身可优化

### 理念

LangChain Open Deep Research、smolagents、ARIS 都重视 trace、benchmark、review state。

没有 trace，就无法回答：

- 哪些 query family 有效？
- 哪些 evidence 经常缺？
- 哪些 reviewer risk 反复出现？
- 哪些 idea 被重复生成？
- 哪个改动真的提升了结果？

### 技术框架

```text
RunTrace
  -> Harness
  -> Metrics
  -> MetaReview
  -> Skill / Prompt / Config patch
```

### 实现细节

`RunTrace`：

```json
{
  "run_id": "",
  "agent_version": "",
  "model": "",
  "tools": [],
  "input_artifacts": [],
  "output_artifacts": [],
  "steps": [],
  "errors": [],
  "token_cost": {},
  "wall_time": "",
  "verdict": ""
}
```

建议 Resmax 的 idea / experiment harness 指标：

- evidence support rate。
- unsupported claim rate。
- citation precision。
- coverage of negative evidence。
- novelty over nearest prior work。
- baseline adequacy。
- ablation completeness。
- feasibility score。
- reviewer attack survival rate。
- result-to-claim calibration。

### 补足的能力

这个机制补足的是 **系统自我改进能力**。

没有 harness，每次修改 skill 或 prompt 都只能凭感觉判断好坏。

### 为什么更简单机制不够

最终报告看起来好不够。

原因：

- 报告质量和 idea 质量不是一回事。
- citation 多和 citation 支持 claim 不是一回事。
- reviewer 打分和真实实验可行性不是一回事。
- 没有负样本，系统会重复生成已失败方向。

Trace / harness 让科研 agent 从“会说”变成“可评估”。

---

## 12. Human Gate 与安全边界

### 理念

Google AI Co-Scientist 明确是 scientist-in-the-loop；Sakana 也暴露了 LLM 写代码执行的安全风险。科研 agent 越强，越需要边界。

尤其 Resmax 当前目标不是：

```text
one command -> final paper
```

而是：

```text
autonomous survey
  -> evidence-backed ROI ranking
  -> idea tournament
  -> experiment planning
```

### 技术框架

```text
HumanGate
  at Round 1 subdirection selection
  at focused evidence expansion
  at idea tournament winner
  at experiment execution
  at claim publication
```

### 实现细节

必须有 human gate 的地方：

- 从 broad survey 进入 focused full-text。
- 从 gap map 进入 idea tournament。
- 从 idea winner 进入实验计划。
- 从实验计划进入真实执行。
- 从结果进入论文 claim。

执行安全：

- planning agent 默认 read-only。
- execution agent narrow write scope。
- 命令 allowlist。
- sandbox / timeout / network policy。
- artifact hash / manifest。
- 不允许 agent 自行扩大预算或延长超时。

### 补足的能力

这个机制补足的是 **目标校准与风险控制能力**。

科研方向选择和实验投入本质是资源分配，不应完全交给自动系统。

### 为什么更简单机制不够

“让 agent 自己判断是否继续”不够。

原因：

- agent 会被局部进展诱导继续投入。
- 自动 reviewer 可能共同偏差。
- 高成本实验的机会成本很高。
- 失败或弱结果可能被包装成可发表叙事。

Human gate 不是降低自动化，而是把自动化用在最有杠杆的位置。

---

# 底层原理总结

下面是不同项目机制背后的共同底层原理。

## 原理 1：科研 agent 的核心对象不是文本，而是状态

优秀项目都会把中间状态文件化或结构化：

- Deep Research 的 plan、sources、activity history。
- LangChain 的 research brief、compressed findings。
- PaperQA2 / OpenScholar 的 evidence 与 citation。
- ARIS 的 review state、research contract。
- Google Co-Scientist 的 tournament state。
- Sakana 的 experiment node。

为什么要这样做：

- 长任务会压缩上下文。
- 科研判断需要复核。
- 多 agent 需要共享同一个事实状态。
- 失败经验要沉淀。

更简单机制为什么不行：

- 对话上下文不可校验、不可 diff、不可恢复。
- 一次性总结会丢掉失败路径和 raw reviewer objection。
- 没有状态，系统无法累积科研记忆。

## 原理 2：生成前先收缩信息分布

强项目都不是直接生成：

```text
prompt -> idea
```

而是：

```text
source policy -> evidence -> claim graph -> gap -> idea
```

为什么要这样做：

- 模型内部知识不够新。
- 前沿 idea 依赖近两年证据。
- 科研质量取决于输入证据的精度和覆盖。

更简单机制为什么不行：

- brainstorming 会产生语义合理但已被做过的 idea。
- web search summary 会产生看似全面但不可复现实验。
- citation trace 不等于 citation 支持 claim。

## 原理 3：新颖性来自张力，不来自随机组合

真正有价值的 idea 多来自：

- claim contradiction。
- unexplained observation。
- shared untested assumption。
- cross-domain bridge。
- benchmark blind spot。
- negative result memory。

为什么要这样做：

- 科研创新本质是解释力、预测力或实验可裁决性提升。
- 张力位置天然包含 reviewer interest。

更简单机制为什么不行：

- 随机组合模块容易变成 engineering novelty。
- “没人做过”不等于“值得做”。
- future work 复述很容易落入低 ROI 方向。

## 原理 4：前沿 idea 不能单点打分，要相对竞争

Google Co-Scientist、ARIS、Sakana 都引入了某种 tournament / review / archive。

为什么要这样做：

- frontier idea 没有稳定 ground truth。
- 绝对分数校准差。
- 近似 idea 需要相互比较才能看出真实差异。
- critique 需要转化成 evolution，而不是停在批评。

更简单机制为什么不行：

- 一个 rubric 分数会奖励表达完整的 idea。
- 同模型自评会保留共同盲区。
- 不保留 lineage 就无法判断是否 drift。

## 原理 5：实验计划服务于 claim，不服务于完整性

ARIS、Sakana、Google Co-Scientist 都把 experiment 和 claim 绑定。

为什么要这样做：

- 顶会 reviewer 关心的是 claim 是否被证明。
- 实验资源有限。
- 每个实验都应改变某个信念。

更简单机制为什么不行：

- benchmark wishlist 会堆实验但不支撑核心贡献。
- 没有 anti-claim 就无法排除替代解释。
- 没有 failure interpretation，失败不能指导下一步。

## 原理 6：LLM 做判断，代码做确定性处理

smolagents 和 LangChain 的启发是：不要让 LLM 手算、去重、汇总、校验。

为什么要这样做：

- 科研 artifact 很多是表格、指标、schema、trace。
- 这些部分需要稳定、可复现。

更简单机制为什么不行：

- 纯自然语言 agent 容易产生格式漂移。
- 手算统计会出错。
- 复杂 artifact 无法可靠 diff 和 validate。

## 原理 7：小成本 empirical gate 比大叙事更可靠

ARIS 的 pilot、Sakana 的 staged runs、Google 的 low-cost viability checkpoint 都说明：早期小实验非常重要。

为什么要这样做：

- idea 早期最大风险是不可行。
- 理论吸引力不能替代 empirical signal。
- 小实验能快速筛掉死路。

更简单机制为什么不行：

- 只做文献评审无法发现实现难度。
- 直接大实验成本高，且容易在错误方向上局部优化。
- reviewer 说“有潜力”不等于实验会跑通。

## 原理 8：负记忆和失败路径是一等资产

ARIS 的 research wiki、Google 的 meta-review failure pattern、Sakana 的 idea archive 都在保存失败信息。

为什么要这样做：

- 科研中失败路径比成功摘要更稀缺。
- 未发表负结果难以从公开文献获得。
- agent 容易重复生成语义上诱人的失败方向。

更简单机制为什么不行：

- 最终报告通常只写成功路径。
- 对话记忆会被压缩或丢失。
- 没有 negative memory，系统不会真正学习。

## 原理 9：人类 gate 是资源决策，不是人工打断

优秀系统不是全自动到底，而是在高杠杆点保留人类决策。

为什么要这样做：

- 方向选择是机会成本问题。
- 实验投入是资源分配问题。
- 论文 claim 是声誉风险问题。

更简单机制为什么不行：

- 让 agent 自己继续，容易被局部正反馈诱导。
- 自动 reviewer 可能共同偏差。
- 高成本实验不能只靠语言判断触发。

---

# 面向 Resmax 的最低可执行组合

不建议一开始复制任何完整框架。Resmax 最短路径是吸收机制，保留本地数据优势。

最低组合：

```text
ResearchBrief
  + SourcePolicy
  + EvidenceCard
  + ClaimGraph
  + Gap / Contradiction Map
  + Idea Tournament
  + Claim-Driven ExperimentPlan
  + Result-to-Claim placeholder
  + Negative Memory writeback
```

建议优先级：

1. `P0`：先定义 schema 和 validator，禁止自由文本报告成为唯一产物。
2. `P1`：在 `resmax-survey` 输出 `EvidenceCard` 与 `ClaimGraph`。
3. `P2`：实现 gap / contradiction mining，作为 idea 生成输入。
4. `P3`：实现 proximity-based idea tournament 和 cross-model reviewer。
5. `P4`：实现 claim-driven experiment plan，不急于自动执行实验。
6. `P5`：等 plan 质量可评估后，再引入 Sakana 式 experiment node tree。

一句话总结：

```text
Resmax 最强科研 agent 不应是更大的聊天机器人，
而应是一个证据状态机：
用文献证据发现张力，
用 tournament 选择假设，
用 claim-driven protocol 规划实验，
用小成本 gate 和负记忆持续校准。
```

