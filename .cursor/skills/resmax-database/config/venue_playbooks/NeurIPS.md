# NeurIPS Venue Playbook

## Primary Source

- NeurIPS 使用 virtual conference 平台，提供结构化 JSON：`https://neurips.cc/static/virtual/data/neurips-{YEAR}-orals-posters.json`
- JSON 包含完整字段：title, authors, abstract, decision, topic, poster_url
- Parser: `virtual_conference_json`
- 摘要直接从主数据源获取，通常不需要 enrich 流程

## Auxiliary Sources

- Proceedings 页面（HTML）：title, authors, paper_link — 可作为 fallback（注意：新年份可能 404）
- Virtual HTML 页面：JS 渲染，仅 title — 不推荐

## Parser Versions Used

| Year | Parser | URL Pattern | Entry Count |
|------|--------|-------------|-------------|
| 2024 | `virtual_conference_json` | neurips-2024-orals-posters.json | 4610 |
| 2025 | `virtual_conference_json` | neurips-2025-orals-posters.json | 6002 |
