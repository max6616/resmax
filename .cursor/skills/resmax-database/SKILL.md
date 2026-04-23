---
name: resmax-database
description: 构建和维护 AI 顶会/顶刊基础文献库。包括数据源调研、accepted list 抓取（会议）/ 论文列表抓取（期刊）、元信息批量补全，均支持增量更新。输出 paper_database/accepted_index.csv。
---

# resmax-database

## 所属体系

本 skill 属于 resmax 自动化科研文献基础设施，与 `resmax-embedding`、`resmax-survey` 协同工作，通过文件系统共享数据、无运行时耦合。

数据流：`resmax-database`（本 skill）产出基础文献索引 → `resmax-embedding` 构建 embedding 缓存 → `resmax-survey` 消费索引和缓存进行方向级检索与评分。

共享数据目录：
| 目录 | 归属 | 说明 |
|------|------|------|
| `paper_database/` | resmax-database 产出 | 全量基础文献索引 |
| `paper_database/embedding_cache/` | resmax-embedding 产出 | Embedding 缓存 |
| `literature_research/<方向>/` | resmax-survey 产出 | 方向级检索结果、评分文献列表、筛选日志 |

设计原则：CSV 为唯一权威索引；批量优先、逐篇兜底；Skill 独立；脚本开箱即用；增量更新。

## 主 agent 行为约束（全局硬性）

1. **主 agent 是流程调度器，不是执行者**。主 agent 只负责：按顺序调用子能力、衔接 stage 输入输出、验证覆盖率、向用户汇报进度。
2. **禁止主 agent 自行编写/修改脚本代码**。如果现有脚本不支持某个会议的抓取格式，主 agent 应委派 subagent 实现新的 fetcher/parser 并测试通过后再继续流程。
3. **禁止主 agent 自行运行探索性调试**（如反复尝试不同 API、编写一次性脚本）。所有探索性工作必须委派给 subagent。
4. **禁止主 agent 读取 `$SKILL_ROOT/scripts/` 下的任何源码**。脚本是黑盒工具，本文档是其 API 文档。主 agent 根据下文的参数表、输出格式、错误处理说明来调用和解读脚本，不需要也不应该阅读实现。如果文档不足以解决问题，委派 subagent 阅读源码并返回结论。
5. **主 agent 输出应极度简洁**：只输出阶段名称、关键数字（如覆盖率）、和下一步动作。不输出调试过程、不解释脚本内部逻辑。
6. **遇到阻塞时的处理**：如果某个子能力的脚本执行失败或 subagent 返回异常，主 agent 应（a）向用户简要说明阻塞原因，（b）提出解决方案选项，（c）等待用户确认或委派 subagent 修复。禁止主 agent 自行进入"尝试-失败-再尝试"循环。

## 路径约定

```bash
SKILL_ROOT=.cursor/skills/resmax-database
```

下文所有命令和路径中的 `$SKILL_ROOT` 均指本 skill 的根目录。改名时只需修改上方赋值。

## 触发词

"建文献库", "build literature base", "更新accepted", "刷新索引", "补摘要", "增量更新文献库", "全量重建", "期刊入库", "journal papers", "更新期刊"

## 执行模式

本 skill 有两种执行模式，主 agent 根据用户指令选择：

### 增量更新（默认）

仅处理用户指定的 conf_year，按子能力 1 → 5 顺序执行（5 内部串起 abstracts / reviews / code_* / openness）。适用于新增会议或补全特定会议的元信息。最后跑子能力 6 验证。

### 全量重建

当用户说"全量重建"时，主 agent 必须端到端执行以下完整流程，不得在任何中间步骤停止：

1. **子能力 1：抓取论文目录** — 运行 `build_accepted_index.py --force`（不带 `--conf-years` 过滤）。若旧 CSV 存在，merge 时会透过 `AcceptedPaperRecord.extras` 保留所有 enrich 字段（`review_*` / `code_is_real` 等），**不需要为了保留这些字段而手动备份**
2. **子能力 5：统一元信息补全** — 对全量 CSV 运行 `enrich_all.py`（无 filter），内部 stage 顺序：`abstracts` → `abstracts_fallback` → `acceptance_type` → `reviews` → `code_urls` → `code_quality` → `openness`
   - 子能力 2 的第三轮搜索引擎兜底（orchestrator subagent / 主 agent 直接 web search）仍需单独执行，`enrich_all.py` 只覆盖前两轮批量 stage
   - `acceptance_type` stage 会按下文"录用等级映射规则 A-E"自动补全空值和无区分度的 bare "Accept"
   - reviews stage 的行为：有 OpenReview 凭据时走 fetch（仍会对已有 JSON 的论文做 rehydrate 回写 CSV）；无凭据时自动降级为 `--rehydrate` 模式，只从已有 JSON 回写 CSV 并对无评审 venue 标记 `review_available=no`。语义见子能力 3
3. **最终验证** — 运行子能力 6（`validate_database.py`），要求 `overall=PASS`。等价于 JSON 报告中 `core/coverage/embedding/registry` 全部 `OK`，且 `coverage.hard_violations = []`。任何 `FAIL` 必须在交付前解决

**硬性约束**：全量重建不得在子能力 1 完成后就停止。子能力 1 产出的 CSV 只有论文目录骨架，缺少摘要和细粒度录用等级，不是可用的最终产物。

## 子能力总览

本 skill 提供七个子能力：

| # | 名称 | 执行方式 | 成本 | 建议调用时机 |
|---|------|---------|------|-------------|
| 0 | 数据源调研 | subagent | 低 | 新增 venue 前 |
| 1 | Accepted list 抓取 | 脚本 | 低 | build 阶段 |
| 2 | 摘要批量补全（S2 → 多源 fallback → orchestrator/web search 兜底） | 脚本 + subagent 兜底 | 中 | build 之后 |
| 3 | 评审信息补全 | 脚本 | 中 | 仅公开评审 venue |
| 4 | 开源信息补全（轻量全局） | 脚本 | 低-中 | 摘要补完之后 |
| 5 | 统一编排入口 `enrich_all.py`（串 abstracts / abstracts_fallback / acceptance_type / reviews / code_* / openness） | 脚本 | 视 stage 而定 | 多 stage 串起来跑 |
| 6 | 数据库状态验证 `validate_database.py` | 脚本 | 低 | 每次 build / enrich 后必跑 |

acceptance_type 的补全规则（A-E，见"已沉淀经验"章节）作为 stage 内嵌在子能力 5 中，不是独立子能力。

**全局层开源信息补全的边界**：本 skill 只做**低成本、高置信度**的全量统计，包括代码链接补全、GitHub 仓库存在性 / stars / 最后 push / 主语言、以及摘要关键词扫出的权重/数据集声明。精细的仓库质量评估（full / partial / skeleton）、PDF 兜底扫 github 链接、HuggingFace Hub 精确匹配等**高成本判断**由 `resmax-survey` 的 Stage 3.5（openness deepcheck）在检索到相关论文后补充，见 `resmax-survey/SKILL.md`。

理由：跑 65k 论文的精细质量判断要上万次 API 和 agent 调用（>10h，误判率高），而真正被下游使用的只有检索得到的那 ~100 篇。ROI 不划算。

## 子能力详解

### 0. 数据源调研（新增会议的前置步骤，subagent 执行）

在抓取任何新会议数据前，必须先调研该会议的公开 accepted list 情况，确认可用数据源及其字段覆盖（尤其是摘要的获取途径）。

**Venue Playbook 机制**：每个 venue 系列（如 ACMMM、ICLR）在 `$SKILL_ROOT/config/venue_playbooks/` 下有一个 markdown 文件（如 `ACMMM.md`），记录该系列会议的通用抓取经验。调研新年份时必须先读取已有 playbook，避免重复踩坑。

