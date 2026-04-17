# CVPR Venue Playbook

## Primary Source

- CVPR 使用 CVF Open Access：`https://openaccess.thecvf.com/CVPR{YEAR}?day=all`
- 可批量获取字段：title, authors, pdf_link
- Parser: `cvpr_openaccess_html`
- 无 abstract，需通过 enrich 流程补全

## Abstract Enrichment

- CVF 页面不提供摘要，需依赖 enrich 流程（S2 batch → 多源 fallback → web search 兜底）
- CVPR 论文通常在 arXiv 上有预印本，S2 batch 命中率较高

## Notes

- ICCV 也使用 CVF Open Access，结构相同，parser 通用（`cvpr_openaccess_html`）
- GitHub 社区仓库（搜索 "CVPR{YEAR} accepted"）可作为辅助验证源

## Parser Versions Used

| Year | Parser | Notes |
|------|--------|-------|
| 2024 | `cvpr_openaccess_html` | |
| 2025 | `cvpr_openaccess_html` | |
| 2026 | `virtual_conference_json` | First year with virtual JSON; has abstracts |

## Lessons Learned

- Starting with CVPR 2026, the EventHosts virtual conference platform (same as ICLR/NeurIPS/ICML) provides a JSON endpoint: `https://cvpr.thecvf.com/static/virtual/data/cvpr-{year}-orals-posters.json`
- This JSON includes abstracts, which CVF OpenAccess does NOT provide — making it the preferred primary source when available
- The JSON becomes available after decisions are released (Feb/Mar), well before the conference and before CVF OpenAccess goes live
- The `virtual_conference_json` parser handles this format (shared with ICLR/NeurIPS/ICML)
- OpenReview API is locked for CVPR (403 Forbidden), unlike ICLR which exposes submissions publicly
- CVPR 2026 introduced a Findings track — the JSON may include both main conference and findings papers
- Decision values: `Accept (Oral)`, `Accept (Highlight)`, `Accept (Poster)`

## Updated Source Priority

1. Virtual Conference JSON (has abstract, available pre-conference) — preferred for 2026+
2. CVF OpenAccess (no abstract, available around/after conference) — used for 2024-2025
