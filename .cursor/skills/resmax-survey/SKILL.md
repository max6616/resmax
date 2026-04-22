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
- Python 依赖：`pip install -r $SKILL_ROOT/scripts/requirements.txt`，其中 Stage 5.5.a 需要 `arxiv-to-prompt`（TeX）、`pymupdf`（PDF 文本层）、`requests`（下载）
- Stage 5.5.a 的 MinerU fallback 需要 `user-mineru` MCP 已启用（仅在 PDF 文本层也失败时才需要）

## 流程

| Stage | 内容 | 执行方式 |
|-------|------|----------|
| 0 | 数据库完整性预检 | 脚本 |
| 1 | 关键词检索 (~50) + embedding 语义检索 (~50) | 脚本 |
| 2 | 按 paper_id 去重合并 (≤100) | 脚本 |
| 3 | 逐篇元信息补充（摘要 + PDF 链接） | 脚本 |
| 3.5 | 开源信息深度补全（passthrough + HF Hub 精查 + 仓库评估 prompt 导出） | 脚本 |
| 4 | 生成无评分文献文档 + CSV + 日志 | 脚本 |
| 5 | orchestrator subagent 批量评分 → scores_raw.json | agent（单次 Task） |
| 5.5.a | 论文源文本抓取（三层：arXiv TeX + PDF 文本层 + MinerU MD）→ `paper_sources/<paper_id>/` | 脚本 + agent（mineru 兜底） |
| 5.5.b | 仓库评审：对每篇 S/A 派发 repo 评审 subagent | agent |
| 5.5.c | *（预留）* 论文正文签名提取：novelty / baselines / datasets / base models | agent（后续 skill 消费） |
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

### Stage 3.5：开源信息深度补全（脚本自动执行，可配置开关）

在 `resmax-database` 的全局轻量开源补全之后，本 stage 对检索到的 100 篇候选做精细化补充。由 `search_literature.py` 自动调用，无需额外命令。

**三级覆盖**：

- **Level A — passthrough**：从 `accepted_index.csv` 复制已有字段到候选（`code_url`、`code_is_real`、`code_stars`、`code_last_commit`、`code_primary_language`、`has_pretrained_weights`、`has_dataset`）。零网络。
- **Level B — HuggingFace Hub 精确查询**：对有 `arxiv_id` 的候选调用 HF Hub API，按 arxiv_id 匹配（tag 或 id 子串）找出挂名的模型/数据集。写入 `hf_models`、`hf_datasets`。100 个候选约 30 秒。
- **Level C — 仓库评审 prompt 导出**：对每个有 `github.com` URL 的候选生成一段结构化 prompt，写入 `deepcheck_prompts.json`。Stage 3.5 本身**不派发** agent；由 Stage 5.5（可选）在 S/A 论文确定后派发。

**配置**（`$SKILL_ROOT/config/default_config.json` 的 `openness_deepcheck` 节）：

```json
"openness_deepcheck": {
  "enabled": true,
  "run_on": "SA",
  "enable_hf_hub": true,
  "hf_rate_limit_delay": 0.3,
  "emit_repo_review_prompts": true
}
```

- `enabled`：总开关。默认 `true`。
- `enable_hf_hub`：关闭可去除 HF Hub 的网络调用（对离线场景）。
- `emit_repo_review_prompts`：是否写 `deepcheck_prompts.json`。

**产物**：`literature_research/<direction_slug>/deepcheck_prompts.json`，结构为 `{paper_id: {title, code_url, ai_score, prompt}}`。Stage 5.5 消费。

### Stage 5.5：开源情况精细检查（三子阶段）

在 Stage 5 评分结束后，对 `final_score` 为 `S`（或 `S/A`）的论文执行以下三子阶段。可以通过独立脚本 `stage5_5_deepcheck.py` 驱动整个流程，该脚本读取既有 `research_index.csv` 并写回，不依赖 Stage 1-5 的内存状态，因此可在任何时间点补跑。

```bash
python3 $SKILL_ROOT/scripts/stage5_5_deepcheck.py \
  --dir literature_research/<direction_slug> \
  --accepted paper_database/accepted_index.csv \
  --grades S    # 或 --grades S,A
```

#### 5.5.a 论文源文本抓取（三层源策略 + agent mineru 兜底）

**目的**：为 S/A 论文获取结构化的正文文本，既帮助本 Stage 挖出真实 GitHub 链接，也为未来的 novelty / SOTA / baseline 分析阶段提供共享缓存。**三种源各有不可替代的优势**，因此都保留：