**硬性约束**：子能力 0 的全部工作（运行脚本、web search、阅读报告、分析结论）必须由 subagent 完成。主 agent 禁止自行运行 `survey_sources.py`、直接阅读调研报告、或自行用 web search / WebFetch 调研数据源。主 agent 只消费 subagent 返回的结构化摘要。

执行步骤：

1. 主 agent 检查 `$SKILL_ROOT/config/venue_playbooks/{VENUE}.md` 是否存在，若存在则读取内容作为 `prior_knowledge`
2. 主 agent 构造 prompt，包含：venues、years、输出目录、脚本路径、`prior_knowledge`（如有）、期望返回的信息
3. 将该 prompt 发给一个 subagent（`subagent_type="generalPurpose"`）
4. subagent 内部执行调研（见下方 prompt 模板）
5. 主 agent 根据返回结果决定是否更新 `source_registry.json`
6. 主 agent 将本次调研中产生的**通用经验**追加到 `$SKILL_ROOT/config/venue_playbooks/{VENUE}.md`（见经验沉淀规则）

```python
# 伪代码 — 子能力 0 subagent 调用
prior_knowledge = read_file(f"$SKILL_ROOT/config/venue_playbooks/{venue}.md") or ""

prompt = f"""
Survey accepted list sources for the given venues/years and return a structured summary.

{"## Prior Knowledge (from previous surveys of this venue series)" + chr(10) + prior_knowledge if prior_knowledge else "## No prior knowledge available for this venue series."}

## Step 1: Run the automated probe script

python3 $SKILL_ROOT/scripts/survey_sources.py \\
  --venues {venues} --years {years} \\
  --out /tmp/survey_reports

## Step 2: Read each generated report in /tmp/survey_reports/

## Step 3: Evaluate script results

The script only has built-in URL patterns for a few major venues (ICLR, NeurIPS,
ICML, CVPR, ECCV, ICCV). For other venues it only does GitHub search.

If the script report shows "No known domain patterns" or all sources are unreachable,
you MUST use web search to find the accepted list yourself. Typical search queries:
- "<VENUE> <YEAR> accepted papers list"
- "<VENUE> <YEAR> proceedings"
- "site:openreview.net <VENUE> <YEAR>"

Investigate the found pages: check HTTP status, inspect HTML structure, identify
what fields are available (title, authors, abstract, PDF link).

## Step 3.5: Evaluate review data availability

The script now also probes OpenReview API for review data. Check the "Review Data
Availability" section in each report. If the script shows "unknown" or you suspect
the result is stale, verify manually:
- Check if the venue uses OpenReview and whether reviews are visible
- Note the scoring scale (e.g. 1-10, 1-6, 1-5) and typical reviewer count
- For ACL/EMNLP/NAACL, check ARR data release status

## Step 4: For each venue-year, return a JSON object with:
- venue, year
- status: "available" | "not_yet_announced" | "no_source_found"
- recommended_primary_source: {{name, url, fields[], has_abstract}}
- recommended_auxiliary_sources: [{{name, url, purpose}}]
- recommended_registry_entry: the full JSON entry for source_registry.json
- review_info: {{available: "yes"|"no"|"partial", platform, score_scale,
  num_reviewers, api_group, invitation_pattern, notes}}
- notes: any important observations
- playbook_update: new lessons learned about this venue series that would help
  future surveys (e.g. "site is Vue SPA, must parse webpack chunks",
  "abstracts not on accepted list, use ACM DL DOI lookup",
  "reviews public on OpenReview, scale 1-10"). Only include
  generalizable patterns, not year-specific details like chunk hashes.

If the accepted list has not been announced yet, set status to "not_yet_announced"
and explain the evidence.

Return all results as a single JSON array.
"""
response = Task(prompt=prompt, subagent_type="generalPurpose")
```

主 agent 收到 subagent 返回后，必须检查结果是否可用。如果出现以下任一情况，则向用户说明当前状况并终止 skill 执行，不继续后续子能力：
- 某个 venue-year 的 status 为 `not_yet_announced` 或 `no_source_found`
- 返回结果为空或格式异常

脚本参数参考：

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `--venues` | 是 | 逗号分隔的会议名称（大小写不敏感） | `ICLR,CVPR,NeurIPS` |
| `--years` | 是 | 逗号分隔的年份 | `2025,2026` |
| `--out` | 是 | 调研报告输出目录（临时目录即可，结论由 subagent 整合到返回值中） | `/tmp/survey_reports` |

调研报告中需重点关注：
- 主数据源是否包含 `abstract` 字段
- 是否有辅助源可补充摘要（如 OpenReview、arXiv）
- 评审数据是否公开可获取（review_info.available）
- 如果评审可获取，确认评分制度（score_scale）和 API 路径（api_group）

### 1. Accepted list 抓取

从 AI 顶会官方源抓取 accepted 论文列表，合并写入 `paper_database/accepted_index.csv`。

**硬性约束**：主 agent 只运行 `build_accepted_index.py` 并检查输出。如果脚本报错（如缺少 parser、抓取失败），主 agent 禁止自行修改脚本代码，必须委派 subagent（`subagent_type="generalPurpose"`）来实现新的 fetcher/parser、更新 registry、并验证通过。

```bash
python3 $SKILL_ROOT/scripts/build_accepted_index.py \
  --registry $SKILL_ROOT/config/source_registry.json \
  --out paper_database/accepted_index.csv \
  --report paper_database/accepted_index_coverage_report.md
```

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `--registry` | 是 | 数据源注册表 JSON 路径 | `$SKILL_ROOT/config/source_registry.json` |
| `--out` | 是 | 输出 CSV 路径 | `paper_database/accepted_index.csv` |
| `--report` | 是 | 覆盖率报告输出路径 | `paper_database/accepted_index_coverage_report.md` |
| `--conf-years` | 否 | 逗号分隔的 conf_year，仅处理指定条目 | `ICLR_2025,CVPR_2025` |
| `--venues` | 否 | 逗号分隔的 venue，仅处理指定会议 | `ICLR,CVPR` |
| `--years` | 否 | 逗号分隔的年份，仅处理指定年份 | `2025,2026` |
| `--force` | 否 | 强制重新抓取（忽略已有数据） | — |

`--conf-years` 的值必须与 `source_registry.json` 中的 `conf_year` 字段完全匹配，格式为 `VENUE_YEAR`（如 `ICLR_2025`、`NeurIPS_2024`、`SIGGRAPH_Asia_2025`）。多个值用逗号分隔，不含空格。

**成功输出**（exit code 0）：
```
[OK] wrote CSV: paper_database/accepted_index.csv
[OK] wrote report: paper_database/accepted_index_coverage_report.md
[OK] total records: 12345
```

**增量安全**：脚本在 merge 时会保留已有记录的所有字段，包括 core schema 之外的 enrich 字段（`review_*` / `code_is_real` / `code_stars` / `has_pretrained_weights` / `has_dataset` / 以及未来任何 enrich 脚本新增的列）。实现方式：CSV 任何未在 `CORE_FIELDNAMES` 声明的列都会通过 `AcceptedPaperRecord.extras` 透传保留，重新抓取不会覆盖已补全的数据。

**常见错误与应对**：
| stderr 关键词 | 含义 | 主 agent 应对 |
|---|---|---|
| `Unknown parser` / `KeyError` | registry 中指定的 parser 不存在 | 委派 subagent 实现新 parser |
| `HTTP 4xx/5xx` / `ConnectionError` | 数据源不可达 | 检查 URL 是否过期，委派 subagent 调研替代源 |
| `0 records` | 抓取到空数据 | 可能是 SPA 站点，委派 subagent 检查并参考 venue playbook |

