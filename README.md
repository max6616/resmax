# Resmax

面向 AI agent 的自动化科研文献基础设施。将科研流程中可标准化的环节封装为可复用的 skill，使 agent 能够高质量地完成文献层面的基础工作。

## 项目结构

```
resmax/
├── .resmax/                        ← 核心技能体系
│   ├── build-literature-base/      ← Skill 1: 基础文献库构建（抓取、补摘要、embedding）
│   └── search-literature/          ← Skill 2: 方向级相关文献检索与评分
├── paper_database/                 ← 全量文献索引 & embedding 缓存（gitignored）
├── literature_research/            ← 各研究方向的检索结果
├── _archive_*/                     ← 历史版本归档
└── PROFILE.md                      ← Agent 上下文（设备信息、环境配置）
```

## 当前技能

| Skill | 功能 | 触发词 |
|-------|------|--------|
| `build-literature-base` | 从 AI 顶会抓取 accepted list，补全摘要，构建 embedding 缓存 | "建文献库"、"更新accepted"、"补摘要" |
| `search-literature` | 从基础文献库中为指定研究方向检索、评分、排序相关论文 | "检索文献"、"文献调研"、"找相关论文" |

## 数据流

```
数据源 → build-literature-base → paper_database/
                                    ├── accepted_index.csv
                                    └── embedding_cache/
                                            ↓
研究方向 → search-literature    → literature_research/<方向>/
                                    ├── research_index.csv
                                    ├── literature_list.md
                                    └── filter_log.md
```

## License

Private repository. All rights reserved.
