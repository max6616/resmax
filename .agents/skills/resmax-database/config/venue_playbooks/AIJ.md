# AIJ Venue Playbook

## 基本信息

- 全称: Artificial Intelligence
- 出版商: Elsevier
- ISSN: 0004-3702 (print), 1872-7921 (online)
- 类型: 期刊
- DBLP key: journals/ai
- OpenAlex source ID: S196139623

## 数据源

- Primary: OpenAlex API (`openalex_works` parser)
- OpenAlex 提供摘要（abstract_inverted_index 格式）
- 每年约 132 篇论文（体量较小）

## 摘要获取

OpenAlex 直接提供，覆盖率约 80%+。少量缺失可通过 fallback 补全。

## 评审数据

不公开。标记 `review_available=no`。

## 已知经验

- Elsevier 期刊在 OpenAlex 上大部分有摘要，但偶有缺失
- DOI 格式: `https://doi.org/10.1016/j.artint.xxxx.xxxxx`
