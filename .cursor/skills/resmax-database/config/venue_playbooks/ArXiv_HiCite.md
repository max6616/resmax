# ArXiv_HiCite Venue Playbook

## 基本信息

- 全称: 高引用 arXiv 预印本（非同行评审）
- 数据源: Semantic Scholar Bulk Search API
- 类型: 非同行评审信源
- 筛选条件: CS 领域 + 有 arXiv ID + 动态引用阈值

## 数据源

- Primary: S2 Bulk Search API (`s2_bulk_papers` parser)
- API 端点: `https://api.semanticscholar.org/graph/v1/paper/search/bulk`
- 认证: 可选 `S2_API_KEY` 环境变量（无 key 时 100 req/5min）
- 分页: cursor-based，每页 1000 篇

## 动态引用阈值

`minCitationCount=auto` 时按公式 `max(10, 100 × 月龄 / 24)` 计算：

| 论文年份 | 月龄（2026-04） | 阈值 | 典型入库量 |
|---------|----------------|------|-----------|
| 2024 | ~28 | 116 | ~860 |
| 2025 | ~16 | 66 | ~435 |
| 2026 | ~4 | 16 | ~52 |

阈值含义：等价于"2 年积累 100 引用"的论文值得入库。随时间推移，同一年份的阈值会自动升高。

## 增量运行

```bash
python3 build_accepted_index.py --conf-years ArXiv_HiCite_2025
# 或一次跑全部年份
python3 build_accepted_index.py --conf-years ArXiv_HiCite_2024,ArXiv_HiCite_2025,ArXiv_HiCite_2026
```

耗时：每年 ~10-60 秒（取决于结果量和分页数）。

## 去重

- Parser 阶段：仅保留有 `externalIds.ArXiv` 的论文（过滤掉已发表的期刊论文）
- 入库阶段：`dedup_against_peer_reviewed` 按 arxiv_id + normalized title 移除已在同行评审 venue 中的论文
- 跨信源：ArXiv_HiCite 优先于 HF_DailyPapers（同一篇论文保留 ArXiv_HiCite 版本）

## 已知经验

- S2 返回的论文中约 30-40% 有 arXiv ID，其余是已发表的期刊论文（有 DOI 无 arXiv ID），被 parser 正确过滤
- `acceptance_type` 固定为 `High-Impact Preprint`
- `extras.citation_count` 保存引用数，可用于下游排序
- S2 API 对 2026 年部分月份数据可能不完整（索引延迟）
