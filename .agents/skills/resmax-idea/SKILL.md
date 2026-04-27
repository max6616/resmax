---
name: resmax-idea
description: Compile a validated ROI-aware ResearchPack into evidence-grounded IdeaCards, lineage, closest-work checks, experiment planning inputs, and structured negative memory.
---

# resmax-idea

## When To Use

Use this skill after `resmax-survey` has produced a validated ROI-aware `research_pack/`.

This is not a topic brainstorm skill. It is a deterministic compiler from structured evidence to structured candidates. Ideas must be grounded in `gap_map.json`, `roi_lens.json`, `paper_roles.json`, reviewer pressure notes, and EvidenceCards.

Production/default execution is interactive. Stop before changing the idea portfolio, experiment budget, execution permission, or long-term memory. Full non-interactive execution is allowed only when the user explicitly says test/dev/debug/smoke; persistent writeback still requires explicit opt-in flags such as `--confirm-write`.

## Input

Required pack:

```text
literature_research/<topic>/research_pack/
```

It must contain the manifest, claim/gap/evidence artifacts, reviewer-pressure artifacts, ROI lens, and idea seed constraints, and must pass:

```bash
python3 .agents/skills/_shared/resmax_core/validators/validate_research_pack.py \
  --pack literature_research/<topic>/research_pack
```

Optional negative memory defaults to `resmax_memory/negative_memory.jsonl`; missing memory is recorded as `memory_status=not_found` and is not an error. Use `--negative-memory <path>` to override it.

## Linear Workflow

Generate and validate the idea portfolio:

```bash
PYTHONPATH=.agents/skills/resmax-idea/scripts python3 -m resmax_idea generate \
  --pack literature_research/<topic>/research_pack \
  --out literature_research/<topic>/ideas

PYTHONPATH=.agents/skills/resmax-idea/scripts python3 -m resmax_idea validate \
  --ideas literature_research/<topic>/ideas
```

Show `ideas/idea_cards.jsonl`, `idea_report.md`, closest-work checks, and cheapest falsification notes. Ask which ideas enter review, whether to add human seeds, and which ideas to discard.

Compile experiment planning artifacts only from reviewed ideas:

```bash
PYTHONPATH=.agents/skills/resmax-idea/scripts python3 -m resmax_idea compile-experiment-plan \
  --pack literature_research/<topic>/research_pack \
  --ideas literature_research/<topic>/ideas \
  --reviews literature_research/<topic>/reviews \
  --out literature_research/<topic>/experiment_plan
```

Stop after writing the experiment planning package. Do not run training, evaluation, code edits, paper-result claims, or mark a block executable until the user approves budget, baseline, dataset, and metric.

Write negative memory only after explicit user approval:

```bash
PYTHONPATH=.agents/skills/resmax-idea/scripts python3 -m resmax_idea write-negative-memory \
  --reviews literature_research/<topic>/reviews \
  --experiment-plan literature_research/<topic>/experiment_plan \
  --memory resmax_memory \
  --confirm-write
```

## Outputs

- `ideas/`: manifest, `idea_cards.jsonl`, lineage, closest-work checks, rejection/falsification notes, generation trace, rendered report
- `experiment_plan/`: manifest, blueprint, falsification plan, baseline/metric contracts, ablation/visualization plans, risk register, human gate, claim-to-experiment matrix
- `resmax_memory/`: negative memory, reviewer blockers, failed gap paths, infeasible experiments

`idea_report.md` is display-only and must be rendered from structured artifacts.

## Contracts

- Full field contracts live in `.agents/skills/_shared/resmax_core/schemas/idea_card.schema.json`, `experiment_blueprint.schema.json`, and `negative_memory.schema.json`.
- Every non-speculative IdeaCard must cite `source_gap_ids` and `evidence_ids`; otherwise it must be `speculative` or `insufficient_evidence`.
- `topic_direct` is forbidden and validator-failing.
- Cards without `closest_work_ids` are not ready for review.
- Cards without `direct_baselines` are not ready for executable experiment planning.
- Experiment planning consumes `resmax-review` outputs; a promoted idea without raw ReviewTrace coverage must not enter an experiment block.
- Missing baseline, dataset, or metric contracts produce `insufficient_evidence` / follow-up plans, not executable experiment blocks.
- Complete experiment contracts produce an approval gate plan, not permission to execute.
- `write-negative-memory` is append-only and deduplicated by `dedupe_key`; superseding old judgments requires appending a new structured record.
- Negative memory stores structured failure reasons only. Do not write secrets, tokens, personal identifiers, raw prompts, or raw model responses.

## Boundaries

- Do not generate ideas directly from a topic or paper list.
- Do not promote or reject by tournament; `resmax-review` owns heterogeneous review, blocker aggregation, and final promotion.
- Do not create `resmax-review`, execute experiments, run training, edit research code, write papers, or claim empirical results.
- A future experiment execution skill must consume validated `experiment_blueprint.json`; it must not start from free-form idea text.
