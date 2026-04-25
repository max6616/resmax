---
name: resmax-worklog
description: Summarize Resmax daily work from the fixed Codex conversation log into the fixed Obsidian work log. Use when the user says "总结今天工作", "今天工作日志", "记录今天工作", "把今天工作写到工作日志", or asks to summarize today's work from .codex/response-summary-log.md.
---

# resmax-worklog

## 目标

把当天 Codex 对话日志整理成一段便于未来快速回顾的工作日志。重点是记录当天推进了哪些主线、为什么重要、项目方向发生了什么变化，而不是复制执行记录。

固定输入：

```text
/Users/zhangzhao/Code/resmax/.codex/response-summary-log.md
```

同时查看当天本地日期的项目 git 提交记录，作为校准主线和关键事实的参考源：

```bash
git log --since="YYYY-MM-DD 00:00" --until="YYYY-MM-DD 23:59:59" \
  --date=iso --pretty=format:'%h %ad %s'
```

固定输出：

```text
/Users/zhangzhao/Library/Mobile Documents/iCloud~md~obsidian/Documents/工作日志/工作日志.md
```

## 执行流程

1. 读取 `response-summary-log.md` 中当天本地日期的所有 `## YYYY-MM-DDT...` 记录。
2. 查看当天 git 提交记录；如果有提交，记录 commit hash 和 message 的顶层意义。
3. 读取工作日志文件，确认是否已有 `## YYYYMMDD` 条目。
4. 将当天对话记录和 git 提交记录归并成 4-7 条主线摘要。
5. 如果当天条目已存在，优先改写该条目；不要重复追加同一天标题。
6. 写入后读取尾部或该章节做验证，确认格式和内容符合要求。

写入 iCloud Obsidian 路径时可能需要沙箱授权。需要写入时直接请求授权，不要改写到临时替代路径。

## 工作日志写法

工作日志是给未来自己快速恢复上下文看的，不是 agent 执行清单。

应该写：

- 按主线总结，而不是按每个 turn 罗列。
- 记录“做成了什么”和“这件事对项目意味着什么”。
- 用项目层语言表达，例如“数据分发与初始化闭环”“survey 目标升级”“review 数据质量修正”。
- 保留少量关键事实：重要数据规模、关键结论、重要 commit、用户明确的方向转变。
- 每条 1-2 句话，整体保持可扫读。

不要写：

- 不要罗列大量文件路径、字段名、脚本名、项目名或 agent 名。
- 不要把调研对象列成长串；应抽象为“自动科研 agent 调研”“通用 agent runtime 调研”“机制提炼”等主线。
- 不要堆实现细节，例如 schema 字段、具体函数、临时命令、每次验证输出。
- 不要把日志写成 PR changelog、commit 列表、命令记录或会议纪要。
- 不要为了完整性牺牲可读性；工作日志允许舍弃低层细节。

## 归纳规则

将原始对话压缩成主线时，优先保留这些信息：

1. 项目目标是否发生变化。
2. 是否完成一个可复用闭环。
3. 是否修正了重要数据质量或流程边界问题。
4. 是否新增了长期有用的 skill、配置、文档或机制。
5. 是否形成了对未来开发有约束力的设计原则。
6. 是否有重要提交或外部仓库状态变化。

git 提交记录用于发现对话日志里可能漏掉的落地节点，或确认当天主线是否已经进入版本历史。只有当 commit 本身代表明确阶段性收束时，才在工作日志中用一句话写它的顶层意义；不要逐条抄 commit message。

如果某项工作只有临时排查价值，除非它改变了后续路线，否则不要写进当天主线。

## 推荐格式

```markdown
## YYYYMMDD
- 完成某条主线。说明它把项目从什么状态推进到什么状态，以及后续为什么更稳或更清晰。
- 修正某个关键问题。说明问题本质和最终边界，不展开调试过程。
- 围绕某个方向做方案迭代。说明目标如何变化，以及沉淀出的核心机制。
```

## 质量检查

写完后自查：

- 未来 1 分钟内能否读懂今天最重要的 3-5 件事？
- 是否出现了连续 5 个以上的项目名、文件名或字段名？如果有，压缩成机制或主线。
- 是否能看出“为什么这天的工作重要”，而不只是“今天做过什么”？
- 是否没有重复当天标题？
