# AAAI Venue Playbook

## Platform

- AAAI 使用 OJS (Open Journal Systems) 平台，地址 `ojs.aaai.org`
- Proceedings 按 volume 组织：Vol. N = AAAI-YY，其中 N = year - 1986（如 Vol. 38 = AAAI-24，Vol. 39 = AAAI-25）
- 每个 volume 分多个 issue（通常 18-21 个），按 track 划分：Technical Tracks、Safe/Robust AI、Social Impact、IAAI、EAAI 等

## Primary Source

- Archive 页面：`https://ojs.aaai.org/index.php/AAAI/issue/archive`（分页，每页 25 条）
- Parser: `aaai_ojs_html`，kind: `aaai_ojs_multi_issue`
- `parser_args` 设为 `AAAI-YY`（两位数年份）以过滤正确 volume
- Parser 自动发现同 volume 下所有 issue

## Field Coverage

- Issue 页面：title, authors
- 单篇文章页面（`/article/view/{id}`）：abstract, PDF link, DOI
- OJS 抓取（`build_accepted_index.py`）只获取 title、authors、paper_link，不含 abstract/doi
- 摘要通过 enrich 流程补全：S2 batch 通常无效（缺 arXiv/DOI ID），fallback 的 `aaai_page` 源直接从 OJS 文章页面抓取，命中率 100%

## Parser Versions Used

| Year | Parser | parser_args | Notes |
|------|--------|-------------|-------|
| 2024 | `aaai_ojs_html` | `AAAI-24` | Vol. 38, 21 issues, ~2331 papers |
| 2025 | `aaai_ojs_html` | `AAAI-25` | Vol. 39 |