| 源 | 优势 | 劣势 | 主要消费场景 |
|----|------|------|-------------|
| arXiv 扁平化 TeX | 源级保真，精确 `\cite{}`/`\url{}`/公式；可调用 LaTeX 结构（定理、图、附录） | 覆盖 < 100%（CVF/ECCV only 无 arxiv_id） | 后续正文分析（baselines、SOTA 声明、公式核对） |
| PDF 文本层（PyMuPDF） | **字符保真**：读 `/ToUnicode` CMap，`I`/`l`/`1`/`O`/`0` 不会混淆；图片可定位 | 无段落 reflow，agent 读起来乱 | **抽取 URL、email、bibkey 等字符敏感信息** |
| MinerU Markdown | 段落重排、清洁结构，适合 LLM 全文理解 | 字形 OCR 失真（CTRL-D 的 `IHe-KaiI` 被识别成 `IHe-Kail`） | agent 全文 prompt，正文语义检索 |

**脚本抓取顺序**（`paper_source_fetch.fetch_and_cache_source`，各源独立尝试，不相互阻塞）：
1. 有 `arxiv_id` → `arxiv-to-prompt` 生成 `paper.tex`，同时下载 `arxiv_source.tar.gz` 并解压到 `arxiv_source/` 保留原始多文件结构。
2. PDF 抓取走**四层 fallback 链**（见下），每层独立记录证据。
3. 主 agent 事后可以通过 MinerU MCP 补 `paper.md`，然后调 `register_mineru_md()` 登记并重新合并 URL。

**PDF 四层 fallback 链**（避开出版社反爬墙的系统性方案，核心理念是"找合法副本，而不是绕防火墙"）：

| 层 | 来源 | 覆盖的论文类型 | 合法性 |
|---|---|---|---|
| 0 | `derive_pdf_candidates`：`pdf_url` / `arxiv_id` / `openreview_forum_id` / `doi` | arXiv、OpenReview、明确 pdf_url 的会议 | 合法 |
| 1 | OA 聚合器：**Unpaywall → OpenAlex → S2 → arXiv title 搜索**（`oa_resolvers.resolve_oa_pdf_urls`） | ACM/Springer/Elsevier/IEEE 里**作者 self-archive 过副本**的论文 | 合法 |
| 2 | Sci-Hub 镜像轮询（`sci_hub.sci_hub_pdf_url`，默认开启，`--disable-sci-hub` 可关） | 老论文（≥2022 前覆盖率高），`.ru`/`.se`/`.st`/`.ee` 顺序尝试 | 灰色，可关 |
| — | 全失败 → 写入 `deepcheck_missing_pdf.json`，`category` 字段分三类 | | |

**`no_oa_copy_found` 终态**：当 OA 聚合器一致判定 `is_oa=False` **且** Sci-Hub 所有镜像都不收录时，该论文**物理上没有可自动获取的公开副本**（典型：2024 年后 ACM/Springer 论文，作者未 self-archive）。这不是可重试的故障。处理选项：(1) 从 deep-check 中移除；(2) 标记为等机构网络重试；(3) 直接找作者要。

**Layer 1 关键机制：Title→DOI 反查**。`accepted_index` 目前不存 `doi`（上游 `resmax-database` TODO），但 Layer 1 开头会自动用 title 查 OpenAlex 反查 DOI（title Jaccard ≥ 0.6 视为匹配），反查到的 DOI 立刻喂给 Unpaywall 和 Sci-Hub。这样即使上游字段缺失也能触发全链路。

**Unpaywall 需要联系 email**。默认值被 API 拒（HTTP 422），但**不影响分类结果**（OpenAlex + S2 已经够判定）。想启用建议：
```bash
export RESMAX_UNPAYWALL_EMAIL="your@email"
```

**Sci-Hub 镜像自定义**（默认 `sci-hub.ru,sci-hub.se,sci-hub.st,sci-hub.ee`）：
```bash
export RESMAX_SCI_HUB_MIRRORS="sci-hub.ru,sci-hub.st"
```

**缓存结构**（每篇论文一个独立文件夹）：

```
literature_research/<slug>/paper_sources/<safe_paper_id>/
    paper.pdf            # 原始 PDF
    paper.pdftxt         # PyMuPDF 抽的文本层（字符保真）
    paper.md             # MinerU 产物（agent 通过 MCP 写入）
    paper.tex            # arxiv-to-prompt 扁平化 TeX
    arxiv_source.tar.gz  # arXiv e-print 原始 tarball
    arxiv_source/        # 解压后的多文件源树
```

