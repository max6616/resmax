---
name: resmax-survey
description: 从基础文献库中为指定研究方向检索相关论文。双路检索（关键词+embedding）→ 合并去重 → 元信息补充 → subagent 逐篇评分 → 主 agent review → 输出带评分的文献列表。
---

# resmax-survey

## 所属体系

本 skill 属于 resmax 自动化科研文献基础设施，与 `resmax-database`、`resmax-embedding` 协同工作，通过文件系统共享数据、无运行时耦合。

数据流：`resmax-database` 产出基础文献索引 → `resmax-embedding` 构建 embedding 缓存 → `resmax-survey`（本 skill）消费索引和缓存进行方向级检索与评分。

共享数据目录：
| 目录 | 归属 | 说明 |
|------|------|------|
| `paper_database/` | resmax-database 产出 | 全量基础文献索引 |
| `paper_database/embedding_cache/` | resmax-embedding 产出 | Embedding 缓存 |
| `literature_research/<方向>/` | resmax-survey 产出 | 方向级检索结果、评分文献列表、筛选日志 |

设计原则：CSV 为唯一权威索引；批量优先、逐篇兜底；Skill 独立；脚本开箱即用；增量更新。

## 路径约定

```bash
SKILL_ROOT=.cursor/skills/resmax-survey
```

下文所有命令和路径中的 `$SKILL_ROOT` 均指本 skill 的根目录。改名时只需修改上方赋值。

## 触发词

"检索文献", "search literature", "找相关论文", "文献调研", "方向调研", "literature search"

## 前置条件

- `paper_database/accepted_index.csv` 已存在（由 resmax-database 产出）
- `paper_database/embedding_cache/qwen3_8b.npz` 已存在（由 resmax-embedding 产出）

## 流程

| Stage | 内容 | 执行方式 |
|-------|------|----------|
| 0 | 数据库完整性预检 | 脚本 |
| 1 | 关键词检索 (~50) + embedding 语义检索 (~50) | 脚本 |
| 2 | 按 paper_id 去重合并 (≤100) | 脚本 |
| 3 | 逐篇元信息补充（摘要 + PDF 链接） | 脚本 |
| 4 | 生成无评分文献文档 + CSV + 日志 | 脚本 |
| 5 | orchestrator subagent 批量评分 → scores_raw.json | agent（单次 Task） |
| 6 | 主 agent review 评分合理性 | agent |
| 7 | 按评分排序，生成最终文献列表 | agent |

### Stage 0：数据库完整性预检（硬性，必须首先执行）

运行预检脚本验证基础文献库的完整性。如果预检失败（exit code 1），必须停止后续流程，将报告中的问题反馈给用户，建议先用 `resmax-database`（CSV 问题）或 `resmax-embedding`（缓存问题）修复。

```bash
python3 $SKILL_ROOT/scripts/preflight_check.py \
  --csv paper_database/accepted_index.csv \
  --cache paper_database/embedding_cache/qwen3_8b.npz
```

脚本输出 JSON 报告，包含：
- `csv.status`：CSV 检查结果（会议覆盖、标题完整性、摘要覆盖率、paper_id 唯一性）
- `embedding.status`：embedding 缓存检查结果（文件存在性、与 CSV 的 paper_id 对齐度）
- `overall`：`PASS` 或 `FAIL`

`overall=FAIL` 时禁止继续执行 Stage 1-7。

### Stages 1-4：脚本自动执行

```bash
python3 $SKILL_ROOT/scripts/search_literature.py \
  --accepted paper_database/accepted_index.csv \
  --direction "研究方向描述" \
  --keywords "关键词1,关键词2,关键词3" \
  --out-dir literature_research/<direction_slug>
```

| 参数 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `--accepted` | 是 | accepted_index.csv 路径 | — |
| `--direction` | 是 | 研究方向自然语言描述 | — |
| `--keywords` | 是 | 逗号分隔的检索关键词 | — |
| `--out-dir` | 否 | 输出目录 | `literature_research/<direction_slug>` |
| `--config` | 否 | 配置 JSON 路径 | 自动检测 |
| `--cache-path` | 否 | embedding 缓存 .npz 路径 | 从 config 读取 |
| `--device` | 否 | query 编码设备 | `cuda`/`mps`/`cpu` 自动选择 |
| `--dim` | 否 | embedding 维度（0=使用 config） | `0` |
| `--embedding-top-k` | 否 | embedding 检索 top-K | `50` |
| `--keyword-top-k` | 否 | 关键词检索 top-K | `50` |
| `--max-candidates` | 否 | 合并后最大候选数 | `100` |

### Stages 5-7：agent 执行（硬性）

#### Stage 5: orchestrator subagent 评分

主 agent 通过单次 Task 调用将全部评分工作委托给一个 orchestrator subagent。orchestrator 内部自行分批、派发 scorer subagent、收集结果、处理重试，最终将所有评分写入 `scores_raw.json`。主 agent 的 context 中只有一次 Task 调用的开销。

执行步骤：

