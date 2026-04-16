# .resmax — 自动化科研文献基础设施

## 定位

`.resmax` 是一套面向 AI agent 的自动化科研技能体系。目标是将科研流程中可标准化的环节（文献收集、筛选、调研）封装为可复用、可组合的 skill，使 agent 能够以接近人类研究者的质量完成文献层面的基础工作。

当前覆盖两个核心能力：**基础文献库构建** 和 **方向级相关文献检索**。后续将沿科研流程向下游扩展（实验设计、论文写作等）。

## 架构总览

```
.resmax/
├── README.md                       ← 本文件：全局架构说明
├── build-literature-base/          ← Skill 1: 基础文献库构建
│   ├── SKILL.md                    ← 技能定义与执行流程
│   ├── config/                     ← 配置（数据源注册表、embedding 参数）
│   ├── scripts/                    ← 自动化脚本（抓取、补全、缓存）
│   └── fixtures/                   ← 离线 HTML/JSON 快照（用于无法直接抓取的源）
└── search-literature/              ← Skill 2: 方向级相关文献检索
    ├── SKILL.md                    ← 技能定义与执行流程
    ├── config/                     ← 配置（检索参数、评分标准）
    └── scripts/                    ← 检索与评分脚本
```

## 数据流

两个 skill 通过共享的文件系统数据进行衔接，无运行时耦合：

```
                    build-literature-base
                    ┌─────────────────────┐
                    │  抓取 → 补摘要 →      │   paper_database/
           数据源 ──→│  构建 embedding 缓存 │──→  ├── accepted_index.csv
                    └─────────────────────┘     └── embedding_cache/
                                                          │
                    search-literature                     │
                    ┌─────────────────────┐               │
  研究方向 +         │  关键词检索 + 语义检索  │←──────────────┘
  关键词          ──→│  → 合并 → 评分 → 排序 │──→  literature_research/<方向>/
                    └─────────────────────┘      ├── research_index.csv
                                                 ├── literature_list.md
                                                 └── filter_log.md
```

## 数据目录约定

| 目录 | 归属 | 说明 |
|------|------|------|
| `paper_database/` | build-literature-base 产出 | 全量基础文献索引、embedding 缓存、数据源调研报告 |
| `literature_research/<方向>/` | search-literature 产出 | 方向级检索结果、评分文献列表、筛选日志 |

数据 schema 详见各 skill 的 SKILL.md。

## 设计原则

1. **CSV 为唯一权威索引** — 不维护冗余 Markdown 真源，所有结构化数据以 CSV 为准
2. **批量优先，逐篇兜底** — 全库级操作（~50000 篇）只做批量处理；逐篇操作仅用于筛选后的小规模候选集（≤100 篇）
3. **Skill 独立** — 每个 skill 自包含（脚本、配置、文档），无运行时耦合，仅通过文件系统共享数据
4. **脚本开箱即用** — 所有脚本均提供完整 CLI 参数说明，无需阅读源码即可使用
5. **增量更新** — 所有环节支持增量操作，避免重复计算

## 技能索引

| Skill | 触发词 | 说明 |
|-------|--------|------|
| [build-literature-base](build-literature-base/SKILL.md) | "建文献库"、"更新accepted"、"补摘要" | 从 AI 顶会抓取 accepted list，补全摘要，构建 embedding 缓存 |
| [search-literature](search-literature/SKILL.md) | "检索文献"、"文献调研"、"找相关论文" | 从基础文献库中为指定研究方向检索、评分、排序相关论文 |

## 扩展规划

当前体系覆盖科研流程的"文献基础"层。后续可沿以下方向扩展：

- **深度阅读**：对筛选出的高相关论文进行结构化精读（方法提取、实验对比）
- **研究定位**：基于文献调研结果，辅助确定研究 gap 和创新点
- **实验设计**：从文献中提取 baseline 配置，生成实验方案
- **论文写作**：基于文献调研和实验结果，辅助 Related Work 等章节撰写
