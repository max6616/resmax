# Resmax Test Layers

本目录中的现有 pytest、fixture 和 validator 默认属于 contract tests。

contract tests 的目标是快速验证稳定契约，包括 schema、manifest、路径、hash、状态机、validator、字段约束、fixture 一致性和小型 artifact 的结构关系。它们适合 Main Developer Agent 在开发和修复期间频繁运行。

## What Contract Tests Prove

contract tests 可以证明：

- fixture 与 schema / validator 保持一致。
- 失败 fixture 会按预期失败。
- manifest、hash、路径、计数、状态位等稳定契约可被校验。
- 相关脚本在小输入、临时目录或 synthetic artifact 上保持基本行为。
- 修改没有破坏已知 contract。

contract tests 不能证明：

- 独立 `skill_executor` 能按 `SKILL.md` 完成任务。
- 真实数据库、embedding cache、source cache 或外部服务可用。
- 真实数据规模下流程稳定。
- 自然语言产物质量达到生产标准。
- 当前变更已经 release-ready。

因此 contract pass 的最终状态只能是 `PASS_CONTRACT_ONLY`。

## Clean-Room Smoke Tests

clean-room smoke tests 由 agent 流程驱动，不由 pytest 直接替代。

这一层应启动全新的 `skill_executor`，提供明确的 `TEST_TARGET`、`TEST_LAYER=clean_room_smoke`、固定 fixture 或小型样例，并优先输出到 `/tmp/resmax_<skill>_<case>` 或明确的测试输出目录。

clean-room smoke 的目标是验证 skill 文档和最小流程是否可执行。通过后只能声明 `PASS_SMOKE_ONLY`，不能作为 production 或 release pass。

## Production Replay Tests

production replay 也由 agent 流程驱动，不由 pytest 直接替代。

这一层应启动全新的 `skill_executor`，使用真实用户目标、真实数据库、真实 cache、真实 source materialization 和真实 production 输出目录完整执行，并由全新的 `skill_verifier` 做只读审计。

production replay 需要检查产物内容质量，而不只是文件存在、命令退出码或 validator PASS。只有这一层通过后才能声明 `PASS_PRODUCTION_REPLAY`。

## Adding Tests

新增 pytest 时优先保持 contract-test 定位：

- 使用 `tests/fixtures/**`、`tmp_path` 和小型结构化输入。
- 避免网络、GPU、外部 API、真实 token 和大规模生产数据依赖。
- 明确测试的是 schema、manifest、路径、hash、状态机、validator、fixture 或稳定字段约束。
- 对失败 fixture 写出明确失败原因，避免把业务流程判断隐藏在测试脚本里。
- 不为了 smoke 或 production replay 大规模重排本目录。

如果某个测试开始依赖真实生产数据、LLM 质量判断、外部服务或多轮 agent 执行，应把它移出 pytest contract 语义，改由 clean-room smoke 或 production replay 流程记录在 `skill-test-logs/**` 中。