### 2. 元信息批量补全（硬性要求）

基础文献库中每篇论文必须有摘要。要求摘要覆盖率无限接近 100%，极个别情况无法覆盖则要特别说明原因及做了哪些尝试。

补全策略按优先级依次执行，直到覆盖率达标：

**第一轮：S2 batch API**

```bash
python3 $SKILL_ROOT/scripts/enrich_abstracts.py \
  --csv paper_database/accepted_index.csv \
  --filter <CONF_YEAR>
```

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `--csv` | 是 | accepted_index.csv 路径 | `paper_database/accepted_index.csv` |
| `--filter` | 否 | 仅处理 conf_year 包含此字符串的行 | `CVPR_2025` |
| `--dry-run` | 否 | 仅统计，不写入 | — |

**成功输出**（exit code 0）：
```
[enrich] loaded 1150 rows
[enrich] 800 papers need abstract (have S2 ID)
[S2 batch] done: enriched=750, not_found=30, no_abstract=15, errors=5
[enrich] final: enriched=750, still_missing=400
[enrich] wrote updated CSV: paper_database/accepted_index.csv
```
主 agent 只需关注 `still_missing` 数字，决定是否继续下一轮。如果输出 `nothing to do` 表示该 conf_year 的论文没有可用的 S2 ID（缺 arXiv/DOI/OpenReview），直接跳到第二轮。

**第二轮：多源 fallback**

```bash
python3 $SKILL_ROOT/scripts/enrich_abstracts_fallback.py \
  --csv paper_database/accepted_index.csv \
  --filter <CONF_YEAR>
```

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `--csv` | 是 | accepted_index.csv 路径 | `paper_database/accepted_index.csv` |
| `--filter` | 否 | 仅处理 conf_year 包含此字符串的行 | `CVPR_2025` |
| `--concurrency` | 否 | 并发数（默认 5） | `10` |
| `--serpapi-key` | 否 | SerpAPI key（或设置 `SERPAPI_KEY` 环境变量） | — |
| `--dry-run` | 否 | 仅统计，不写入 | — |

fallback 搜索链：CVF → AAAI OJS → ACM → OpenAlex → CrossRef → S2 → arXiv → SerpAPI → Google Scholar 直接搜索

**成功输出**（exit code 0）：
```
[fallback] loaded 1150 rows
[fallback] 400 papers still missing abstract
  ACMMM_2024: 400
[fallback] starting with concurrency=5...
[fallback] done: enriched=389, still_missing=11
  sources: {'openalex': 200, 'crossref': 100, 's2': 50, 'arxiv': 39}
[fallback] papers still without abstract:
  - ACMMM_2024: Paper Title Here...
[fallback] wrote updated CSV: paper_database/accepted_index.csv
```
主 agent 只需关注 `still_missing` 数字和末尾列出的缺摘要论文列表。如果 `still_missing > 0`，进入第三轮兜底。

**第三轮：搜索引擎兜底（硬性）**

根据剩余缺摘要数量选择不同策略：

**路径 A：≤ 10 篇 → 主 agent 直接 web search**

当剩余缺摘要论文 ≤ 10 篇时，不启动 orchestrator subagent，主 agent 直接逐篇用 WebSearch 搜索论文标题（加引号），从 arXiv、ACM DL、IEEE Xplore、OpenReview 等公开页面提取摘要，写回 CSV。这是最快最可靠的路径。

**路径 B：> 10 篇 → orchestrator subagent 批量搜索**

主 agent 通过单次 Task 调用将全部兜底搜索委托给一个 orchestrator subagent。orchestrator 内部自行分批、派发 searcher subagent 执行 web search、收集结果，最终将找到的摘要写入 `enrich_results.json`。主 agent 读取结果后写回 CSV。

路径 B 执行步骤：

1. 用 `build_enrich_orchestrator_prompt()` 生成 orchestrator 指令
2. 将该 prompt 发给一个 subagent（`subagent_type="generalPurpose"`）
3. orchestrator 内部：读取 CSV → 筛选缺摘要论文 → 分批（每批 5 篇）→ 派发 searcher subagent（`model="fast"`）→ 收集结果 → 写入 `enrich_results.json`
4. orchestrator 返回后，主 agent 用 `load_enrich_results_file()` 读取结果
5. 调用 `apply_enrich_results()` 将找到的摘要写回 CSV

```python
# 伪代码 — 第三轮兜底搜索
from enrich_orchestrator import (
    build_enrich_orchestrator_prompt, load_enrich_results_file,
    apply_enrich_results, ENRICH_RESULTS_FILENAME,
)

prompt = build_enrich_orchestrator_prompt(
    csv_path="paper_database/accepted_index.csv",
    out_dir="paper_database",
    conf_year_filter="<CONF_YEAR>",
)
response = Task(prompt=prompt, subagent_type="generalPurpose")

results = load_enrich_results_file("paper_database/" + ENRICH_RESULTS_FILENAME)
updated, skipped = apply_enrich_results("paper_database/accepted_index.csv", results)
```

**覆盖率验证**

完成后跑子能力 6 验证：

```bash
python3 $SKILL_ROOT/scripts/validate_database.py --out /tmp/validate.json
```

目标：`overall=PASS`，或至少 JSON 报告中 `coverage.conf_year_stats["<CONF_YEAR>"].abstract_pct >= 99.0`。

### 3. 评审信息补全（仅公开评审的 venue）

对公开评审数据的 venue（ICLR、NeurIPS、ICML，当前 `VENUE_REVIEW_CONFIG` 内），通过 OpenReview API v2 批量拉取评审信息，写入 JSON 详情文件和 CSV 的 9 个 `review_*` 列。

**前置条件**：目标 conf_year 的论文必须已有 `openreview_forum_id`。如果 forum_id 覆盖率不足，脚本会先尝试通过 OpenReview API 按 title 匹配补全（`--backfill-ids` 开关）。

**凭据加载**：
```bash
source .secrets/openreview.env  # exports OPENREVIEW_USERNAME / OPENREVIEW_PASSWORD
```
（凭据清单与填写方式见仓库根目录 `SECRETS.md`；`.secrets/` 目录已 gitignore。）

**硬性约束**：对调研阶段确认评审不公开的 venue（CVPR、ECCV、ICCV、AAAI、KDD、SIGGRAPH、ACMMM，以及所有期刊），不执行本子能力，仅在 CSV 中标记 `review_available=no`。

**三种运行模式**：

| 模式 | 场景 | 命令 | 是否需网络 |
|---|---|---|---|
| fetch（默认） | 正常补全新 venue-year | 不带额外 flag（见下） | 需 OpenReview 凭据 |
| `--rehydrate` | CSV 被 rebuild 丢失 review_* 列，但 JSON 缓存还在 | `--rehydrate` | 零网络 |
| `--mark-unavailable` | 期刊 / 不公开评审 venue 批量标记 `no` | `--mark-unavailable` | 零网络 |

所有模式都是幂等的：fetch 模式下若某论文的 JSON 已存在（且对应 CSV 行已有 `review_available=yes`），会跳过网络请求；若行缺 review_* 字段，会从 JSON 回写而不重新 fetch。

