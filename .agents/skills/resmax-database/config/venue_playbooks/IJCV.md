# IJCV Venue Playbook

## 基本信息

- 全称: International Journal of Computer Vision
- 出版商: Springer
- ISSN: 0920-5691 (print), 1573-1405 (online)
- 类型: 期刊
- DBLP key: journals/ijcv
- OpenAlex source ID: S25538012

## 数据源

- Primary: OpenAlex API (`openalex_works` parser)
- 每年约 356 篇论文

## 摘要获取

OpenAlex 对 Springer 期刊不提供摘要。需要通过 `enrich_abstracts_fallback.py` 补全（CrossRef → S2 → arXiv → Web Search 链路）。

## 评审数据

不公开。标记 `review_available=no`。

## 已知经验

- Springer 期刊在 OpenAlex 上无 abstract_inverted_index，这是 Springer 的数据政策限制
- 可通过 DOI 从 Springer 网页爬取摘要作为备选方案
- Springer Nature API 需要申请 key，暂未使用
