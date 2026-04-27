# TEST_CASE_ID: T001-smoke

## Skill under test

Source skill path:

.agents/skills/your-skill/SKILL.md

## User task

Act as a normal user and use the skill to complete the following task:

对以下的研究方向完整执行resmax-survey，resmax-idea，resmax-review

intent: "4DGS editing, especially real-time editing and feed-forward Gaussian editing, aiming for breakthroughs in action editing accuracy, temporal/action coherence, and the achievable magnitude of action changes. Target venue: SIGGRAPH. Compute budget: 4x5090. Timeline: 4 weeks."
direction_slug: "e2e_fulltest_4dgs_editing"
output_dir: "literature_research/e2e_fulltest_4dgs_editing"
target_venue: "SIGGRAPH"
compute_budget: "4x5090"
timeline_weeks: 4

## Inputs

使用现有的由resmax-database和resmax-embedding创建的数据库paper_database

## Expected outputs

The executor must create outputs under:

<run-snapshot>/outputs/T001-smoke/

Expected artifacts:

<run-snapshot>/outputs/T001-smoke/result.md

## Must follow

- Must read and follow the skill under test.
- Must not modify `SKILL.md`.
- Must not modify this test case.
- Must not use artifacts outside the current run snapshot.
- Must stop on the first unexpected failure.
- Must report warnings and errors.

## Must not do

- No patching the skill.
- No fallback strategy unless explicitly permitted by the skill.
- No partial success claims.
- No reuse of old run artifacts.
- No editing files outside the designated output directory, unless the skill explicitly requires it.

## Pass criteria

- Executor returns `STATUS: PASS`.
- Verifier returns `VERDICT: PASS`.
- Expected artifacts exist.
- Expected artifacts satisfy the artifact validation rules.
- No unexplained errors or warnings occurred.
- The skill file is not modified in the run snapshot.
- The test case file is not modified in the run snapshot.
- The result does not depend on previous run artifacts.

## Artifact validation

The file `<run-snapshot>/outputs/T001-smoke/result.md` must satisfy all of the following:

- It exists.
- It is non-empty.
- It contains no placeholder text such as `TODO`, `FIXME`, `<placeholder>`, or `<REPLACE_WITH_...>`.
- It directly addresses the user task.
- It follows the output requirements defined by the skill.

## Fail criteria

The test fails if any of the following occur:

- Any expected artifact is missing.
- Any expected artifact is not validated.
- The executor modifies the skill.
- The executor modifies this test case.
- Any unexplained warning occurs.
- Any unexplained error occurs.
- Any command fails.
- Any dependency is missing.
- Any permission issue occurs.
- Any workaround is used without explicit permission from the skill.
- The executor relies on previous run artifacts.
- The executor claims success without verifying the expected artifacts.