```bash
python3 $SKILL_ROOT/scripts/enrich_reviews.py \
  --csv paper_database/accepted_index.csv \
  --reviews-dir paper_database/reviews \
  --filter <CONF_YEAR>
```

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `--csv` | 是 | accepted_index.csv 路径 | `paper_database/accepted_index.csv` |
| `--reviews-dir` | 是 | 评审详情 JSON 输出目录 | `paper_database/reviews` |
| `--filter` | 否 | 仅处理 conf_year 包含此字符串的行 | `ICLR_2025` |
| `--batch-size` | 否 | 每批查询论文数（默认 50） | `100` |
| `--delay` | 否 | 批次间延迟秒数（默认 1.0） | `2.0` |
| `--skip-existing` | 否 | 跳过"已有 JSON 且 CSV 行 review_available=yes"的论文（幂等重跑用） | — |
| `--scores-only` | 否 | 仅拉取评分，不保存 review 全文 | — |
| `--backfill-ids` | 否 | 先通过 title 匹配补全缺失的 openreview_forum_id | — |
| `--rehydrate` | 否 | 零网络，仅从本地 JSON 把 review_* 列写回 CSV；对不公开评审 venue 自动标 `no` | — |
| `--mark-unavailable` | 否 | 把指定过滤范围内所有不公开评审 venue 的 `review_available` 设为 `no` | — |
| `--repair` | 否 | 对 review_available 为空的论文清空 forum_id 后重新 backfill + fetch | — |

**成功输出**（fetch 模式，exit code 0）：
```
[reviews] authenticated as xxx@xxx
[reviews] loaded 5695 rows for ICLR_2026
[reviews] 5414 papers have openreview_forum_id
[reviews] processing batch 1/109...
...
[reviews] done: fetched=5600, rehydrated_from_json=64, skipped=0, errors=31
[reviews] updated CSV: paper_database/accepted_index.csv
```

**成功输出**（rehydrate 模式，exit code 0）：
```
[rehydrate] scanning 65394 rows under filter='all'
[rehydrate] rehydrated=24948, marked_no=37836, json_missing=2610
[reviews] updated CSV: paper_database/accepted_index.csv
```

主 agent 只需关注 `fetched` / `rehydrated_from_json` 和 `errors` 数字。`json_missing` 代表有 forum_id 但缓存中无 JSON 的论文——若 > 0 说明这些论文需要跑 fetch 模式。

**评审详情 JSON 结构**（`paper_database/reviews/{conf_year}/{forum_id}.json`）：

```json
{
  "paper_id": "ICLR_2025::xxx",
  "forum_id": "abc123",
  "venue": "ICLR",
  "year": 2025,
  "score_scale": "1-10",
  "reviews": [
    {
      "reviewer_id": "Reviewer_1",
      "rating": 8,
      "confidence": 4,
      "summary": "...",
      "strengths": "...",
      "weaknesses": "...",
      "questions": "...",
      "raw_content": "..."
    }
  ],
  "meta_review": {
    "recommendation": "Accept (Oral)",
    "content": "..."
  },
  "rebuttals": [
    { "round": 1, "content": "..." }
  ],
  "decision": "Accept (Oral)",
  "fetched_at": "2026-04-19T12:00:00Z"
}
```

**评审覆盖率验证**：跑 `validate_database.py`，检查 `coverage.conf_year_stats["<CONF_YEAR>"].review_available_pct`。

**不公开评审 venue 的批量标记**

对不公开评审的 venue，运行脚本的 `--mark-unavailable` 模式批量标记：

```bash
python3 $SKILL_ROOT/scripts/enrich_reviews.py \
  --csv paper_database/accepted_index.csv \
  --reviews-dir paper_database/reviews \
  --mark-unavailable \
  --filter <CONF_YEAR>
```

此模式仅将 `review_available` 设为 `no`，不发起任何 API 请求。

### 4. 开源信息补全（轻量全局）

统计论文的代码开源状态和基本仓库信息。三个脚本对应独立维度，可单独调用或通过 `enrich_all.py` 串联。

**覆盖率的实际基线**：在 65k 论文的全量统计中，`code_url` 覆盖率极限约 **45%**（PWC official 仓库 0 漏），剩下 55% 绝大多数是没有开源的论文或新会议尚未被 PWC 收录。想进一步提升得扫 PDF 首页 footnote，ROI 在全局层不划算，已挪到 `resmax-survey` 的 Stage 3.5。

**全局层边界**：本子能力只做**低成本、高置信度**的统计。`code_quality`（full / partial / skeleton）、HuggingFace Hub 精确匹配、PDF 扫描等**高成本判断**由 `resmax-survey` 的 openness deepcheck 在检索到 S/A 论文后补充。理由详见本文件"子能力总览"节。

**第一步：代码链接补全（`enrich_code_urls.py`）**

从 Papers With Code 历史 dump、Semantic Scholar batch API、摘要正则提取三路补全 `code_url`。

```bash
python3 $SKILL_ROOT/scripts/enrich_code_urls.py \
  --csv paper_database/accepted_index.csv \
  --filter <CONF_YEAR>
```

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `--csv` | 是 | accepted_index.csv 路径 | `paper_database/accepted_index.csv` |
| `--filter` | 否 | 仅处理 conf_year 包含此字符串的行 | `ICLR_2026` |
| `--pwc-dump` | 否 | PWC dump 文件目录（默认 `/tmp/pwc_dump`） | `/data/pwc` |
| `--skip-pwc` | 否 | 跳过 PWC dump 匹配 | — |
| `--skip-s2` | 否 | 跳过 S2 API 查询 | — |
| `--skip-regex` | 否 | 跳过摘要正则提取 | — |
| `--dry-run` | 否 | 仅统计，不写入 | — |

数据源优先级：PWC dump → S2 API → 摘要正则。每个源只补全尚无 `code_url` 的行。

**成功输出**（exit code 0）：
```
[enrich_code_urls] loaded 5471 rows (filter=ICLR_2026)
[enrich_code_urls] 2250 already have code_url, 3221 missing
[PWC] enriched 1200 papers
[S2] enriched 300 papers
[Regex] enriched 150 papers
[enrich_code_urls] done: enriched=1650 (PWC=1200, S2=300, regex=150)
[enrich_code_urls] final: 3900/5471 (71.3%), still_missing=1571
```

**第二步：仓库轻量探测（`enrich_code_quality.py`）**

对每个 GitHub 仓库**只发起 1 次** `/repos/{owner}/{repo}` API 请求，拿四个字段：存在性、stars、最后 push 时间（`pushed_at`）、主语言（`language`）。相比老版本（每仓库 3-4 次请求）快约 4 倍。并发（默认 8 workers）+ 断点续传。

```bash
GITHUB_TOKEN=<token> python3 $SKILL_ROOT/scripts/enrich_code_quality.py \
  --csv paper_database/accepted_index.csv \
  --filter <CONF_YEAR>
```

| 参数 | 必填 | 说明 | 默认 |
|------|------|------|------|
| `--csv` | 是 | CSV 路径 | — |
| `--filter` | 否 | conf_year 子串过滤 | 全部 |
| `--workers` | 否 | 并发数（建议 4-12） | 8 |
| `--checkpoint` | 否 | 断点续传 JSON | `<csv>.code_quality_ckpt.json` |
| `--refresh-stale-days` | 否 | 缓存过期天数（0 = 永不刷新） | 0 |
| `--dry-run` | 否 | 不写 CSV | — |

**环境变量**：`GITHUB_TOKEN`（未设时 rate limit 仅 60 req/h，几乎不可用）。

**性能**：8 worker 下约 2-3 repo/s，29k 仓库约 2-4 小时。结果字段：
- `code_is_real` ∈ `yes` / `404` / `empty` / `error:XXX`
- `code_stars` — stars 数（字符串）
- `code_last_commit` — 仓库 `pushed_at`（ISO 8601）
- `code_primary_language` — GitHub 识别的主语言

