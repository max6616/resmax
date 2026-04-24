# TPAMI Venue Playbook

## 基本信息

- 全称: IEEE Transactions on Pattern Analysis and Machine Intelligence
- 出版商: IEEE Computer Society
- ISSN: 0162-8828 (print), 1939-3539 (online)
- 类型: 期刊（月刊）
- DBLP key: journals/pami
- OpenAlex source ID: S199944782

## 数据源

- Primary: OpenAlex API (`openalex_works` parser)
- OpenAlex 提供完整摘要（abstract_inverted_index 格式）
- 每年约 676-778 篇论文
- Cursor paging，每页 200 条，通常 4 页即可拉完一年

## 摘要获取

OpenAlex 直接提供，无需额外补全。

## 评审数据

不公开。标记 `review_available=no`。

## 已知经验

- OpenAlex 的 DOI 格式为 `https://doi.org/10.1109/TPAMI.xxxx.xxxxx`，需要去掉前缀存储
- 2024 年约 676 篇，2023 年约 1041 篇（波动较大）
- OpenAlex 新论文有 1-2 周延迟
