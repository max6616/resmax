# resmax：AI 领域全流程自动化科研系统 — 项目汇报大纲

## 1. 项目总览

### 1.1 目标

构建 CS/AI 领域全流程全自动科研系统，覆盖：

```
文献调研 → 讨论idea → 设计实验 → 自主跑实验+监控迭代
→ 收集实验数据 → 图表生成 → 模型结构图绘制 → 论文撰写 → 模拟审稿
```

当前进度：**文献调研部分已完成**（database → embedding → survey 三级流水线），本次汇报聚焦于此。

### 1.2 系统架构（三个独立 skill，文件系统耦合）

```
resmax-database          resmax-embedding          resmax-survey
(文献索引构建)     →     (向量缓存构建)      →     (方向级文献检索)
   ↓                        ↓                        ↓
accepted_index.csv    embedding_cache.npz      literature_list.md
   (CSV 为唯一权威索引，skill 间零运行时耦合)
```

---

## 2. 现有自动化科研项目的文献能力分析

### 2.1 主流项目对比

> 数据来源：[Awesome-Autonomous-Research-Agent](https://github.com/LTzycLT/Awesome-Autonomous-Research-Agent)

| 项目 | Stars | 文献数据源 | 检索方法 | 是否自建数据库 |
|------|-------|-----------|---------|--------------|
| autoresearch (Karpathy) | ~74.7k | 无 | 无文献检索能力 | 无 |
| AI-Scientist v2 (Sakana) | ~5.7k | S2 API | 关键词搜索 | 否，实时查询 |
| PaperQA2 (FutureHouse) | ~8.4k | Crossref + S2 + 本地 PDF | BM25 + LLM re-rank | 是，本地 PDF 索引 |
| OpenScholar (AI2/UW) | ~1.4k | S2 peS2o 45M 论文 | 双路检索(dense+BM25) + self-feedback | 是，预建 45M datastore |
| ResearchAgent (KAIST) | ~31 | S2 Graph API | 引用图遍历 | 否 |
| AutoResearchClaw (AIMING) | ~3.5k | arXiv + S2 | 关键词搜索 | 否 |
| EvoScientist (Huawei) | ~4.5k | Web search + S2 | 多 agent 分工 | 否 |

> 来源：各项目 GitHub 仓库及论文。AI-Scientist: [arXiv:2408.06292](https://arxiv.org/abs/2408.06292)；PaperQA2: [paper.wikicrow.ai](https://paper.wikicrow.ai)；OpenScholar: [arXiv:2411.14199](https://arxiv.org/abs/2411.14199)；ResearchAgent: [arXiv:2404.07738](https://arxiv.org/abs/2404.07738)

### 2.2 关键发现

- **S2 是事实上的标准数据源** — 几乎所有项目都依赖 Semantic Scholar API
- **多数项目不自建数据库** — 实时查询 S2，受限于 S2 的数据质量和覆盖范围
- **review 数据几乎无人利用** — AI-Scientist 有自动 review agent，但用于评估生成的论文，不用于文献筛选
- **agent 审查相关性是新趋势** — OpenScholar(self-feedback)、PaperQA2(agentic RAG)、ResearchAgent(5维多agent评审)

→ 问题：**如果底层数据源（S2）本身有缺陷，所有依赖它的项目都会受影响**

---

## 3. Semantic Scholar 的数据质量问题

### 3.1 实时性不足

S2 对最新会议的收录严重滞后：

| 会议 | 状态 | S2 收录数 | 说明 |
|------|------|----------|------|
| ICLR 2026 | 录用结果已公布 | **10** | 几乎为零 |
| CVPR 2026 | 录用结果已公布 | **0** | 完全未收录 |
| ICML 2025 | 已举办 | 2,711 | 部分收录，31.5% 缺摘要 |

> 数据获取时间：2026-04-20，通过 S2 Bulk Search API 查询

对比 resmax：ICLR 2026 已收录 5,471 篇，CVPR 2026 已收录 4,071 篇。

### 3.2 噪声严重 — 以 AAAI 2025 为例

S2 标记为 "AAAI 2025" 的论文共 3,864 篇，实际构成：

```
S2 "AAAI 2025" = 3,864 篇
├── 真正的 AAAI 2025 论文 (v39 DOI)     1,904 篇  ← 可信
├── 实际是 AAAI 2026 的论文 (v40 DOI)     178 篇  ← 年份错误
└── 仅有 arXiv 预印本 DOI               1,782 篇  ← 误标为会议论文
```

**arXiv 预印本被误标为 AAAI 会议论文的样例：**

| 论文标题 | DOI | DBLP 分类 | S2 标注 |
|---------|-----|----------|--------|
| Interactive Evaluation of LLMs for Multi-Requirement SE Tasks | 10.48550/arXiv.2508.18905 | journals/corr (预印本) | AAAI Conference |
| PathRAG: Pruning Graph-based RAG with Relational Paths | 10.48550/arXiv.2502.14902 | journals/corr (预印本) | AAAI Conference |
| Conformal Constrained Policy Optimization for Cost-Effective LLM Agents | 10.48550/arXiv.2511.11828 | journals/corr (预印本) | AAAI Conference |

**AAAI 2026 论文被错误归入 2025 的样例：**

| 论文标题 | DOI | 实际所属 | S2 标注年份 |
|---------|-----|---------|-----------|
| Symbolic Planning and MAPF in Dense Environments | 10.1609/aaai.**v40**i35.40183 | AAAI-40 (2026) | 2025 |
| iSeal: Encrypted Fingerprinting for LLM Ownership | 10.1609/aaai.**v40**i42.40909 | AAAI-40 (2026) | 2025 |

### 3.3 摘要覆盖不全

S2 各会议摘要覆盖率（采样前 1000 篇）：

| 会议 | 年份 | 有摘要 | 覆盖率 |
|------|------|--------|--------|
| AAAI | 2025 | 999 | 99.9% |
| ACL | 2024 | 969 | 96.9% |
| NeurIPS | 2024 | 960 | 96.0% |
| CVPR | 2024 | 837 | **83.7%** |
| ICLR | 2024 | 832 | **83.2%** |
| ICML | 2024 | 791 | **79.1%** |
| ICML | 2025 | 685 | **68.5%** |

→ ICML 2024 约 1/5 论文无摘要，ICML 2025 约 1/3 无摘要

### 3.4 摘要缺失对向量检索的影响

S2 的 embedding 使用 **SPECTER2** 模型：
- 架构：SciBERT-base（BERT-base，~110M 参数，768 维）
- 输入：**title + abstract**（512 token 上限）
- 当 abstract 缺失时，仅用 title 编码 → embedding 质量严重退化

> 来源：Singh et al., "SciRepEval: A Multi-Format Benchmark for Scientific Document Representations", EMNLP 2023. [arXiv:2211.13308](https://arxiv.org/abs/2211.13308)；[HuggingFace: allenai/specter2_base](https://huggingface.co/allenai/specter2_base)

### 3.5 关于 arXiv

arXiv 论文未经同行评审，不纳入 resmax 数据库。目标：**获取尽可能纯净的顶级、前沿、主线相关论文**。

---

## 4. resmax-database：自建高质量文献索引

### 4.1 覆盖范围

当前收录 ~60,000 篇论文，覆盖 13 个 venue × 多年份：

- ML：ICLR (2024-2026), ICML (2024-2025), NeurIPS (2024-2025)
- CV：CVPR (2024-2026), ECCV (2024), ICCV (2025)
- NLP：ACL (2024-2025), EMNLP (2024)
- AI 综合：AAAI (2024-2025), ACMMM (2024-2025), KDD (2024-2025)
- 图形学：SIGGRAPH (2025), SIGGRAPH Asia (2025)
- 期刊：TPAMI, IJCV, JMLR, AIJ, TNNLS (2024-2026)

### 4.2 数据源体系

```
16 种 parser 覆盖不同数据源格式：
├── virtual_conference_json    (ICLR/NeurIPS/ICML/CVPR — 含 oral/poster 等级)
├── openreview_api_v2          (OpenReview 直接 API)
├── cvpr_openaccess_html       (CVF Open Access)
├── aaai_ojs_html              (AAAI OJS 多 issue 聚合)
├── acl_anthology_html         (ACL Anthology)
├── acmmm_vue_accepted         (ACM MM Vue SPA 解析)
├── kesen_siggraph_html        (Ke-Sen Huang SIGGRAPH 页面)
├── openalex_works             (期刊论文 via OpenAlex API)
└── ...等 8 种其他 parser
```

每个 venue 有独立的 **Venue Playbook**（经验手册），记录跨年份通用的抓取经验、已知坑点、评审政策等。

### 4.3 三层摘要补全机制（核心设计亮点）

```
                    ┌─────────────────────────────────┐
                    │  Layer 1: 主数据源自带摘要        │
                    │  (OpenReview / Virtual Conf JSON) │
                    └──────────────┬──────────────────┘
                                   │ 仍有缺失？
                    ┌──────────────▼──────────────────┐
                    │  Layer 2: 批量 API 补全           │
                    │  S2 batch (500篇/请求)            │
                    │  → arXiv batch (80篇/请求)        │
                    └──────────────┬──────────────────┘
                                   │ 仍有缺失？
                    ┌──────────────▼──────────────────┐
                    │  Layer 3: 9源逐篇异步 fallback    │
                    │  CVF → AAAI OJS → ACM DL          │
                    │  → OpenAlex → CrossRef → S2       │
                    │  → arXiv → SerpAPI → Google Scholar│
                    │  (命中即停，异步并发)               │
                    └──────────────┬──────────────────┘
                                   │ 仍有缺失？(≤10篇)
                    ┌──────────────▼──────────────────┐
                    │  Layer 4: Agent web search 兜底   │
                    │  主agent/subagent 逐篇搜索补齐     │
                    └─────────────────────────────────┘

                    最终目标：摘要覆盖率 = 100%
```

### 4.4 元信息优势（vs S2 及其他项目）

| 维度 | S2 | 其他自动科研项目 | resmax |
|------|-----|----------------|--------|
| 摘要覆盖率 | 68-99%（会议依赖） | 受限于 S2 | **100%** |
| 审稿信息 | 无 | 无 | review/score/rebuttal/meta-review |
| 中稿等级 | 无 | 无 | Oral/Spotlight/Highlight/Poster |
| 实时性 | 滞后数月 | 受限于 S2 | 录用结果公布后即可收录 |
| 数据纯净度 | 含大量噪声 | 受限于 S2 | 仅收录 accepted papers |

### 4.5 审稿信息收录

通过 OpenReview API v2 批量拉取公开评审数据：

```json
// 每篇论文的评审详情 (paper_database/reviews/{conf_year}/{forum_id}.json)
{
  "reviews": [
    { "rating": 8, "confidence": 4, "strengths": "...", "weaknesses": "..." }
  ],
  "meta_review": { "recommendation": "Accept (Oral)" },
  "rebuttals": [{ "round": 1, "content": "..." }],
  "decision": "Accept (Oral)"
}
```

覆盖 venue：ICLR (1-10), NeurIPS (1-10 / 1-6), ICML (1-10)。不公开评审的 venue 标记为 `review_available=no`。

---

## 5. resmax-embedding：高精度向量缓存

### 5.1 模型对比

| | S2 (SPECTER2) | resmax |
|---|---|---|
| 模型 | SciBERT-base (~110M) | **Qwen3-Embedding-8B** (~8B) |
| 维度 | 768 | 全维度（可配置截断） |
| 输入 | title + abstract (512 token) | title + abstract（更长上下文） |
| 摘要依赖 | 缺摘要 → 仅 title → 质量退化 | **100% 摘要覆盖 → 无退化** |

> SPECTER2 来源同上。Qwen3-Embedding: [HuggingFace: Qwen/Qwen3-Embedding-8B](https://huggingface.co/Qwen/Qwen3-Embedding-8B)

### 5.2 工程实现

- INT8 量化加载（BitsAndBytes），~8GB/GPU
- 多 GPU 数据并行：N 卡 → N 倍吞吐，零通信开销
- 增量更新：已编码论文自动跳过
- 缓存格式：`.npz`（numpy compressed），纯 CPU 可加载

---

## 6. resmax-survey：方向级文献检索

### 6.1 检索流程

```
输入：研究方向描述 + 关键词列表
         │
    ┌────▼────┐     ┌─────▼─────┐
    │ 关键词匹配 │     │ 向量匹配   │     ← 双路检索
    │ (top-50)  │     │ (top-50)  │
    └────┬────┘     └─────┬─────┘
         │               │
    ┌────▼───────────────▼────┐
    │  合并去重 (标注来源)       │     ← keyword / embedding / both
    │  cap = 100               │
    └──────────┬──────────────┘
               │
    ┌──────────▼──────────────┐
    │  元信息补全               │     ← 确保每篇有摘要+PDF链接
    └──────────┬──────────────┘
               │
    ┌──────────▼──────────────┐
    │  Subagent 逐篇评分       │     ← 2层subagent架构
    │  S / A / B / C 四级       │        orchestrator → batch scorer
    └──────────┬──────────────┘
               │
    ┌──────────▼──────────────┐
    │  主 Agent 整体审核        │     ← 检查评分合理性
    └──────────┬──────────────┘
               │
    ┌──────────▼──────────────┐
    │  输出：带评分的文献列表     │     ← literature_list.md + CSV + log
    └─────────────────────────┘
```

### 6.2 双路检索设计

| 路径 | 方法 | 优势 | 劣势 |
|------|------|------|------|
| 关键词匹配 | title+abstract 子串匹配，按命中关键词数排序 | 精确术语命中，无漏检同名方法 | 无法捕获语义相似但用词不同的论文 |
| 向量匹配 | query embedding vs 缓存 cosine similarity | 语义泛化，捕获相关但用词不同的工作 | 可能引入主题相近但实际无关的噪声 |

合并时标注来源（keyword / embedding / both），both 优先排序 → 两路都命中的论文最可能相关。

### 6.3 Subagent 评分机制

```
主 Agent (调度器)
    │
    ▼
Orchestrator Subagent (单个)
    │  接收全部候选论文 + 研究方向
    │  内部分批（每批 ≤10 篇）
    ├──▶ Scorer Subagent #1  →  {paper_id, score, reason} × 10
    ├──▶ Scorer Subagent #2  →  {paper_id, score, reason} × 10
    └──▶ ...
    │
    ▼  汇总 → scores_raw.json
主 Agent
    │  审核评分合理性
    ▼
最终评分列表 (S/A/B/C)
```

评分标准：
- **S**：直接 baseline 或核心 related work
- **A**：方法/问题有显著重叠
- **B**：有一定关联，背景参考
- **C**：边缘相关

---

## 7. 后续规划（尚未实现）

### 7.1 深度文献分析

对 S/A 级论文进一步处理：
- 补充 PDF 全文、arXiv TeX 源码、PDF→Markdown 转换
- 结合 review 评价/打分、是否开源等，给出逐篇详细评价

评价维度：

```
方法创新程度 | 是否 SOTA | 是否能/值得复现 | 是否需作为 baseline
引用的 baseline / dataset / base model | 代码质量 | 实验规模
```

### 7.2 方向可行性评估

除了保证对研究现状的前沿全面认识，同时评估：

| 评估维度 | 目的 |
|---------|------|
| 算力需求 | 该方向典型实验需要多少 GPU·hours |
| 实验难度/周期 | 从复现到出结果的预期时间 |
| Benchmark 统一性 | 是否有公认 benchmark，数据是否易获取 |
| 方向热度趋势 | 近 2-3 年投稿量/引用量变化 |

→ 前半部分保证 resmax 提出的 idea **可靠且前沿**，后半部分保证 idea **可实现且周期可预期**。

### 7.3 完整科研流程

```
文献调研 (已完成)
    → 讨论 idea → 设计实验 → 自主跑实验+监控迭代
    → 收集实验数据 → 图表生成 → 模型结构图
    → 论文撰写 → 模拟审稿
```

---

## 附录：关键数据汇总

### A. resmax vs S2 论文数量对比（部分会议）

| 会议 | 年份 | resmax | S2 | 差异原因 |
|------|------|--------|-----|---------|
| ICLR | 2026 | 5,471 | 10 | S2 未收录 |
| CVPR | 2026 | 4,071 | 0 | S2 未收录 |
| ICML | 2025 | 3,339 | 2,712 | S2 部分收录 |
| AAAI | 2025 | 3,028 | 3,864* | *S2 含 1,782 篇 arXiv 误标 + 178 篇年份错误 |

### B. 技术栈

- 语言：Python 3
- Embedding：Qwen3-Embedding-8B (INT8)
- 向量计算：NumPy (CPU) / PyTorch (GPU encoding)
- Agent 框架：Cursor IDE agent + subagent 机制
- 数据格式：CSV (索引) + NPZ (向量) + JSON (评审详情)
