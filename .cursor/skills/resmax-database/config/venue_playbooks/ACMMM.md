# ACMMM (ACM Multimedia) Venue Playbook

## Site Architecture

- ACM MM 2023 起官网使用 Vue SPA（webpack 构建），accepted list 页面内容嵌入在 JS chunk 中，静态 HTML 抓取无法获得正文。
- `survey_sources.py` 的自动探测会返回 HTTP 200 并推荐 `acmmm_html` parser，但这是误判——页面 body 为空壳，数据在 JS 中。
- 正确做法：使用 `acmmm_vue_accepted` parser，从首页解析 `app.[hash].js` 找到路由对应的 chunk 哈希，下载 chunk 后从 `contents:[...]` 中成对提取 `paperTitle` / `paperAuthor`。
- `parser_args` 需填入目标 chunk 名（每年不同，需人工或 subagent 检查 app.js 确认）。

## Abstract Availability

- Accepted list 页面只有 title 和 authors，没有 abstract。
- 摘要需通过 enrich 流程补全，主要来源：
  1. Semantic Scholar batch API（通过标题匹配，因无 arXiv/DOI/OpenReview ID）
  2. 多源 fallback（ACM DL、OpenAlex、CrossRef、arXiv）
  3. Web search 兜底（ACM DOI 页面、arXiv abs 页面）

## Known Pitfalls

- 录用列表标题可能与 ACM DL proceedings 标题措辞不同（如 "Open-World" vs "Out-of-Distribution"），匹配摘要时以 DOI / arXiv / 官方代码库 citation 为准，避免张冠李戴。
- S2 batch API 对大批量请求容易 429，fallback 脚本会自动处理。
- 部分论文在 OpenAlex 中无 `abstract_inverted_index`，需进一步 fallback 到 web search。

## Parser Versions Used

| Year | Parser | Notes |
|------|--------|-------|
| 2024 | `acmmm_vue_accepted` | chunk name in `parser_args` |
| 2025 | `acmmm_html` | Used fixture (offline HTML snapshot) |
