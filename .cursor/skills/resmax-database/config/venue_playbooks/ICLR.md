# ICLR Venue Playbook

## Primary Source

- ICLR 使用 virtual conference 平台，提供结构化 JSON：`https://iclr.cc/static/virtual/data/iclr-{YEAR}-orals-posters.json`
- JSON 包含完整字段：title, authors, abstract, decision, topic, poster_url
- Parser: `virtual_conference_json`
- 摘要直接从主数据源获取，通常不需要 enrich 流程

## Auxiliary Sources

- Proceedings 页面（HTML）：title, authors, paper_link — 可作为 fallback
- Virtual HTML 页面：JS 渲染，仅 title — 不推荐

## Parser Versions Used

| Year | Parser | URL Pattern | Entry Count |
|------|--------|-------------|-------------|
| 2024 | `virtual_conference_json` | iclr-2024-orals-posters.json | 2382 |
| 2025 | `virtual_conference_json` | iclr-2025-orals-posters.json | 4040 |
