---
name: resmax-database
description: 构建、规范化和验证 AI 顶会/顶刊基础文献库。产出 paper_database/accepted_index.csv，并维护 manifest、review/cache/schema 覆盖率。
---

# resmax-database

## 何时使用

用于新增或刷新基础论文库、补全摘要/评审/代码信息、规范化现有 CSV、生成 `paper_database/manifest.json`、验证数据库是否可供下游检索。

## 执行原则

- Codex 主 agent 负责调度、验证和报告；长 context、网页调研、逐 venue 解析和动态试跑交给 subagent。
- CSV 是唯一权威索引；`paper_database/manifest.json` 是本机快照的可复现证据。大产物不入 git。
- 先用脚本解决可重放问题，禁止手工编辑 `accepted_index.csv`。
- 如果需要明显偏离当前流程才能继续，先停下修脚本或文档，再重跑。

## 最小流程

```bash
SKILL_ROOT=.agents/skills/resmax-database

python3 $SKILL_ROOT/scripts/build_accepted_index.py \
  --registry $SKILL_ROOT/config/source_registry.json \
  --out paper_database/accepted_index.csv \
  --report paper_database/accepted_index_coverage_report.md

python3 $SKILL_ROOT/scripts/enrich_all.py \
  --csv paper_database/accepted_index.csv

python3 $SKILL_ROOT/scripts/normalize_database.py \
  --csv paper_database/accepted_index.csv \
  --manifest paper_database/manifest.json

python3 $SKILL_ROOT/scripts/ensure_reviews_available.py \
  --csv paper_database/accepted_index.csv \
  --reviews-dir paper_database/reviews \
  --package-dir paper_database/hf_export/reviews

python3 $SKILL_ROOT/scripts/validate_database.py \
  --csv paper_database/accepted_index.csv \
  --cache paper_database/embedding_cache/qwen3_8b.npz \
  --manifest paper_database/manifest.json \
  --out paper_database/validate_report.json
```

增量处理时给 build/enrich 加 `--conf-years <VENUE_YEAR>` 或 `--filter <VENUE_YEAR>`。全量重建必须跑完 build → enrich → normalize → validate，不得停在 accepted list 骨架。

`validate_database.py` 的 JSON 报告必须用 `--out` 写文件；不要用 shell 重定向捕获 stdout/stderr，否则错误摘要会和 JSON 混在同一个文件里。

## 数据契约

- `paper_link`：兼容旧字段，表示论文 landing page 或原始来源链接，不保证是 PDF。
- `landing_url`：规范化后的论文页面入口。
- `pdf_url`：可直接下载 PDF 的 URL；仅由官方/OA/arXiv/OpenReview/明确 PDF 链接派生。
- `pdf_status`：`available` 或 `missing_unresolved`。
- `pdf_source`：`pdf_url` / `arxiv_id` / `openreview_forum_id` / `cvf_html` / `acl_anthology` / `paper_link` / `none`。
- `source_text_status`：`pdf_available` / `preprint_available` / `publisher_landing_only` / `official_landing_only` / `source_listing_only` / `paywalled_landing` / `not_yet_public` / `unresolved_after_search` / `missing_anchor_needs_search`。
- `source_text_url`：当前最好的原文锚点；优先 PDF/preprint，其次 DOI/publisher/official landing，再其次 source listing。
- `source_text_evidence`：JSON 证据，说明该状态来自哪个字段/来源。
- `source_text_search_query`：需要逐篇 web search 升级时使用的默认查询；已有 PDF 时为空。
- `review_score_status`：`complete` / `no_scores` / `no_reviews` / `unavailable` / `partial` / `unknown`。
- `code_url` 必须经过规范化，不得包含 prose 尾标点，也不得用 `rstrip(".git")` 这类字符集删除逻辑。

## 验证门槛

`validate_database.py` 是唯一状态门。`overall=PASS` 才能交给 `resmax-embedding` 或 `resmax-survey` 的生产路径。常见 FAIL：

- embedding cache 不是安全字符串 dtype，或没有覆盖所有 queryable rows。
- manifest 缺失、hash 不匹配、或 source report 有 `active_with_errors`。
- 公开评审 venue 已有 review JSON 但 `review_available` 覆盖率不足。
- 摘要是空值/占位符而低于 registry 阈值。

字段覆盖和 DOI/PDF 缺口审计使用：

```bash
python3 $SKILL_ROOT/scripts/audit_field_coverage.py \
  --csv paper_database/accepted_index.csv \
  --json-out /tmp/resmax_field_coverage_audit.json \
  --md-out /tmp/resmax_doi_pdf_gap_report.md
```

