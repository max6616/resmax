# HF_DailyPapers Venue Playbook

## 基本信息

- 全称: HuggingFace Daily Papers 社区精选
- 数据源: HuggingFace Daily Papers API
- 类型: 非同行评审信源（社区投票筛选）
- 收录机制: 任何人可提交 arXiv 论文，社区用户投票（upvote），按 upvotes 阈值过滤

## 数据源

- Primary: HF Daily Papers API (`hf_daily_papers` parser)
- API 端点: `https://huggingface.co/api/daily_papers`
- 认证: 无需 API key
- 分页: 按 `date` 参数逐天遍历（`skip` 参数不可用，API bug）

## 筛选阈值

| 年份 | minUpvotes | 典型入库量 |
|------|-----------|-----------|
| 2024 | 30 | ~320 |
| 2025 | 30 | ~860 |
| 2026 | 15 | ~960（部分年） |

2026 年使用更低阈值（15），因为年份不完整，upvotes 积累时间短。

## 增量运行

```bash
python3 build_accepted_index.py --conf-years HF_DailyPapers_2026
# 或一次跑全部年份（耗时较长）
python3 build_accepted_index.py --conf-years HF_DailyPapers_2024,HF_DailyPapers_2025,HF_DailyPapers_2026
```

耗时：每年约 10-15 分钟（~260 活跃天 × ~2 秒/天）。

## 去重

- 入库阶段：`dedup_against_peer_reviewed` 移除已在同行评审 venue 中的论文
- 跨信源：HF_DailyPapers 优先级低于 ArXiv_HiCite（同一篇论文保留 ArXiv_HiCite 版本）

## 已知经验

- Python `urllib` 无法连接 huggingface.co（OpenSSL/TLS 兼容性问题），fetcher 使用 `subprocess.run(curl)` 作为 HTTP 客户端
- `upvotes` 字段在 `paper.upvotes`（嵌套在 paper 对象内），不在外层 entry 上
- `date` 端点返回该天提交的论文，upvotes 是累计值（非当天值），可靠
- 周末和节假日通常无论文提交（empty response），fetcher 自动跳过
- `acceptance_type` 固定为 `Community Selected`
- `extras.hf_upvotes` 保存投票数，可用于下游排序
- 该信源间接覆盖了几乎所有头部 AI 公司技术报告（GPT/Claude/Gemini/Llama/DeepSeek 等），省去逐站写 HTML parser 的成本