**成功输出**（exit code 0）：
```
[code_quality] 3900 repos to probe (filter=ICLR_2026, workers=8)
[code_quality] cache hits: 0, need to probe: 3900
  [100/3900] rate=2.4/s, eta=26.4min
  ...
[code_quality] done: probed=3900, cached=0, errors=12
[code_quality] results: {'yes': 3500, '404': 200, 'empty': 50, 'error:TimeoutError': 150}
```

**刻意不做的事**：不评估 `code_quality`（full / partial / skeleton）。单次 `/repos` 响应的信息不足以判断，启发式容易误判。这个维度由 `resmax-survey` 在 S/A 论文层面通过 agent 阅读 README 和仓库结构完成。

**第三步：摘要本地扫描（`enrich_openness.py`）**

**零网络**、纯本地正则/关键词扫描，对摘要里的权重发布声明和数据集属性做粗判。65k 摘要全量扫约 5 秒。

```bash
python3 $SKILL_ROOT/scripts/enrich_openness.py \
  --csv paper_database/accepted_index.csv \
  --filter <CONF_YEAR>
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `--csv` | 是 | CSV 路径 |
| `--filter` | 否 | conf_year 子串过滤 |
| `--refresh` | 否 | 强制重扫（即使已有值） |
| `--dry-run` | 否 | 不写 CSV |

**输出字段取值**：
- `has_pretrained_weights` ∈ `yes` / `no_promise`（文中承诺但没给链接）/ `unknown`
- `has_dataset` ∈ `public` / `private` / `standard_only`（只用公开 benchmark）/ `unknown`

**重要**：本步骤只做**粗筛**。HuggingFace Hub 精确匹配、PDF 扫描由 `resmax-survey` Stage 3.5 做。这里保留大量 `unknown` 是合理的 — 下游 S/A 论文会被再次精确判定。

**成功输出**（实测 ICLR_2026 5471 篇 3 秒）：
```
[openness] 5471 rows in scope, 5471 need scanning
[openness] weight stats: {'unknown': 5231, 'yes': 169, 'no_promise': 71}
[openness] dataset stats: {'unknown': 5295, 'public': 72, 'private': 15, 'standard_only': 89}
```

### 5. 统一编排入口（`enrich_all.py`）

**用途**：把子能力 2、3、4 的所有 stage + acceptance_type 映射按正确顺序串起来，一条命令跑完。新增会议 / 全量重建后补完元信息的推荐入口。

Stage 顺序：`abstracts` → `abstracts_fallback` → `acceptance_type` → `reviews` → `code_urls` → `code_quality` → `openness`

其中：
- `abstracts`：S2 batch API 第一轮（见子能力 2 第一轮）
- `abstracts_fallback`：多源 fallback 第二轮（见子能力 2 第二轮）。第三轮搜索引擎兜底需要主 agent 显式调度 orchestrator subagent，不在 enrich_all 内
- `acceptance_type`：按 SKILL.md "录用等级映射规则 A-E" 补全（见下方"已沉淀经验"章节）

```bash
# 新增会议一条龙（推荐）
GITHUB_TOKEN=<token> python3 $SKILL_ROOT/scripts/enrich_all.py \
  --csv paper_database/accepted_index.csv \
  --filter <CONF_YEAR>

# 全量刷一次除慢 stage 外的所有元信息
python3 $SKILL_ROOT/scripts/enrich_all.py \
  --csv paper_database/accepted_index.csv \
  --skip-code-quality

# 只跑某个 stage
python3 $SKILL_ROOT/scripts/enrich_all.py \
  --csv paper_database/accepted_index.csv \
  --only openness --refresh
```

| 参数 | 说明 |
|------|------|
| `--csv` | CSV 路径（必填） |
| `--filter` | conf_year 子串，传到每个 stage |
| `--only <names>` | 只跑指定 stage（逗号分隔），覆盖 skip 标志 |
| `--skip-abstracts` / `--skip-abstracts-fallback` / `--skip-acceptance-type` / `--skip-reviews` / `--skip-code-urls` / `--skip-code-quality` / `--skip-openness` | 跳过特定 stage |
| `--strict` | 任一 stage 失败就停（默认继续） |
| `--workers` | GitHub 探测并发（默认 8） |
| `--refresh` | openness 阶段强制重扫 |
| `--reviews-dir` | 评审 JSON 目录（默认 `<csv_dir>/reviews`） |
| `--dry-run` | 传给所有 stage，不写 CSV |

**自动跳过规则**：`code_quality` 在 `GITHUB_TOKEN` 未设置时自动跳过。reviews stage 在没有 OPENREVIEW 凭据时自动降级为 `--rehydrate`（见子能力 3）。

**退出码**：0 = 全部成功，2 = 至少一个 stage 非 0。

### 6. 数据库状态验证（`validate_database.py`）

**用途**：每次 build / enrich / rehydrate 后跑一次，产出结构化 JSON 报告，作为"数据库是否处于可用状态"的**单一事实源**。主 agent 凭此报告决定是否交付或需要继续修复，不需要自己写统计 SQL 或对着 SKILL.md 的表格去核对。

```bash
python3 $SKILL_ROOT/scripts/validate_database.py \
  --csv paper_database/accepted_index.csv \
  --cache paper_database/embedding_cache/qwen3_8b.npz \
  --registry $SKILL_ROOT/config/source_registry.json \
  --reviews-dir paper_database/reviews \
  --out /tmp/validate.json