**URL 抽取与并集**：脚本在所有文本源（TeX、pdftxt、md）上跑正则，抽 `github.com/<owner>/<repo>` 和 `<owner>.github.io/...` 两类。合并时**字符保真源（TeX/pdftxt）优先，MD 退后**，写入 `paper_github_urls`（`;` 分隔）。下游 agent 看到第一个 URL 就是最可信的。

**主 agent 兜底 mineru 的脚本片段**（当 TeX 和 PDF 文本层都失败，或想给 agent 额外的结构化全文）：

```python
from search_literature_lib.paper_source_fetch import register_mineru_md
from pathlib import Path

cache = Path('literature_research/<slug>/paper_sources')
# 从 deepcheck_missing_source.json 或 CSV 筛选需要 MinerU 的条目
md_text = Path(extract_path).read_text(encoding='utf-8')
register_mineru_md(paper_id, md_text, cache)
# 随后重跑 stage5_5_deepcheck.py 以复用缓存并合并 URL
```

MinerU Flash 模式免费但每文件 20 页上限；实践中传 `pages: "1-12"` 足够覆盖方法 + 实验的开源声明。

#### 5.5.b 仓库评审派发

读取 `deepcheck_prompts.json`（脚本产出），对每个条目派发一个 `generalPurpose` subagent。prompt 已经包含：
- 所有已知链接（`code_url` / `paper_github_urls` / project page）
- 统一的 JSON 返回格式（包含 `resolved_repo_url` 字段，允许 agent 覆盖原 `code_url` 为真实 repo）

```python
# 伪代码 — Stage 5.5.b
import json
from search_literature_lib.openness_deepcheck import apply_repo_review_results
from search_literature_lib.models import load_research_index, write_research_index

with open(out_dir / 'deepcheck_prompts.json') as f:
    prompts = json.load(f)

reviews: dict[str, dict] = {}
for pid, p in prompts.items():
    resp = Task(prompt=p['prompt'], subagent_type='generalPurpose')
    try:
        reviews[pid] = json.loads(resp)
    except Exception:
        continue

candidates = load_research_index(out_dir / 'research_index.csv')
apply_repo_review_results(candidates, reviews)
write_research_index(out_dir / 'research_index.csv', candidates)
```

**关键设计点**：
- prompt 不再硬性要求 `github.com/`——只要 `code_url` 或 `paper_github_urls` 有一个非空就会生成。这是为了覆盖 CV / 3DGS 社区常见的"只发项目页"模式。
- agent 的职责是**从项目页追到真实 GitHub repo** 并回写 `resolved_repo_url`；本脚本的 `apply_repo_review_results` 会用 `resolved_repo_url` 覆盖原 `code_url`（当新 URL 含 `github.com` 而原值不含时）。
- 三种"无法评审"的情况要闭环处理：`code_quality="project_page_only"`（有项目页无 repo）、`code_quality="dead"`（404 或陈旧）、`code_quality="unknown"`（连入口都没有，主 agent 在 apply 后手工标记）。

#### 5.5.c 论文正文签名提取（预留，未来阶段消费）

`CandidatePaper` 已经预留了以下字段，**本 Stage 不赋值**，交给未来的分析 skill（novelty-check、ablation-planner、result-to-claim 等）基于 `paper_sources/` 缓存做派发：

- `novelty_claims`：论文声明的创新点
- `baselines_used`：实验中引用的基线方法（从 `\cite{}` 或 "we compare against" 段落提取）
- `datasets_used`：实验使用的数据集
- `base_models_used`：底座模型（LLM / VLM / Diffusion）
- `sota_claims`：SOTA 声明
- `reproducibility_signal`：正文层面的可复现性判断（`full` / `partial` / `none`）

