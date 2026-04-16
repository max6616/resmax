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

## 路径约定

```bash
SKILL_ROOT=.cursor/skills/resmax-database
```

下文所有命令和路径中的 `$SKILL_ROOT` 均指本 skill 的根目录。改名时只需修改上方赋值。

## 触发词

"建文献库", "build literature base", "更新accepted", "刷新索引", "build cache", "补摘要", "增量更新文献库"

## 四个子能力

### 0. 数据源调研（新增会议的前置步骤）

在抓取任何新会议数据前，必须先调研该会议的公开 accepted list 情况，确认可用数据源及其字段覆盖（尤其是摘要的获取途径）。

```bash
python3 $SKILL_ROOT/scripts/survey_sources.py \
  --venues ICLR,CVPR \
  --years 2025,2026 \
  --out paper_database/source_survey_reports
```

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `--venues` | 是 | 逗号分隔的会议名称（大小写不敏感） | `ICLR,CVPR,NeurIPS` |
| `--years` | 是 | 逗号分隔的年份 | `2025,2026` |
| `--out` | 是 | 调研报告输出目录 | `paper_database/source_survey_reports` |

脚本会自动探测每个 venue-year 的官方源（Virtual Conference JSON、Proceedings、CVF OpenAccess、Virtual HTML）和 GitHub 社区数据集，生成调研报告并推荐 `source_registry.json` 条目。

调研报告中需重点关注：
- 主数据源是否包含 `abstract` 字段
- 是否有辅助源可补充摘要（如 OpenReview、arXiv）

### 1. Accepted list 抓取

从 AI 顶会官方源抓取 accepted 论文列表，合并写入 `paper_database/accepted_index.csv`。

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

**第三轮：orchestrator subagent 搜索引擎兜底（硬性）**

主 agent 通过单次 Task 调用将全部兜底搜索委托给一个 orchestrator subagent。orchestrator 内部自行分批、派发 searcher subagent 执行 web search、收集结果，最终将找到的摘要写入 `enrich_results.json`。主 agent 读取结果后写回 CSV。

执行步骤：

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
| `paper_database/source_survey_reports/` | 数据源调研报告 |

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
