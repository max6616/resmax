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