**跳过条件**：`deepcheck_prompts.json` 为空（例如所有 S/A 论文都没有代码链接、也没挖到源文本）。

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
| `research_index.csv` | 方向级 research index，含评分和开源深度检查字段 |
| `scores_raw.json` | orchestrator 产出的原始评分（中间文件） |
| `deepcheck_prompts.json` | Stage 5.5.b 的仓库评审 prompt（中间文件） |
| `deepcheck_missing_source.json` | Stage 5.5.a 输出：TeX 和 PDF 文本层都失败的论文清单（主 agent 用 mineru 兜底或放弃） |
| `deepcheck_missing_pdf.json` | Stage 5.5.a 输出：PDF 全 fallback 失败的论文，每条带 `category`（`no_oa_copy_found` / `fallback_failed` / `unknown`）和 `fallback_diagnostic`（OA API + Sci-Hub 完整证据链）。`no_oa_copy_found` 是终态不可重试 |
| `deepcheck_reviews.json` | Stage 5.5.b 的 agent 原始 JSON 返回（可复核） |
| `deepcheck_results.md` | Stage 5.5.b 人类可读的评审表格 |
| `paper_sources/<paper_id>/{paper.pdf,paper.pdftxt,paper.md,paper.tex,arxiv_source.tar.gz,arxiv_source/}` | Stage 5.5.a 源文本缓存（per-paper 子目录；供 5.5.c 和后续 skill 共享） |
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
| `openreview_rating_mean` | float | OpenReview 平均评分（从 `accepted_index.csv` 的 `review_score_mean` 字段读取，由 `resmax-database` 子能力 3 预填充） |
| `openreview_confidence_mean` | float | OpenReview 平均置信度（从 `accepted_index.csv` 的 `review_confidence_mean` 字段读取） |
| `openreview_decision` | string | OpenReview 决定（从 `accepted_index.csv` 的 `decision` 字段读取） |
| `presentation_type` | string | 展示类型（oral / poster / spotlight） |
| `citation_count` | int | 引用数 |
| `code_url` | string | 代码仓库 URL（passthrough，Stage 3.5 Level A） |
| `code_is_real` | string | 仓库存在且非空（passthrough） |
| `code_stars` | int | GitHub star 数（passthrough） |
| `code_last_commit` | string | 最近 push 时间 ISO8601（passthrough） |
| `code_primary_language` | string | 主语言（passthrough） |
| `has_pretrained_weights` | string | 摘要层 weights 扫描结果（`yes`/`no`/`unknown`，passthrough） |
| `has_dataset` | string | 摘要层 dataset 扫描结果（`yes`/`no`/`unknown`，passthrough） |
| `hf_models` | string | 分号分隔的 HuggingFace 模型 repo id（Stage 3.5 Level B） |
| `hf_datasets` | string | 分号分隔的 HuggingFace 数据集 repo id（Stage 3.5 Level B） |
| `code_quality` | string | 仓库评审等级（`full`/`partial`/`skeleton`/`dead`/`project_page_only`/`unknown`，Stage 5.5.b 写入） |
| `reproduction_readiness` | int | 可复现评估（0-5 分，Stage 5.5.b 写入） |
| `source_cache_path` | string | Stage 5.5.a 源文本缓存的 per-paper 子目录名（位于 `paper_sources/` 下） |
| `source_cache_type` | string | 逗号分隔的存在源 tag：`tex`、`pdf`、`md` 的子集（例 `tex,pdf` 或 `pdf,md`），`none` 表示全部失败 |
| `paper_github_urls` | string | 从源文本抽取的 `;` 分隔 URL 列表（含 `github.com` 和 `*.github.io`） |
| `novelty_claims` | string | *（预留，Stage 5.5.c / 下游 skill 填充）* 创新点声明 |
| `baselines_used` | string | *（预留）* 实验引用的基线方法 |
| `datasets_used` | string | *（预留）* 实验数据集 |
| `base_models_used` | string | *（预留）* 底座模型（LLM/VLM/Diffusion） |
| `sota_claims` | string | *（预留）* SOTA 声明摘要 |
| `reproducibility_signal` | string | *（预留）* 正文层面的可复现性判断 |

## 4DGS editing 方向执行经验（2026-04）

在本方向上跑通 Stage 5.5 两轮后沉淀的关键结论（S 论文共 11 篇）：