1. 用 `build_orchestrator_prompt()` 生成 orchestrator 的完整指令
2. 将该 prompt 发给一个 subagent（`subagent_type="generalPurpose"`）
3. orchestrator 内部：读取 `research_index.csv` → 分批 → 派发 scorer subagent（`model="fast"`）→ 收集评分 → 写入 `scores_raw.json`
4. orchestrator 返回后，主 agent 用 `load_scores_file()` 读取评分结果

```python
# 伪代码 — Stage 5 orchestrator 调用
from search_literature_lib.subagent_scorer import (
    build_orchestrator_prompt, load_scores_file, SCORES_RAW_FILENAME,
)

prompt = build_orchestrator_prompt(
    research_index_path=str(out_dir / 'research_index.csv'),
    direction=direction,
    keywords=keywords,
    out_dir=str(out_dir),
    scorer_lib_path=str(lib_path),
)
response = Task(prompt=prompt, subagent_type="generalPurpose")

scores = load_scores_file(str(out_dir / SCORES_RAW_FILENAME))
```

#### Stage 6+7: apply_scores 统一写入（硬性）

读取 `scores_raw.json` 后，调用 `apply_scores()` 一次性完成 review + 写入 + 日志更新。禁止手动赋值 `ai_score`/`final_score` 等字段。

`apply_scores()` 内部会：
- 设置 `ai_score`, `ai_reason`（subagent 原始评分）
- 调用 `review_score()` 自动检查矛盾并修正（设置 `review_adjusted`, `review_adjust_reason`）
- 设置 `final_score`, `importance`
- 更新 `FilterLog` 记录

```python
# 伪代码 — Stage 6+7 统一写入
from search_literature_lib.subagent_scorer import apply_scores
from search_literature_lib.filter_logger import FilterLog
from search_literature_lib.literature_doc import generate_scored
from search_literature_lib.models import write_research_index

log = FilterLog.load_json(out_dir / 'filter_log_state.json')
papers = apply_scores(candidates, scores, direction, log)

papers.sort(key=lambda p: ({'S':0,'A':1,'B':2,'C':3}.get(p.final_score, 4), p.venue, p.title))

write_research_index(out_dir / 'research_index.csv', papers)
generate_scored(papers, direction, out_dir / 'literature_list.md')
log.save_json(out_dir / 'filter_log_state.json')
log.write(out_dir / 'filter_log.md')
```

## 执行约束（硬性）

1. **orchestrator 模式**：Stage 5 必须通过单次 Task 调用委托给 orchestrator subagent，禁止主 agent 自行循环分批评分
2. **paper_id 是唯一匹配键**：评分结果必须通过 `paper_id` 匹配写回，禁止依赖列表索引、序号或标题
3. **prompt 必须由库函数生成**：orchestrator prompt 用 `build_orchestrator_prompt()`，禁止手写
4. **中间文件传递**：orchestrator 通过 `scores_raw.json` 传递评分结果，主 agent 通过 `load_scores_file()` 读取
5. **从 JSON 恢复日志**：从 `filter_log_state.json` 加载 stages 1-4 日志状态，追加 stages 5-7 数据
6. **有摘要不给 PDF**：有摘要时只提供摘要，无摘要时才提供 PDF URL
7. **scorer subagent 工具限制**：scorer subagent 只允许用 WebFetch 读 PDF，禁止调用 Shell 等工具

## 输出

所有输出保存在 `literature_research/<direction_slug>/`：

| 文件 | 说明 |
|------|------|
| `research_index.csv` | 方向级 research index，含评分 |
| `scores_raw.json` | orchestrator 产出的原始评分（中间文件） |
| `literature_list.md` | 按评分排序的文献列表 |
| `filter_log.md` | 可读筛选日志 |
| `filter_log_state.json` | 可恢复日志状态 |

## research_index.csv Schema

在 `accepted_index.csv` 基础字段（见 [resmax-database/SKILL.md](../resmax-database/SKILL.md)）之上，增加以下方向级检索与评分字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `state` | string | 候选状态 |
| `filter_source` | string | 进入候选集的来源（`keyword` / `embedding` / `both`） |
| `keyword_hits` | string | 命中的关键词列表 |
| `embedding_score` | float | embedding 余弦相似度 |
| `ai_score` | string | subagent 原始评分（`S` / `A` / `B` / `C`） |
| `ai_reason` | string | subagent 评分理由 |
| `review_adjusted` | string | 主 agent review 后是否调整（`yes` / `no`） |
| `review_adjust_reason` | string | 调整理由 |
| `final_score` | string | 最终评分（`S` / `A` / `B` / `C`） |
| `importance` | string | 重要性标记 |
| `core_or_edge` | string | 核心论文 / 边缘论文 |
| `tags` | string | 标签 |
| `topic_bucket` | string | 主题分桶 |
| `pdf_path` | string | 本地 PDF 路径 |
| `has_abstract` | bool | 是否有摘要 |
| `has_pdf_link` | bool | 是否有 PDF 链接 |
| `pdf_url` | string | PDF URL |
| `openreview_rating_mean` | float | OpenReview 平均评分 |
| `openreview_confidence_mean` | float | OpenReview 平均置信度 |
| `openreview_decision` | string | OpenReview 决定 |
| `presentation_type` | string | 展示类型（oral / poster / spotlight） |
| `citation_count` | int | 引用数 |
