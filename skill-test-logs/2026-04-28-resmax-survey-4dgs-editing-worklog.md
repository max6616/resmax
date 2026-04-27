# resmax-survey production test/fix work log: 4DGS editing

## Session

- Date: 2026-04-28
- Main Developer Agent: Codex
- Target skill: `resmax-survey`
- User goal: Execute a complete production-grade test and repair loop for `resmax-survey`.
- Production task: Build a direction-level survey and ResearchPack for 4DGS editing, especially real-time editing and feed-forward Gaussian editing, targeting breakthroughs in action-edit accuracy, temporal/action coherence, and magnitude of achievable action changes. Focus includes transferable techniques from 3DGS and adjacent fields. Target venue is SIGGRAPH. Compute budget is 4x RTX 5090. Timeline is 4 weeks. Data constraint: no private/self-built datasets; only public datasets and public benchmarks. Qualitative visualization improvement is as meaningful as quantitative metric improvement.
- Output directory: `literature_research/4dgs_editing_siggraph_4w`

## Global Rules

- Follow `DEV_AGENT.md`.
- Main Developer Agent does not perform the full skill task directly.
- `skill_executor` performs the full production task and must stop at the first exception, uncertainty, policy conflict, missing dependency, or user decision point.
- `skill_verifier` independently audits executor results and remains read-only.
- Final pass requires executor PASS and verifier PASS in the same round.

## Production Acceptance Criteria

- The task remains full production, not smoke/debug/degraded.
- `paper_database/accepted_index.csv` exists.
- Database validation passes with `overall=PASS`.
- Production retrieval uses the embedding cache and requires embeddings.
- No missing embedding-cache downgrade.
- No Sci-Hub unless explicitly approved by the real user; no such approval is granted in this session.
- No abstract fallback unless explicitly approved by the real user; no such approval is granted in this session.
- If source gate G2 fails, executor performs the skill-defined legal public web-search replenishment path before asking for a business decision.
- ResearchPack covers only the selected subdirection and does not parse the full corpus.
- Selected candidate readable source coverage is at least 95%, and not all evidence is abstract fallback.
- `EvidenceCard` references `EvidenceSpan`.
- `GapMap` references claim/evidence or explicitly marks `missing_evidence`.
- ROI lens preserves unknowns, blockers, confidence, and multi-dimensional vectors rather than collapsing to a single score.
- Reviewer pressure uses real review cache where available; inferred items are marked as inferred.
- Public-data/public-benchmark constraints are represented in seed constraints, risk register, and ROI lens where relevant.
- Final artifacts include spec, macro retrieval outputs, selected subdirection, ResearchPack, ROI lens, manifests, and validation output.
- Markdown files are display-only; JSON/JSONL/CSV plus manifest hashes remain the downstream contract.

## Allowed Modification Scope

- Main Developer Agent may modify:
  - `.agents/skills/resmax-survey/**`
  - Directly related shared code under `.agents/skills/_shared/resmax_core/**` if root cause requires it
  - Directly related tests/fixtures if root cause requires it
  - `skill-test-logs/**`
- Executor may write runtime artifacts/caches only:
  - `literature_research/4dgs_editing_siggraph_4w/**`
  - `paper_database/source_cache/**`
  - `paper_database/reviews/**` only if restoring already packaged public reviews through the skill preflight path
- Executor must not modify skill files, shared code, tests, prompts, agent configs, or development instructions.
- Verifier must not modify any files.

## Round 1

### Start Git Status