1. **accepted_index.csv 的 `arxiv_id` 覆盖不完整**：11 篇 S 论文中只有 3 篇原生带 arxiv_id；至少 2 篇（ICLR Real-time 4DGS、NeurIPS D-MiSo）在 arXiv 上实际存在但未被 resmax-database 关联。**后续 resmax-database 改进方向**：对 OpenReview / CVF open-access 源补做 arxiv ID 反查。
2. **accepted_index.csv 的 `code_url` 大小写被抓取时 `.lower()` 了**：`IHe-KaiI.github.io` 被存成 `ihe-kaii.github.io`，而 GitHub Pages 路由对大小写敏感，直接打不开。**resmax-database 待修**：URL 抓取时保持原始大小写，不要做任何归一化。
3. **CV 社区的 `code_url` 绝大多数指向 `*.github.io` 项目页而非 `github.com` repo**：11 篇 S 里 8 篇有 `code_url`，其中 0 篇是 `github.com`。因此 5.5.b 的 prompt 不能硬性要求 `github.com/`，必须允许 agent 从项目页追到真实 repo。
4. **MinerU MD 在字符敏感抽取上不可信**（CTRL-D 典型案例）：MinerU 把项目页 URL 里的大写 `I` 识别成小写 `l`，输出 `IHe-Kail.github.io`（实为 `IHe-KaiI.github.io`）。这类字形 OCR 混淆只有 PDF 文本层（`/ToUnicode` CMap）能规避。**所以 5.5.a 升级为三层并行**：TeX + PDF 文本层 + MinerU MD，URL 并集按字符保真优先排序（TeX/pdftxt > MD），下游 agent 看到的第一个 URL 就是最可信的。
5. **PDF 文本层 vs MinerU MD 的互补性**：PDF 文本层 char-faithful，适合抽 URL/email/bibkey；MinerU MD 结构清洁、段落 reflow，适合给 agent 做正文理解 prompt；都应该保留。arXiv TeX 是第三条独立路径，保留公式和 `\cite{}` 结构，**对 5.5.c 及之后的 baseline/dataset 提取最有价值**。
6. **每篇论文保留 per-paper 子目录**（`paper_sources/<paper_id>/paper.{pdf,pdftxt,md,tex}` + `arxiv_source/`）方便多源并存、避免扁平目录下 `.tex`/`.md` 互相覆盖或被归并压缩。
7. **3 篇 S 论文无法派发 repo review**（和源数量多少无关，是正文里确实没有任何 URL 提示）：`D²Gaussian`（完全零源）、`Instruct 4D-to-4D`（PDF+MD 两份都无）、`InterGSEdit`（TeX+PDF 两份都无）。CSV 标记为 `code_quality="unknown"`，不伪造评审结论。**后续改进方向**：对 unknown 的论文让 agent 以 title+作者在 GitHub 搜一遍兜底，而不是完全依赖源里抽 URL。
8. **二轮执行对比**：从"仅 TeX or 仅 MinerU MD 单源"升级到"三层并行"后，11 篇 S 中 7 篇拿到 ≥ 2 个源（可交叉验证），CTRL-D 从 `project_page_only`（0/5） 改评为 `full`（5/5，`github.com/IHe-KaiI/CTRL-D`）。
9. **三轮升级：PDF 抓取的四层 fallback 链**（2026-04 第三次迭代）：针对 ACM/Springer 这类被 Cloudflare 拦的 DOI（如 D²Gaussian 的 `10.1145/3746027.3754728`），不去硬刚反爬墙，而是系统性地查"**有没有合法 OA 副本**"。链路：Layer 0 直接 URL → Layer 1 Unpaywall+OpenAlex+S2+arXiv title 搜索 → Layer 2 Sci-Hub 镜像轮询 → 全失败标 `no_oa_copy_found`。**活体验证**：D²Gaussian 被 OpenAlex/S2 一致判定 `is_oa=False`、Sci-Hub 四个镜像都查无此文，正确落到 `no_oa_copy_found` 终态；这是作者未 self-archive 的真实无解情形（2024 年后的新 ACM 论文此类比例较高）。**关键子机制：Title→DOI 反查**——因为 `accepted_index` 目前不存 `doi`（上游 TODO），Layer 1 开头先用 title 查 OpenAlex 反查 DOI（Jaccard ≥ 0.6），反查到后喂 Unpaywall 和 Sci-Hub，从而对上游字段缺失鲁棒。
10. **`resmax-database` 上游 TODO 汇总**（影响本 skill fallback 链的数据缺失）：
    - `accepted_index.csv` 缺 `doi` 列。当前由 `resolve_oa_pdf_urls` 内部 title→DOI 反查兜底；若上游补齐可省去 OpenAlex 一次额外查询。
    - NeurIPS/ICLR/ICML 论文的 `openreview_forum_id` 普遍为空（应为 OpenReview 上就能抓到）。当前 `derive_pdf_candidates` 能在该字段存在时直接命中 OpenReview PDF；若上游补齐可为 31 篇"只有 venue 信息"的论文打开 Layer 0 直达通路，减少 Layer 1/2 的网络开销。
    - `code_url` 和 URL 字段全局 `.lower()` bug（见经验 2）。