逐篇 web search / OA resolver 升级队列使用：

```bash
python3 $SKILL_ROOT/scripts/export_source_text_queue.py \
  --csv paper_database/accepted_index.csv \
  --out /tmp/resmax_source_text_search_queue.csv
```

subagent/web search 结果必须写成 JSONL，再用脚本回填：

```bash
python3 $SKILL_ROOT/scripts/apply_source_text_results.py \
  --csv paper_database/accepted_index.csv \
  --results-jsonl /tmp/resmax_source_text_results.jsonl

python3 $SKILL_ROOT/scripts/normalize_database.py \
  --csv paper_database/accepted_index.csv \
  --manifest paper_database/manifest.json
```

JSONL 每行至少包含 `paper_id`、`source_text_status`、`source_text_url`、`source_text_source`、`source_text_evidence`。只有真实 PDF/preprint 直链才能写 `source_text_status=pdf_available/preprint_available` 并同步到 `pdf_url`。

`source_text_status` 允许把“有官方/出版商锚点但无 PDF”和“找到 PDF/preprint”区分开。不得为了追求 `pdf_url=100%` 把 DOI landing、venue poster 页或 source listing 填进 `pdf_url`。

逐篇补摘要时，`abstract_raw` 必须来自权威页面、论文 PDF、OpenReview/arXiv/OA 元数据或机构 Pure/仓储页；subagent 的归纳总结只能作为检索线索，不能写入 `abstract_raw`。如果只能找到论文存在性证据而没有摘要原文，应保留 unresolved 队列，不能用模型改写文本冒充摘要。

摘要内容更新后，现有 embedding cache 即使 ID 覆盖仍通过 validate，也应视为语义过期；恢复 GPU 后需要用 `resmax-embedding` 重新编码受影响论文或全量重建缓存。

## Hugging Face 导出

review JSON 缓存文件数很多，不适合逐文件上传到 Hugging Face。上传前先生成按 `conf_year` 分片的压缩包和索引：

```bash
python3 $SKILL_ROOT/scripts/package_reviews_for_hf.py \
  --csv paper_database/accepted_index.csv \
  --reviews-dir paper_database/reviews \
  --out-dir paper_database/hf_export/reviews
```

产物包括 `reviews_index.csv` / `reviews_index.parquet`、`reviews_manifest.json`、`checksums.sha256` 和 `archives/reviews_<conf_year>.tar.zst`。上传到 HF dataset repo 时保留这些文件的相对路径，避免把 `paper_database/reviews/**/*.json` 原样上传。

生产执行在 validate 或需要 review 信息前先调用 `ensure_reviews_available.py`。它的执行逻辑：

1. 如果 `paper_database/reviews/{conf_year}/{forum_id}.json` 已覆盖 `accepted_index.csv` 中所有 `review_available=yes` 行，直接通过。
2. 如果原始 JSON 缺失但本地存在 `paper_database/hf_export/reviews` package，自动校验并解压还原。
3. 如果原始 JSON 和本地 package 都不存在，自动尝试从 Hugging Face 私有 dataset repo 下载 package，再校验并解压。下载 repo 通过 `--hf-repo-id` 或 `RESMAX_HF_DATASET_REPO` 指定，package 在 repo 内的路径默认是 `reviews/`，可用 `--hf-reviews-path` 或 `RESMAX_HF_REVIEWS_PATH` 覆盖。
4. 如果无法下载、缺少 repo 配置、checksum/CSV hash/索引校验失败、或解压后仍缺文件，必须显式报错并终止；不得静默降级为“无 review”继续生产流程。

部署者从 HF 下载 review package 后，也可以手动还原为现有数据库契约使用的原始 JSON 目录：

```bash
python3 $SKILL_ROOT/scripts/ensure_reviews_available.py \
  --package-dir paper_database/hf_export/reviews \
  --reviews-dir paper_database/reviews \
  --csv paper_database/accepted_index.csv

python3 $SKILL_ROOT/scripts/validate_database.py \
  --csv paper_database/accepted_index.csv \
  --cache paper_database/embedding_cache/qwen3_8b.npz \
  --manifest paper_database/manifest.json
```

`ensure_reviews_available.py` 下载/还原后，现有 `enrich_reviews.py --rehydrate`、`validate_database.py` 和下游 skill 仍只读取 `paper_database/reviews/{conf_year}/{forum_id}.json`，不直接读取压缩包。

## 参考资料

- 旧完整手册：`references/legacy_full_manual.md`
- venue 经验：`config/venue_playbooks/*.md`
- 依赖：根目录 `requirements.txt`，数据库脚本最小依赖见 `scripts/requirements.txt`