```text
 M .agents/skills/_shared/resmax_core/corpus_api.py
 M .agents/skills/_shared/resmax_core/schemas/query_family.schema.json
 M .agents/skills/_shared/resmax_core/schemas/research_spec.schema.json
 M .agents/skills/_shared/resmax_core/schemas/retrieval_trace.schema.json
 M .agents/skills/resmax-idea/SKILL.md
 M .agents/skills/resmax-review/SKILL.md
 M .agents/skills/resmax-survey/SKILL.md
 M .agents/skills/resmax-survey/scripts/resmax_survey_v2/cluster_subdirections.py
 M .agents/skills/resmax-survey/scripts/resmax_survey_v2/compile_spec.py
 M .agents/skills/resmax-survey/scripts/resmax_survey_v2/phase3_pack.py
 M .agents/skills/resmax-survey/scripts/resmax_survey_v2/plan_queries.py
 M .agents/skills/resmax-survey/scripts/resmax_survey_v2/render_macro.py
 M .agents/skills/resmax-survey/scripts/resmax_survey_v2/retrieve_macro.py
 D .claude/skills
 M .codex/agents/skill_executor.toml
 M .codex/agents/skill_verifier.toml
 D .cursor/skills
 D AGENTS.md
 D docs/resmax_development_plan_v2/interaction_gate_policy.md
 D prompts/skill_dev.md
 D prompts/skill_executor.md
 D prompts/skill_verifier.md
 D prompts/start_test.md
 D skill-tests/cases/T001-smoke.md
 D skill-tests/scripts/prepare-run.sh
 M tests/fixtures/research_pack/valid_minimal/research_pack/manifest.json
 M tests/fixtures/research_pack/valid_minimal/research_pack/query_families.jsonl
 M tests/fixtures/research_pack/valid_minimal/research_pack/research_spec.json
 M tests/fixtures/research_pack/valid_minimal/research_pack/retrieval_trace.jsonl
 M tests/fixtures/research_pack/valid_roi_pack/research_pack/manifest.json
 M tests/fixtures/research_pack/valid_roi_pack/research_pack/query_families.jsonl
 M tests/fixtures/research_pack/valid_roi_pack/research_pack/research_spec.json
 M tests/fixtures/research_pack/valid_roi_pack/research_pack/retrieval_trace.jsonl
 M tests/fixtures/resmax_core/invalid/retrieval_trace_missing_query.jsonl
 M tests/fixtures/resmax_core/valid/query_family.json
 M tests/fixtures/resmax_core/valid/research_spec.json
 M tests/fixtures/resmax_core/valid/retrieval_trace.json
 M tests/fixtures/resmax_core/valid/retrieval_trace.jsonl
 M tests/fixtures/resmax_survey_v2/macro_smoke/survey_v2/macro/retrieval_trace.jsonl
 M tests/fixtures/resmax_survey_v2/macro_smoke/survey_v2/spec/query_families.jsonl
 M tests/fixtures/resmax_survey_v2/macro_smoke/survey_v2/spec/research_spec.json
 M tests/test_corpus_api.py
 M tests/test_survey_v2_macro.py
?? DEV_AGENT.md
```

### Round 1 Task

Execute the complete production-grade `resmax-survey` workflow for the 4DGS editing target and stop at the first real blocker or user decision point.

### Executor Prompt

```text
You are the `skill_executor` for a production-grade test of the `resmax-survey` skill in `/Users/zhangzhao/Code/resmax`.

Use the `resmax-survey` skill exactly as a real user would. Read its `SKILL.md` and follow it. Do not modify any skill files, shared code, tests, prompts, agent configs, or development instructions. You may write only runtime outputs/caches required by the skill:

- `literature_research/4dgs_editing_siggraph_4w/**`
- `paper_database/source_cache/**`
- `paper_database/reviews/**` only if restoring already packaged public reviews through the skill preflight path

Full production task:

Build a production direction-level survey and ResearchPack for 4DGS editing, especially real-time editing and feed-forward Gaussian editing. The research goal is to identify a SIGGRAPH-level direction that can break through on action-edit accuracy, temporal/action coherence, and the magnitude of achievable action changes. Include transferable techniques from 3DGS and adjacent fields. Target venue: SIGGRAPH. Compute budget: 4x RTX 5090. Timeline: 4 weeks. Data constraint: do not self-build/private-build data; only public datasets and public benchmarks are allowed. Qualitative visualization improvement is as meaningful as quantitative metric improvement.

Production constraints:

- This is not smoke/debug/degraded mode.
- Do not use missing-cache keyword-only downgrade.
- Do not use Sci-Hub.
- Do not use abstract fallback unless the real user explicitly approves it; no approval is currently granted.
- If the workflow reaches an intended production user decision point, such as choosing a subdirection or approving a source fallback, stop and return `NEEDS_INPUT` with the exact options, relevant files, and your recommended business choice. Do not guess silently.
- If any command errors, validation fails, dependency is missing, a gate conflicts with the skill rules, source coverage is insufficient, or you are unsure whether continuing would be a workaround, stop immediately and return `FAIL`.
- If G2 source gate fails, follow the skill-defined legal public web-search replenishment path before asking for a business decision.

Required acceptance before `PASS`:

- Database preflight validator passes with `overall=PASS`.
- Retrieval uses the production embedding cache with `--require-embedding`.
- Macro outputs are created and validated.
- A selected subdirection is explicitly chosen through a production decision flow.
- `build-pack`, `build-roi-lens`, and ResearchPack validation complete.
- Selected candidate readable source coverage is at least 95%.
- Evidence, claim/gap linkage, reviewer pressure, ROI lens, risk register, public-data/public-benchmark constraints, and manifests are present and coherent.
- No unapproved fallback, no hidden warnings/errors/tracebacks, and no unauthorized file modification.

Return one of:

- `PASS`: include commands run, key artifact paths, validation results, chosen subdirection, source coverage, and any non-blocking warnings.
- `FAIL`: include the first blocker, command/output excerpt, files touched, and why it is a real blocker.
- `NEEDS_INPUT`: include the decision needed, exact choices, supporting artifact paths, and recommended business choice.
```

