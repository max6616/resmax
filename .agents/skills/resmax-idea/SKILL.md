---
name: resmax-idea
description: Compile a validated ROI-aware ResearchPack into evidence-grounded IdeaCards, lineage, closest-work checks, experiment planning inputs, and structured negative memory.
---

# resmax-idea

## When To Use

Use this skill after `resmax-survey` has produced either a validated normalizer contract or a legacy ROI-aware `research_pack/`.

This is not a topic brainstorm skill. It is a deterministic compiler from structured evidence to structured candidates. For the normalizer-first path, ideas must be grounded in `downstream/survey_contract.json`, `claim_graph`, `gap_map`, closest-work candidates, paper assets, EvidenceCards, and missing-evidence records. For the legacy path, ideas must be grounded in `gap_map.json`, `roi_lens.json`, `paper_roles.json`, reviewer pressure notes, and EvidenceCards.

Production/default execution is interactive. Stop before changing the idea portfolio, experiment budget, execution permission, or long-term memory. Full non-interactive execution is allowed only when the user explicitly says test/dev/debug/smoke; persistent writeback still requires explicit opt-in flags such as `--confirm-write`.

## Input

Preferred normalizer contract:

```text
literature_research/<topic>/downstream/survey_contract.json
```

If the contract exists, read it first and follow its paths for verified paper set, claim graph, gap map, closest-work candidates, paper assets, asset stats, evidence cards, and missing evidence. If it does not exist, fall back to the legacy pack:

```text
literature_research/<topic>/research_pack/
```

The legacy pack must contain the manifest, claim/gap/evidence artifacts, reviewer-pressure artifacts, ROI lens, and idea seed constraints, and must pass:

```bash
python3 .agents/skills/_shared/resmax_core/validators/validate_research_pack.py \
  --pack literature_research/<topic>/research_pack
```

Optional negative memory defaults to `resmax_memory/negative_memory.jsonl`; missing memory is recorded as `memory_status=not_found` and is not an error. Use `--negative-memory <path>` to override it.

Input trust boundary:

- `verified_fact`: accepted-index metadata or materialized source evidence only.
- `external_claim`: external report or seed assertion; never promote directly.
- `model_inference`: deterministic/model extraction or classification; cite provenance and lower confidence.
- `missing_evidence`: blocking or warning record; blocking records prevent review-ready idea generation.

Do not expand this skill into survey normalization or retrieval. If the contract says a gap lacks closest-work candidates or blocking missing evidence is open, keep it out of review-ready idea generation.

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
- Prefer `literature_research/<topic>/downstream/survey_contract.json` when present; otherwise use legacy `literature_research/<topic>/research_pack/`.
- Every non-speculative IdeaCard must cite `source_gap_ids` and `evidence_ids`; otherwise it must be `speculative` or `insufficient_evidence`.
- Every IdeaCard must preserve the distinction between verified fact, external claim, model inference, and missing evidence.
- `topic_direct` is forbidden and validator-failing.
- Cards without `closest_work_ids` are not ready for review.
- Gaps marked not `downstream_ready` in the survey contract are not ready for review.
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