```

全部默认值可省略（与上方示例一致）。`--out` 省略时 JSON 输出到 stdout；`--quiet` 省略 stderr 摘要。

**退出码**：0 = `overall=PASS`，1 = 任一 hard 违例或 schema 级错误。

**检查维度**（硬性要求任一不满足即 FAIL，软警告仅提示）：

| ID | 检查项 | 硬性阈值 |
|---|---|---|
| H1 | paper_id 唯一、title/venue/year 非空 | 100% |
| H2 | 每个 conf_year 的 abstract_raw 覆盖率 | ≥ registry 中声明的 `expected_abstract_coverage`（默认 99%，AIJ/IJCV 因 Springer 摘要缺失声明为 65%） |
| H3 | 每个 conf_year 的 acceptance_type 覆盖率 100% 且 0 行 bare `Accept` | = 100% |
| H4 | 公开评审 venue 且 `reviews/<conf_year>/` 已有数据时，review_available 覆盖率 | ≥ 99% |
| H5 | embedding cache 与 CSV paper_id 重叠率 | ≥ 95% |

**软警告**：公开评审 venue 但 `reviews/` 目录不存在（enrich_reviews 从未跑过）、registry 与 CSV 的 conf_year 集合差异、review_detail_path 指向缺失文件等。

**JSON 报告字段**（agent 读这几个就能做决策）：
- `overall`: `PASS` / `FAIL`
- `core.status`, `core.duplicate_paper_ids`, `core.total_rows`
- `coverage.status`, `coverage.hard_violations[]`, `coverage.soft_warnings[]`, `coverage.conf_year_stats{<conf_year>: {...}}`
- `embedding.status`, `embedding.overlap_pct`, `embedding.missing_in_cache`
- `registry.status`, `registry.unexpected_in_csv[]`, `registry.missing_from_csv[]`
- `review_json_integrity.status`, `review_json_integrity.missing_files`

## 输出

| 文件 | 说明 |
|------|------|
| `paper_database/accepted_index.csv` | 基础文献索引（schema 见下方） |
| `paper_database/accepted_index_coverage_report.md` | 覆盖率报告 |
| `paper_database/reviews/{conf_year}/{forum_id}.json` | 评审详情 JSON（每篇论文一个文件，仅公开评审的 venue） |
| `paper_database/accepted_index.code_quality_ckpt.json` | GitHub 仓库探测断点续传缓存（子能力 4 第二步） |
| `$SKILL_ROOT/config/venue_playbooks/` | Venue 级经验手册（经验证的跨年份复用经验，子能力 0 的 prior knowledge 输入） |

## accepted_index.csv Schema

CSV 的列按逻辑分为两层：

1. **核心字段**（34 列）由 `build_accepted_index.py` 直接写入，对应 `AcceptedPaperRecord` 的 dataclass 字段。
2. **Enrich 字段**（~15 列，会根据上游调用增减）由后续 enrich_* 脚本追加，通过 `AcceptedPaperRecord.extras` 透传，**build 循环不会丢失**（这是 2026-04 修复的旧 bug）。

任何 enrich 脚本添加新列，build 下次运行都会自动保留。文档侧只声明"至少有的字段"即可，agent 应以 `validate_database.py --out` 的 `csv_fields` 字段为准。

### 核心字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `paper_id` | string | 全局唯一标识（格式：`VENUE_YEAR_序号`） |
| `short_id` | string | 短标识 |
| `venue` | string | 会议名称（如 `ICLR`、`CVPR`） |
| `year` | int | 年份 |
| `conf_year` | string | 会议-年份标识（如 `ICLR_2025`） |
| `title` | string | 论文标题 |
| `authors` | string | 作者列表（分号分隔） |
| `source_type` | string | 数据源类型 |
| `source_url` | string | 数据源 URL |
| `paper_link` | string | 论文页面链接 |
| `arxiv_id` | string | arXiv ID |
| `arxiv_url` | string | arXiv URL |
| `keywords_raw` | string | 原始关键词 |
| `abstract_raw` | string | 原始摘要 |
| `doi` | string | DOI |
| `openreview_forum_id` | string | OpenReview forum ID |
| `has_pdf_camera_ready` | bool | 是否有 camera-ready PDF |
| `decision` | string | 原始录用决定（标准化大小写，如 `Accept (Poster)`、`Accept (Oral)`） |
| `acceptance_type` | string | 标准化录用等级：`Oral` / `Spotlight` / `Highlight` / `Poster` / `Accept`。从 decision + event_type 推断 |
| `topic` | string | 论文主题分类（如 `Applications->Robotics`） |
| `code_url` | string | 代码链接 |
| `paper_url` | string | 论文 URL（通常为 OpenReview 链接） |
| `virtual_id` | string | 虚拟会议平台内部 ID |
| `virtual_uid` | string | 虚拟会议平台 UID |
| `virtualsite_url` | string | 虚拟会议页面路径（如 `/virtual/2024/poster/18969`） |
| `sourceid` | string | 数据源 ID（如 OpenReview source ID） |
| `sourceurl` | string | 数据源 URL（如 OpenReview group URL） |
| `session` | string | 展示 session（如 `Poster Session 4`） |
| `eventtype` | string | 事件类型（如 `Poster`、`Oral`） |
| `event_type` | string | 细粒度事件类型（如 `Spotlight Poster`、`Oral Poster`） |
| `room_name` | string | 展示房间 |
| `starttime` | string | 展示开始时间（ISO 8601） |
| `endtime` | string | 展示结束时间（ISO 8601） |
| `poster_position` | string | 海报位置编号 |

注：`virtual_id` ~ `poster_position` 字段仅 `virtual_conference_json` 数据源有值，其他数据源为空。

### Enrich 字段（extras）

以下字段由 enrich_* 脚本写入，核心 schema 不认识但会被透传保留。当前约定的字段如下：

| 字段 | 来源脚本 | 说明 |
|------|---------|------|
| `review_available` | enrich_reviews | 是否有公开评审：`yes` / `no` / `partial` |
| `review_source` | enrich_reviews | 评审数据来源（如 `openreview_v2`、空） |
| `review_num_reviewers` | enrich_reviews | 审稿人数量 |
| `review_score_scale` | enrich_reviews | 评分制度（如 `1-10`、`1-6`） |
| `review_scores` | enrich_reviews | 各审稿人评分（分号分隔，如 `6;8;5;7`） |
| `review_score_mean` | enrich_reviews | 平均评分（保留 2 位小数） |
| `review_confidence_scores` | enrich_reviews | 各审稿人 confidence（分号分隔） |
| `review_confidence_mean` | enrich_reviews | 平均 confidence（保留 2 位小数） |
| `review_detail_path` | enrich_reviews | 评审详情 JSON 相对路径（如 `paper_database/reviews/ICLR_2025/abc123.json`） |
| `code_is_real` | enrich_code_quality | `yes` / `404` / `empty` / `error:<type>` |
| `code_stars` | enrich_code_quality | GitHub stars 数（字符串） |
| `code_last_commit` | enrich_code_quality | 仓库 `pushed_at`（ISO 8601） |
| `code_primary_language` | enrich_code_quality | GitHub 识别的主语言（如 `Python`） |
| `has_pretrained_weights` | enrich_openness | 粗判：`yes` / `no_promise` / `unknown` |
| `has_dataset` | enrich_openness | 粗判：`public` / `private` / `standard_only` / `unknown` |

注：`review_*` 字段仅对 `VENUE_REVIEW_CONFIG` 配置内的公开评审 venue（当前 ICLR / NeurIPS / ICML）有完整值；不公开评审 venue 的 `review_available=no`，其余 review 列为空。评审详情 JSON 存储在 `paper_database/reviews/{conf_year}/{forum_id}.json`。

注：`code_is_real` ~ `code_primary_language` 字段仅对有 `code_url` 且指向 GitHub 仓库的论文有值。`has_pretrained_weights` 和 `has_dataset` 是纯本地摘要扫描的粗筛结果，`resmax-survey` 的 Stage 3.5 会对 S/A 论文进一步精确判定。

**已在全局层删除的字段**：原 `code_quality`（full/partial/skeleton）和 `code_framework`。`code_quality` 移到 `resmax-survey` 层基于 agent 读 README 评估；`code_framework` 信息量小于 `code_primary_language`，已被后者取代。如果旧 CSV 仍保留这两列，build 会通过 extras 透传保留，但没有脚本会再更新它们。

## 新增会议流程

1. 子能力 0：subagent 调研该 venue 的公开 accepted list 情况，重点关注摘要获取途径和评审数据可获取性
2. 在 `config/source_registry.json` 中添加对应 conference-year 条目（可参考调研报告的推荐）
3. 子能力 1：`build_accepted_index.py --conf-years <NEW_CONF_YEAR>` 增量抓取
4. 子能力 5：`enrich_all.py --filter <CONF_YEAR>` 一次性补完摘要、评审、开源信息
   - 未设置 `GITHUB_TOKEN` 时会自动跳过 `code_quality` stage
   - 未设置 `OPENREVIEW_USERNAME/PASSWORD` 时 reviews stage 自动降级为 `--rehydrate`
   - 如果第三轮摘要兜底仍有缺口，走子能力 2 的第三轮兜底流程（主 agent web search）
5. 子能力 6：`validate_database.py` 验证 `overall=PASS`
6. 使用 `resmax-embedding` skill 在 GPU 服务器上增量更新 embedding 缓存（覆盖率不足 95% 时 validate 会 FAIL）

**说明**：推荐用 `enrich_all.py` 作为统一入口，不建议再逐个调用 `enrich_abstracts.py` / `enrich_reviews.py` / `enrich_code_*.py`。它们仍可单独使用（见各子能力说明），但一条龙入口保证 stage 顺序和错误处理一致。

## 新增期刊流程

期刊论文入库与会议类似，但数据源不同。当前支持两种期刊数据源：

### OpenAlex API（TPAMI、IJCV、AIJ、TNNLS）

1. 在 `config/journal_sources.json` 中确认期刊的 OpenAlex source ID
2. 在 `config/source_registry.json` 中添加条目，`kind` 设为 `openalex_api`，`url` 填 OpenAlex source ID，`parser_args` 填年份
3. 设置环境变量 `OPENALEX_API_KEY`（免费注册获取，无 key 时每天仅 100 次请求）
4. 运行 `build_accepted_index.py --conf-years <VENUE_YEAR>` 增量抓取
5. OpenAlex 对 IEEE 和 Elsevier 期刊直接提供摘要；Springer 期刊（如 IJCV）无摘要，需走 enrich fallback 补全
6. `enrich_all.py --filter <VENUE_YEAR>` 自动处理期刊：reviews stage 在降级到 `--rehydrate` 模式时会把期刊的 `review_available` 标记为 `no`（无需手动 `--mark-unavailable`）

### JMLR 官网（JMLR）

1. 在 `config/source_registry.json` 中添加条目，`kind` 设为 `jmlr_html`，`url` 填 `https://jmlr.org/papers/v{N}/`
2. Volume-年份映射：v25=2024, v26=2025, v27=2026
3. 运行 `build_accepted_index.py --conf-years JMLR_<YEAR>` 增量抓取
4. JMLR 是开放获取，摘要通过 fallback 脚本从 abs 页面补全

