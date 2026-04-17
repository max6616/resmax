---
name: resmax-database
description: 构建和维护 AI 顶会基础文献库。包括数据源调研、accepted list 抓取、元信息批量补全、embedding 缓存构建，均支持增量更新。输出 paper_database/accepted_index.csv 和 embedding 缓存。
---

# resmax-database

## 所属体系

本 skill 属于 resmax 自动化科研文献基础设施，与 `resmax-survey` 协同工作，通过文件系统共享数据、无运行时耦合。

数据流：`resmax-database`（本 skill）产出基础文献索引和 embedding 缓存 → `resmax-survey` 消费这些数据进行方向级检索与评分。

共享数据目录：
| 目录 | 归属 | 说明 |
|------|------|------|
| `paper_database/` | resmax-database 产出 | 全量基础文献索引、embedding 缓存、数据源调研报告 |
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

"建文献库", "build literature base", "更新accepted", "刷新索引", "build cache", "补摘要", "增量更新文献库"

## 四个子能力

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

## Step 4: For each venue-year, return a JSON object with:
- venue, year
- status: "available" | "not_yet_announced" | "no_source_found"
- recommended_primary_source: {{name, url, fields[], has_abstract}}
- recommended_auxiliary_sources: [{{name, url, purpose}}]
- recommended_registry_entry: the full JSON entry for source_registry.json
- notes: any important observations
- playbook_update: new lessons learned about this venue series that would help
  future surveys (e.g. "site is Vue SPA, must parse webpack chunks",
  "abstracts not on accepted list, use ACM DL DOI lookup"). Only include
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

**增量安全**：脚本在 merge 时会保留已有记录的 enrich 字段（abstract_raw、doi、arxiv_id 等），重新抓取不会覆盖已补全的数据。

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

完成后必须验证覆盖率达到 100%：

```bash
python3 -c "
import csv
with open('paper_database/accepted_index.csv') as f:
    rows = [r for r in csv.DictReader(f) if r['conf_year'] == '<CONF_YEAR>']
has = sum(1 for r in rows if r.get('abstract_raw','').strip())
print(f'{has}/{len(rows)} ({has/len(rows)*100:.1f}%)')
"
```

### 3. Embedding 缓存构建

在 GPU 服务器上构建/增量更新 embedding 缓存。

**前置检查（硬性）**：

1. SSH 连接服务器，确认能正常连通
2. 运行 `nvidia-smi` 查看各 GPU 的显存占用和进程情况
3. 选择空闲 GPU（显存占用 < 10%），通过 `--gpus` 参数指定，避开有高占用的 GPU 以免影响其他用户

```bash
# 前置：检查 GPU 占用
ssh <server> nvidia-smi

# 构建缓存（指定空闲 GPU）
python3 $SKILL_ROOT/scripts/build_cache_multigpu.py \
  --accepted paper_database/accepted_index.csv \
  --out paper_database/embedding_cache/qwen3_8b.npz \
  --gpus 0,1
```

| 参数 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `--accepted` | 是 | accepted_index.csv 路径 | — |
| `--out` | 否 | 输出 .npz 路径 | `paper_database/embedding_cache/qwen3_8b.npz` |
| `--model` | 否 | embedding 模型名 | `Qwen/Qwen3-Embedding-8B` |
| `--batch-size` | 否 | 批大小 | `64` |
| `--max-length` | 否 | 最大 token 长度 | — |
| `--dim` | 否 | 截断维度（0=全维度） | `0`（全维度，不截断） |
| `--gpus` | 否 | 逗号分隔的 GPU ID（必须选择空闲 GPU） | 自动检测 |
| `--instruction` | 否 | query 指令前缀 | 见 config |

## 输出

| 文件 | 说明 |
|------|------|
| `paper_database/accepted_index.csv` | 基础文献索引（schema 见下方） |
| `paper_database/accepted_index_coverage_report.md` | 覆盖率报告 |
| `paper_database/embedding_cache/qwen3_8b.npz` | Embedding 缓存 |
| `$SKILL_ROOT/config/venue_playbooks/` | Venue 级经验手册（经验证的跨年份复用经验，子能力 0 的 prior knowledge 输入） |

## accepted_index.csv Schema

| 字段 | 类型 | 说明 |
|------|------|------|
| `paper_id` | string | 全局唯一标识（格式：`VENUE_YEAR_序号`） |
| `short_id` | string | 短标识 |
| `venue` | string | 会议名称（如 `ICLR`、`CVPR`） |
| `year` | int | 年份 |
| `conf_year` | string | 会议-年份标识（如 `ICLR_2025`） |
| `title` | string | 论文标题 |
| `authors` | string | 作者列表 |
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

## 新增会议流程

1. 用 `survey_sources.py` 调研该会议的公开 accepted list 情况，重点关注摘要获取途径
2. 在 `config/source_registry.json` 中添加对应 conference-year 条目（可参考调研报告中的推荐条目）
3. 运行 `build_accepted_index.py --conf-years <NEW_CONF_YEAR>` 增量抓取
4. 运行 `enrich_abstracts.py --filter <CONF_YEAR>` 补摘要（S2 batch）
5. 运行 `enrich_abstracts_fallback.py --filter <CONF_YEAR>` 补摘要（多源 fallback）
6. 验证摘要覆盖率达到 100%，未达标则 agent 用 web search 逐篇搜索补齐（见子能力 2 第三轮）
7. 在 GPU 服务器上增量更新 embedding 缓存

## 配置文件说明

### config/default_config.json

embedding 模型参数配置，包括模型名、维度、批大小、指令前缀、缓存路径等。

### config/source_registry.json

数据源注册表，定义每个 conference-year 的抓取源。每个条目包含：
- `venue` / `year` / `conf_year`：会议标识
- `status`：`active`（正常抓取）或 `skip`（跳过，需填 `skip_reason`）
- `primary_source`：主数据源（`kind`、`url`、`parser`、`expected_count`）
- `auxiliary_sources`：辅助数据源列表
- `notes`：备注

`url` 支持两种格式：
- 标准 URL：直接从网络抓取
- `fixture://` 前缀：从 `fixtures/` 目录加载离线快照（用于无法直接抓取或需要稳定复现的源）

## 经验沉淀规则

执行本 skill 后，如果发现了可复用的经验，应沉淀到对应层级的文件中。经验分三层：

**Layer 1：Venue Playbook（`$SKILL_ROOT/config/venue_playbooks/{VENUE}.md`）**

记录某个会议系列（跨年份通用）的抓取经验。每次完成子能力 0 后，主 agent 根据 subagent 返回的 `playbook_update` 字段追加更新。

适合写入的内容：
- 该系列会议站点的技术架构（如"ACM MM 系列 2023 起使用 Vue SPA，需解析 webpack chunk"）
- 摘要获取的最佳路径（如"accepted list 无摘要，需通过 ACM DL DOI 或 arXiv 补全"）
- 已知的 parser kind 和适用年份范围
- 常见坑点（如"录用列表标题可能与 proceedings 不一致，以 DOI 为准"）

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
