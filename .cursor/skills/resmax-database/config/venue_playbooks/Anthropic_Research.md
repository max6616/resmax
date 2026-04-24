# Anthropic_Research Venue Playbook

## 基本信息

- 全称: Anthropic 研究博客 + Transformer Circuits Thread
- 数据源: anthropic.com/research sitemap 逐页抓取
- 类型: 非同行评审信源（公司研究报告）
- 覆盖内容: interpretability 研究（Circuits 系列）、alignment 研究、模型安全、经济影响报告等

## 数据源

- Primary: Anthropic sitemap scrape (`anthropic_research` parser)
- Sitemap: `https://www.anthropic.com/sitemap.xml`（约 109 个 /research/ URL）
- 认证: 无需 API key
- 抓取方式: 逐页 curl 抓取 HTML，提取 title / date / description / 链接

## 为什么需要单独爬取

Tier 1 信源（S2 高引用 + HF Daily Papers）对 Anthropic 覆盖率仅 **7.5%**。原因：
- 大量 interpretability 研究只发在 transformer-circuits.pub，不上 arXiv
- 经济影响报告、alignment 博客等不属于传统论文形态
- 这些内容对理解 LLM 内部机制和安全对齐有独特价值

## 增量运行

```bash
# 建议三年一起跑，利用缓存机制只爬一次 sitemap
python3 build_accepted_index.py --conf-years Anthropic_Research_2024,Anthropic_Research_2025,Anthropic_Research_2026
```

耗时：首次爬取 ~6 分钟（109 页 × ~3 秒/页），后续年份从内存缓存过滤，0 秒。

## 缓存机制

`source_registry.json` 中使用 `anthropic_sitemap_cached` kind：
- 第一个 conf_year 触发完整 sitemap 爬取，结果缓存在 `fetch_and_parse` 函数属性上
- 同一次 build 中后续 conf_year 直接从缓存按 year 过滤
- 如果只跑单个年份，也可改用 `anthropic_sitemap` kind（每次独立爬取）

## 链接提取

`paper_link` 字段按优先级提取：
1. `transformer-circuits.pub` 完整论文链接（如 Circuits Updates、Emotions 研究）
2. `arxiv.org` 论文链接（如 Alignment Faking、Constitutional AI）
3. `anthropic.com/research/` 博客页面（兜底）

## 字段覆盖率

| 字段 | 覆盖率 | 说明 |
|------|--------|------|
| title | 100% | 从 `<title>` 标签提取 |
| abstract_raw | 100% | 从 og:description 提取（博客摘要级别） |
| arxiv_id | ~47% | 仅有 arXiv 版本的论文 |
| paper_link | 100% | 按优先级链提取 |
| authors | 0% | 页面无结构化作者列表，统一填 "Anthropic" |
| published_date | ~95% | 从页面内容中正则提取日期 |

## 已知经验

- `_curl_html` 带 2 次重试，应对偶发的空响应（成功率从 ~25% 提升到 ~98%）
- 少数页面（如 `building-effective-agents`）偶尔返回空响应（38 bytes），重试后通常成功
- 日期格式多样（`Apr 2, 2026` / `December 18, 2024`），正则已覆盖所有月份全称和缩写
- `acceptance_type` 固定为 `Technical Report`
- `extras.anthropic_page_url` 保存原始博客页面 URL
- `extras.full_paper_url` 保存 transformer-circuits.pub 链接（如有）
- `expected_abstract_coverage` 设为 70%（og:description 不是所有页面都有）