### 期刊 acceptance_type

期刊论文的 `acceptance_type` 统一设为 `Journal Article`，区别于会议的 Oral/Spotlight/Highlight/Poster。

### 当前已入库期刊

| 期刊 | OpenAlex ID | 数据源 | 年份 | 约论文数/年 |
|------|-------------|--------|------|------------|
| TPAMI | S199944782 | openalex_api | 2024-2026 | ~700 |
| IJCV | S25538012 | openalex_api | 2024-2026 | ~360 |
| JMLR | — | jmlr_html | 2024-2026 | ~300 |
| AIJ | S196139623 | openalex_api | 2024-2026 | ~130 |
| TNNLS | S4210175523 | openalex_api | 2024-2026 | ~850 |

## 配置文件说明

### config/source_registry.json

数据源注册表，定义每个 conference-year / journal-year 的抓取源。每个条目包含：
- `venue` / `year` / `conf_year`：会议或期刊标识（期刊也使用 `conf_year` 字段，格式如 `TPAMI_2025`）
- `status`：`active`（正常抓取）或 `skip`（跳过，需填 `skip_reason`）
- `primary_source`：主数据源（`kind`、`url`、`parser`、`expected_count`）
- `auxiliary_sources`：辅助数据源列表
- `expected_abstract_coverage`：（可选，默认 99.0）该 conf_year 的摘要覆盖率下限。用于对上游数据源存在客观限制的 venue 放宽 `validate_database.py` 的 H2 阈值（当前 AIJ / IJCV 设 65.0，其它默认 99.0）。
- `notes`：备注

`url` 支持两种格式：
- 标准 URL：直接从网络抓取
- `fixture://` 前缀：从 `fixtures/` 目录加载离线快照（用于无法直接抓取或需要稳定复现的源）

### config/journal_sources.json

期刊元信息参考表，记录每个期刊的 OpenAlex source ID、ISSN、DBLP key 等。供调研和新增期刊时查表使用，不被脚本直接读取（脚本通过 source_registry.json 获取配置）。

### 环境变量

本 skill 的所有脚本通过 `.cursor/skills/_shared/secrets_loader.py` 自动加载
`.secrets/*.env` 与 `.localconfig/*.env`，**不需要**手动 `source`。各变量的
归档文件与必填性：

| 变量 | 归档 | 说明 | 必填 |
|------|------|------|------|
| `OPENREVIEW_USERNAME` / `OPENREVIEW_PASSWORD` | `.secrets/openreview.env` | OpenReview API 账号（子能力 3） | fetch 模式必填；`--rehydrate` / `--mark-unavailable` 零网络模式无需 |
| `OPENALEX_API_KEY` | `.secrets/openalex.env` | OpenAlex API key（免费注册） | 期刊入库强烈建议，否则每天仅 100 次请求 |
| `SERPAPI_KEY` | `.secrets/serpapi.env` | SerpAPI key（摘要兜底搜索用） | 否 |
| `GITHUB_TOKEN` | `.secrets/github.env` | GitHub personal access token（子能力 4 仓库探测） | 无 token 时 rate limit 60 req/h，几乎不可用 |
| `S2_API_KEY` | `.secrets/s2.env` | Semantic Scholar API key（提升 rate limit） | 否 |
| `RESMAX_CONTACT_EMAIL` | `.secrets/contact.env` | 用于 OpenAlex/Crossref 的 User-Agent mailto；未设置时回落到 `resmax@example.com` | 否，但填了能进入 OpenAlex polite pool |

### 信息补充指引（hard-required secret 缺失时 agent 的处理流程）

脚本在缺少**硬性必填**凭据时会抛出 `MissingSecretError`，stderr 中会出现
固定前缀 `[MISSING_SECRET]`，后跟 JSON 载荷，例如：

```
[MISSING_SECRET] {"missing_var": "OPENREVIEW_USERNAME", "all_vars": ["OPENREVIEW_USERNAME","OPENREVIEW_PASSWORD"], "env_file": ".secrets/openreview.env", "example_file": ".secrets/openreview.env.example", "purpose": "Authenticate to OpenReview API v2 to fetch review data"}
```

主 agent 必须：

1. **立即终止当前 stage**，不要重试、不要降级、不要伪造默认值。
2. 解析 JSON 载荷，用自然语言向用户说明：本 skill 的哪个子能力需要这个值、
   会写入哪个 `.env` 文件、`.secrets/` 已 gitignore。
3. 获得用户答复后，把 `export VAR='<value>'` 追加到 `env_file`（文件不存在
   时从 `example_file` 复制），`.secrets/` 下的文件权限设为 `0600`。
4. 重新执行原命令。共享 loader 会在下一次 import 时自动拾取新值。

详见仓库根目录 `SECRETS.md` 的完整协议。

## 经验沉淀规则

执行本 skill 后，如果发现了可复用的经验，应沉淀到对应层级的文件中。经验分三层：

**Layer 1：Venue Playbook（`$SKILL_ROOT/config/venue_playbooks/{VENUE}.md`）**

记录某个会议系列（跨年份通用）的抓取经验。每次完成子能力 0 后，主 agent 根据 subagent 返回的 `playbook_update` 字段追加更新。

适合写入的内容：
- 该系列会议站点的技术架构（如"ACM MM 系列 2023 起使用 Vue SPA，需解析 webpack chunk"）
- 摘要获取的最佳路径（如"accepted list 无摘要，需通过 ACM DL DOI 或 arXiv 补全"）
- 已知的 parser kind 和适用年份范围
- 常见坑点（如"录用列表标题可能与 proceedings 不一致，以 DOI 为准"）
- 评审数据公开政策（是否公开、平台、评分制度、审稿人数量）
- 评审数据获取的 API 路径和 invitation pattern
- 评分制度的年份变更（如"NeurIPS 2025 起评分制度从 1-10 改为 1-6"）

不适合写入的内容：
- 特定年份的 chunk 哈希、URL 路径等易变细节（这些放 `source_registry.json` 的 `notes`）
- 特定论文的问题

**Layer 2：source_registry.json 的 notes 字段**

记录特定 venue-year 的技术细节，如 chunk 名、fixture 来源、expected_count 依据等。

**Layer 3：SKILL.md 本文件**

