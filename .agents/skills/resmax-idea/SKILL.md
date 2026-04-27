---
name: resmax-idea
description: Compile a validated Phase 4 ResearchPack into evidence-grounded IdeaCards, lineage, closest-work checks, and cheapest falsification notes.
---

# resmax-idea

## Interaction Policy

Production/default execution is interactive. The agent must stop at Human Gates and ask the user before changing the idea portfolio, experiment budget, execution permission, or long-term memory. Non-interactive full pipeline execution is allowed only when the user explicitly says test/dev/debug/smoke, and persistent writeback still needs explicit opt-in flags such as `--confirm-write`.

## When To Use

Use this skill after `resmax-survey` Phase 4 has produced a validated ROI-aware `research_pack/`.

This is not a topic brainstorm skill. It is a deterministic `ResearchPack -> IdeaPortfolio` compiler. Candidate ideas must be grounded in `gap_map.json`, `roi_lens.json`, `paper_roles.json`, reviewer pressure notes, and EvidenceCards.

## Hard Gates

- Do not generate ideas directly from a topic or paper list.
- Every non-speculative IdeaCard must cite `source_gap_ids` and `evidence_ids`.
- An IdeaCard without `source_gap_ids` or `evidence_ids` must be `speculative` or `insufficient_evidence`.
- An IdeaCard without `closest_work_ids` is not ready for Phase 6 review.
- An IdeaCard without `direct_baselines` is not ready for executable experiment blueprint generation.
- This skill does not promote, reject by tournament, create `resmax-review`, execute experiments, run training, edit research code, write papers, or claim empirical results.
- Phase 7 experiment planning only consumes Phase 6 review outputs; a promoted idea without raw ReviewTrace coverage must not enter an experiment block.
- Phase 5 output stops at G4: show `ideas/idea_cards.jsonl`, `idea_report.md`, closest-work checks, and cheapest falsification notes, then ask which ideas enter Phase 6 review, whether to add human seeds, and which ideas to discard.
- Phase 7 output stops at G7: write `experiment_blueprint.json` and the human gate package only. Do not run training, evaluation, code edits, paper-result claims, or mark a block executable until the user approves the minimal falsification budget, baseline, dataset, and metric.
- Negative memory writeback stops at G8 and requires explicit approval. The CLI enforces this with `write-negative-memory --confirm-write`.
- Negative memory must store structured failure reasons only. Do not write secrets, tokens, personal identifiers, raw prompts, or raw model responses to memory.
- `idea_report.md` is display-only and must be rendered from structured artifacts.

## Required Input

```text
literature_research/<topic>/research_pack/
  manifest.json
  gap_map.json
  claim_graph.json
  evidence_cards.jsonl
  evidence_spans.jsonl
  reviewer_pressure_notes.jsonl
  paper_roles.json
  roi_lens.json
  gap_roi_table.csv
  idea_seed_constraints.md
```

The input pack must pass:

```bash
python3 .agents/skills/_shared/resmax_core/validators/validate_research_pack.py \
  --pack literature_research/<topic>/research_pack
```

## Commands

```bash
PYTHONPATH=.agents/skills/resmax-idea/scripts python3 -m resmax_idea generate \
  --pack literature_research/<topic>/research_pack \
  --out literature_research/<topic>/ideas

PYTHONPATH=.agents/skills/resmax-idea/scripts python3 -m resmax_idea validate \
  --ideas literature_research/<topic>/ideas

PYTHONPATH=.agents/skills/resmax-idea/scripts python3 -m resmax_idea compile-experiment-plan \
  --pack literature_research/<topic>/research_pack \
  --ideas literature_research/<topic>/ideas \
  --reviews literature_research/<topic>/reviews \
  --out literature_research/<topic>/experiment_plan

PYTHONPATH=.agents/skills/resmax-idea/scripts python3 -m resmax_idea write-negative-memory \
  --reviews literature_research/<topic>/reviews \
  --experiment-plan literature_research/<topic>/experiment_plan \
  --memory resmax_memory \
  --confirm-write
```

Optional negative memory is read from `resmax_memory/negative_memory.jsonl` by default. Use `--negative-memory <path>` to override it. Missing memory is recorded as `memory_status=not_found` and is not an error.

## Outputs

```text
ideas/
  manifest.json
  idea_cards.jsonl
  idea_lineage.json
  closest_work_checks.jsonl
  strongest_rejection_cases.md
  cheapest_falsification.md
  generation_trace.jsonl
  idea_report.md

experiment_plan/
  manifest.json
  experiment_blueprint.json
  minimal_falsification_plan.md
  baseline_contract.md
  metric_contract.md
  ablation_plan.md
  visualization_plan.md
  risk_register.md
  human_gate.md
  claim_to_experiment_matrix.csv

resmax_memory/
  negative_memory.jsonl
  reviewer_blockers.jsonl
  failed_gap_paths.jsonl
  infeasible_experiments.jsonl
```

## IdeaCard Contract

Each IdeaCard contains:

- `idea_id`
- `source_gap_ids`
- `source_claim_ids`
- `evidence_ids`
- `closest_work_ids`
- `core_delta`
- `primary_claim`
- `mechanism`
- `why_now`
- `direct_baselines`
- `method_donors`
- `benchmark_opportunities`
- `estimated_compute`
- `estimated_timeline`
- `expected_failure_modes`
- `reviewer_attack_points`
- `strongest_rejection_case`
- `cheapest_falsification`
- `lineage`
- `generation_sources`
- `readiness`
- `status`

Allowed generation sources:

```text
gap_driven
reviewer_pressure_driven
benchmark_blindspot_driven
method_transfer_driven
human_seed
```

`topic_direct` is forbidden and validator-failing.

## Phase 7 ExperimentBlock Contract

Each `experiment_blueprint.json` block contains:

- `experiment_id`
- `idea_id`
- `tested_claim`
- `anti_claim`
- `minimum_convincing_evidence`
- `baseline`
- `dataset`
- `metric`
- `ablation_or_sanity_check`
- `estimated_cost`
- `stop_condition`
- `failure_interpretation`
- `required_artifacts`
- `human_gate_required`
- `execution_status`

`baseline.category` is one of:

```text
must_run
nice_to_have
appendix_only
not_applicable
unknown_needs_followup
```

Metric contracts distinguish primary, secondary, sanity, and failure metrics. Missing baseline, dataset, or metric contracts produce `insufficient_evidence` / follow-up plans, not executable experiment blocks. Complete contracts produce an approval gate plan, not permission to execute; production `compile-experiment-plan` must not be treated as approval to run experiments.

## Negative Memory Contract

`write-negative-memory` is append-only. It computes a `dedupe_key` for each structured memory row and skips exact duplicate keys instead of rewriting old records. Superseding an old judgment must be represented by appending a new structured record, not deleting the old one.

Memory write triggers include fatal blocker kills, closest-work coverage, missing or over-budget baselines, unavailable data/metrics, human rejection, and low-ROI / infeasible experiment blueprints.

## Boundary

This skill outputs candidates, self-checks, Phase 7 blueprints, and structured negative-memory writeback only. Phase 6 owns heterogeneous review, blocker aggregation, and final promotion. A future `resmax-experiment` must consume validated `experiment_blueprint.json`; it must not start from free-form idea text.
