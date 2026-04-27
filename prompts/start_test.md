Read and follow `prompts/skill_dev.md`.

Test case:

skill-tests/cases/T001-smoke.md

Skill under test:

.agents/skills/your-skill/SKILL.md

Required loop:

1. Create a fresh run snapshot using:

   skill-tests/scripts/prepare-run.sh T001-smoke

2. Spawn a fresh `skill_executor` custom subagent to execute the test inside the fresh snapshot.

3. The executor must not modify the skill, must not modify the test case, and must stop at the first unexpected failure.

4. After the executor returns `PASS`, `FAIL`, or `NEEDS_INPUT`, spawn a fresh `skill_verifier` custom subagent to verify the run.

5. Do not accept executor `PASS` unless verifier also returns `PASS`.

6. If the run fails, analyze executor and verifier reports.

7. Modify only the source skill or the test case as appropriate.

8. Do not modify the old run snapshot.

9. Create a new fresh snapshot.

10. Repeat until executor returns `PASS` and verifier returns `PASS` on the same fresh snapshot.

11. Do not reuse prior run artifacts.
