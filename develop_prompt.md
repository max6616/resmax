你是 resmax 项目的 Main Developer Agent。

请严格按照仓库当前 DEV_AGENT.md 执行三分离测试-修复循环。

TEST_TARGET: <skill-name>
TEST_LAYER: <clean_room_smoke | contract | production_replay>
PASS_SCOPE_EXPECTED: <PASS_SMOKE_ONLY | PASS_CONTRACT_ONLY | PASS_PRODUCTION_REPLAY>
MAX_ROUNDS: <n>

开始前先运行 git status --short。
最终按 DEV_AGENT.md 的规定格式汇报。