只记录跨 venue 通用的流程改进，如：
- 脚本 bug 修复或新增参数
- 补全策略优先级调整（如"S2 batch 经常 429，应在 fallback 中降低重试次数"）
- 新增的 fallback 数据源
- 流程步骤的增删改

判断标准：**如果经验只对某个 venue 有用 → Layer 1；只对某个 venue-year 有用 → Layer 2；对所有会议通用 → Layer 3**。

## 已沉淀经验（Layer 3）

### 全量重建的并发控制

同一工作区内禁止并发启动多个 `build_accepted_index.py` 全量重建任务，否则多个进程会竞争写同一个 `accepted_index.csv`，导致产物来源不确定、监控信号被污染。任一时刻只保留一个权威全量重建任务。

### CSV schema 分层与 enrich 字段保留（2026-04）

**经验**：CSV 的列分两层——core（`AcceptedPaperRecord` 的 34 个 dataclass 字段）+ extras（`review_*` / `code_is_real` / `has_pretrained_weights` 等 enrich 脚本追加的列）。早期 `build_accepted_index.py` 的 `load_existing_records` 和 `write_csv` 只认 core，导致每次 build 都把 extras 抹掉；"增量保留"被误宣称。

**修复**：`AcceptedPaperRecord.extras: dict` 透传未知列；`write_csv` 动态写出 `CORE_FIELDNAMES + sorted(extras_keys)`。所有 enrich 脚本写入的列都会被 build 循环无损保留，不需要在 build 前备份 CSV。

**验证方式**：`validate_database.py` 的 JSON 报告里 `csv_fields` 列出实际字段。新增 enrich 脚本后，只要任意一行写入了新列，之后 build 会自动把它加进 CSV header。

### 代理环境变量对脚本的干扰

本机 shell 经常设置 `ALL_PROXY=http://127.0.0.1:10901`（Clash/其他本地代理）。若代理进程未启动，基于 `requests` 的脚本（`enrich_reviews`、`enrich_abstracts_fallback` 等）会对每个请求重试多次并全部失败，但不一定显式报错——需要显式 `unset ALL_PROXY HTTP_PROXY HTTPS_PROXY`（或 `env -u`）。OpenReview/arXiv/OpenAlex/Semantic Scholar 在中国大陆均可直连。

### 部分 venue-year 不公开评审（year-level override）

**经验**：即便 venue 声明"公开评审"，具体年份可能例外。已知：
- ICML 2024 的 OpenReview 只暴露 Submission / Post_Submission，没有 Official_Review（2026-04 直连 API 确认）。
- NeurIPS 2025 改为 1-6 分制（见 `score_scale_overrides`）。

**约定**：`VENUE_REVIEW_CONFIG[venue]["no_public_years"]` 声明此类年份。rehydrate 和 fetch 模式都会对这些年份的论文直接 mark `review_available=no`，不发网络请求。

### Springer 期刊摘要缺口（AIJ / IJCV）

**经验**：OpenAlex 对 Springer / Elsevier 部分期刊不提供 `abstract_inverted_index` 字段，第二轮 fallback（Unpaywall / OpenAlex / CrossRef / S2 / arXiv / SerpAPI）对付费墙后的论文命中率也有限。实测 AIJ_2024 fallback 后摘要覆盖率只有 73%（87/119）。

**约定**：对 AIJ / IJCV 全年份，`source_registry.json` 里已声明 `expected_abstract_coverage=65.0`，validate 对这些 venue 按 65% 阈值判定；其它会议默认 99%。这样"上游数据源限制"不会伪装成"skill 质量问题"。

如果需要进一步提升 AIJ / IJCV 的覆盖率，可选：
- 手动跑第三轮 orchestrator subagent（见子能力 2 第三轮）；
- 通过机构代理下载原文后离线扫描。

JMLR / TNNLS / TPAMI 能直接经 OpenAlex 拿到摘要，保持默认 99% 阈值。

### P7 动态测试沉淀（2026-04）

三个代表性 venue 全流程验证修复结果：

| venue | 行数 | abstract | acceptance_type | review_available | 备注 |
|---|---|---|---|---|---|
| SIGGRAPH_2025 | 330 | 99.7% | Conference Paper 100% | `no` 100% | Bug-2/3 修复生效 |
| KDD_2024 | 411 | 100% | Poster 100% | `no` 100% | D 规则通过 |
| ICLR_2024 | 2296 | 100% | Poster/Spotlight/Oral 100% | rehydrate `yes` 2260/2296 | 公开评审 rehydrate 路径通过 |
| AIJ_2024 | 119 | 70.6% | Journal Article 100% | `no` 100% | Springer 固有限制 |

**核心结论**：`AcceptedPaperRecord.extras` 透传在 build → enrich 全链路多次循环中零丢失；新增 venue 的 acceptance_type 100% 自动化；`review_available` 对非公开评审 venue 100% 自动标 `no`。

### 录用等级（acceptance_type）标准化

virtual conference JSON 的 `decision` 字段大小写极不统一（如 `Accept (poster)` vs `Accept (Poster)` vs `Accept (oral)` vs `Accept (Oral)`），同一会议同一年份内都可能混用。`_normalize_decision()` 统一为 `Accept (Poster)` 格式（括号内 Title Case）。

`acceptance_type` 字段从 decision → event_type → eventtype 三级回退推断，标准化为 `Oral` / `Spotlight` / `Highlight` / `Poster` / `Accept` 五个值。特殊情况：
- ECCV 2024 的 decision 全为空，但 event_type 有 Poster/Oral，可正确回退
- CVPR 2026 引入了 `Highlight` 等级（介于 Oral 和 Poster 之间）
- NeurIPS 2025 的 event_type 含 `{location}` 占位符（如 `{location} Poster`），不影响推断
- ICML 2025 有 `Accept (spotlight poster)` 变体，标准化为 Spotlight

### 录用等级映射规则

`build_accepted_index.py` 只能从 virtual conference JSON 的 decision/event_type 推断录用等级。对于不使用 virtual conference JSON 的 venue，或 auxiliary source 未覆盖到的论文，需要在子能力 2 之后额外补全。规则如下：

**A. 有 virtual conference JSON 的 venue（ICLR、NeurIPS、ICML、CVPR、ECCV、ICCV）**：
- 脚本已自动推断，但 auxiliary source 未覆盖的论文（如 CVPR 中仅在 CVF OpenAccess 出现的论文）acceptance_type 可能为空
- 补全策略：这些论文默认标记为 `Poster`（CVF OpenAccess 不区分 oral/poster，但未被 virtual conference JSON 收录的论文几乎全是 poster）

**B. ACL/EMNLP（ACL Anthology 数据源）**：
- decision 字段已有 Main/Findings/Main Short/SRW/Industry/Demo 区分
- 映射：`Main` → `Main`, `Findings` → `Findings`, `Main Short` → `Main Short`, `SRW` → `SRW`, `Industry` → `Industry`, `Demo` → `Demo`

**C. SIGGRAPH/SIGGRAPH Asia（Ke-Sen Huang 页面）**：
- keywords_raw 字段有 SIG/TOG/SIG+TOG 区分
- 映射：`SIG` → `Conference Paper`, `TOG` → `Journal Paper`, `SIG/TOG` → `Conference+Journal`, 空 → `Conference Paper`

**D. 无区分信息的 venue（AAAI、ACMMM、KDD）**：
- 数据源（OJS proceedings / accepted list HTML）不提供 oral/poster 区分
- 这些会议也不公开 oral/poster 列表
- 补全策略：统一标记为 `Poster`

**E. 期刊（TPAMI、IJCV、JMLR、AIJ、TNNLS）**：
- 期刊论文无 oral/poster 区分
- Parser 直接设置 `acceptance_type = "Journal Article"`
- 无需额外补全
