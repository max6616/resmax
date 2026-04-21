# JMLR Venue Playbook

## 基本信息

- 全称: Journal of Machine Learning Research
- 出版商: JMLR Inc.（完全开放获取）
- ISSN: 1532-4435 (print), 1533-7928 (online)
- 类型: 期刊
- DBLP key: journals/jmlr
- OpenAlex source ID: S118988714（数据严重缺失，不可用）

## 数据源

- Primary: JMLR 官网 HTML (`jmlr_html` parser)
- URL 模式: `https://jmlr.org/papers/v{N}/`
- Volume-年份映射: v25=2024, v26=2025, v27=2026
- 每年约 300+ 篇论文

## HTML 结构

```html
<dl>
<dt>Title</dt>
<dd><b><i>Author1, Author2</i></b>; (N):pages, year.
<br>[<a href='abs_url'>abs</a>][<a href='pdf_url'>pdf</a>][<a href='bib_url'>bib</a>]
</dl>
```

## 摘要获取

官网有 abs 页面链接（`/papers/v{N}/{paper_id}.html`），可通过 fallback 脚本补全。JMLR 是开放获取，无访问限制。

## 评审数据

不公开。标记 `review_available=no`。

## 已知经验

- JMLR 不使用 DOI，CrossRef 无数据
- OpenAlex 上 JMLR 数据严重缺失（仅 1411 篇，最新到 2008 年），不可用
- 官网 HTML 结构多年稳定，解析可靠
- 部分论文有 `[code]` 链接，parser 已提取
