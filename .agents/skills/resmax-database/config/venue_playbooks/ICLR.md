# ICLR Venue Playbook

## Primary Source

- ICLR 使用 virtual conference 平台，提供结构化 JSON：`https://iclr.cc/static/virtual/data/iclr-{YEAR}-orals-posters.json`
- JSON 包含完整字段：title, authors, abstract, decision, topic, poster_url
- Parser: `virtual_conference_json`
- 摘要直接从主数据源获取，通常不需要 enrich 流程

## Auxiliary Sources

- Proceedings 页面（HTML）：title, authors, paper_link — 可作为 fallback
- Virtual HTML 页面：JS 渲染，仅 title — 不推荐

## Review Data

- **Reviews public**: Yes — all submissions (accepted + rejected), fully open since inception
- **Platform**: OpenReview v2
- **API group**: `ICLR.cc/{YEAR}/Conference`
- **Review invitation**: `ICLR.cc/{YEAR}/Conference/Submission{number}/-/Official_Review`
- **Score scale**: 1-10 (overall rating) + confidence 1-5
- **Reviewers/paper**: typically 4 (3 auto-assigned + 1 manual by AC)
- **Data includes**: reviews, author rebuttals, reviewer-author discussion, meta-reviews, decision
- ICLR is the gold standard for review mining — everything is public for all papers

## Parser Versions Used

| Year | Parser | URL Pattern | Entry Count |
|------|--------|-------------|-------------|
| 2024 | `virtual_conference_json` | iclr-2024-orals-posters.json | 2382 |
| 2025 | `virtual_conference_json` | iclr-2025-orals-posters.json | 4040 |
| 2026 | `virtual_conference_json` | iclr-2026-orals-posters.json | 5695 |

## Lessons Learned

- Virtual conference JSON can be available BEFORE the conference takes place (confirmed for 2026: decisions out, conference not held, JSON already live)
- OpenReview API v2 venue strings: `ICLR {YEAR} Oral` / `ICLR {YEAR} Poster` (capitalized decision type)
- Virtual JSON `decision` field values: `Accept (Oral)` and `Accept (Poster)`
- Paper count trend: 2024=2382, 2025=4040, 2026=5695 (~40-70% YoY growth)
- openreview_forum_id coverage from virtual JSON: ~98-99% (some papers in CVF OpenAccess but not in virtual JSON lack forum_id)
