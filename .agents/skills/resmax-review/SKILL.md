---
name: resmax-review
description: Review a Phase 5 idea portfolio with heterogeneous raw reviews, blocker-first aggregation, and pairwise tournament traces.
---

# resmax-review

## Interaction Policy

Production/default execution is interactive. The agent must stop at Human Gates and ask the user before spending reviewer budget, reducing reviewer independence, or promoting a disputed idea. Non-interactive full pipeline execution is allowed only when the user explicitly says test/dev/debug/smoke, and reviewer fallback still needs explicit opt-in flags such as `--allow-same-model-review`.

## When To Use

Use this skill after `resmax-idea` has produced a validated `ideas/` portfolio from a validated ROI-aware `research_pack/`.

This skill reviews candidates. It does not generate new ideas, edit `idea_cards.jsonl`, run experiments, write experiment blueprints, or summarize away raw reviewer outputs.

## Hard Gates

- Reviewer inputs must be standard evidence packages, not `idea_report.md` or any generator persuasive pitch.
- Raw reviewer prompt and response must be preserved in `reviews/raw/<reviewer_role>/<idea_id>.json`.
- Promotion is blocker-first. Do not promote by average score.
- Any fatal blocker with cited evidence kills promotion.
- Missing raw reviews prevent promotion and route the idea to `human_gate_ideas.jsonl`.
- Missing closest work prevents promotion and routes the idea to revision unless a stronger fatal blocker kills it.
- Phase 6 stops at G5 before reviewer execution: ask which reviewer models/roles to use and whether same-model fallback is allowed.
- Same-model review fallback is allowed only when the user explicitly approves it. If allowed, `review_independence_confidence` must be `low` and `fallback_reason` must state that the same model was used. If not allowed, the raw trace routes to `human_gate`.
- Phase 6 stops at G6 after aggregation: ask what to do with `promoted`, `revise`, `human_gate`, and `killed` ideas. Disputed ideas must not be auto-promoted to Phase 7.
- Revision requests are written to new review artifacts. The source `ideas/idea_cards.jsonl` is append-only input and must not be modified by this skill.

## Commands

```bash
PYTHONPATH=.agents/skills/resmax-review/scripts python3 -m resmax_review build-packages \
  --ideas literature_research/<topic>/ideas \
  --out literature_research/<topic>/reviews

PYTHONPATH=.agents/skills/resmax-review/scripts python3 -m resmax_review run-reviewers \
  --ideas literature_research/<topic>/ideas \
  --out literature_research/<topic>/reviews \
  --provider mcp-deepseek \
  --concurrency 5

PYTHONPATH=.agents/skills/resmax-review/scripts python3 -m resmax_review aggregate \
  --ideas literature_research/<topic>/ideas \
  --raw-reviews literature_research/<topic>/reviews/raw \
  --out literature_research/<topic>/reviews

PYTHONPATH=.agents/skills/resmax-review/scripts python3 -m resmax_review validate \
  --reviews literature_research/<topic>/reviews
```

Use `--pack literature_research/<topic>/research_pack` only when `ideas/manifest.json` does not point to the source pack.

By default, Phase 6 sends only the internally selected top idea to external reviewers. The selection is deterministic and prefers `phase6_ready` method ideas with strong evidence, direct baselines, target-term fit, and bounded compute. Use `--max-ideas N` to review a small shortlist, or `--all-ideas` only for explicit portfolio-wide regression or audit runs. Do not send every generated IdeaCard to external reviewers by default.

## Reviewer Protocol

Each reviewer role reads only one JSON evidence package:

```text
reviews/evidence_packages/<idea_id>.json
```

The evidence package may include structured `IdeaCard` fields, closest-work checks, ResearchSpec, EvidenceCards, ClaimGraph/Gaps, ROI lens entries, paper roles, and reviewer pressure notes. It must not include display-only reports such as `idea_report.md`, `strongest_rejection_cases.md`, or `cheapest_falsification.md`.

Required reviewer roles:

```text
novelty
theory_or_mechanism
experiment
engineering
reviewer_pressure
```

Raw review JSON must conform to the shared `review_trace.schema.json` and include `prompt`, `prompt_hash`, `raw_response`, `blockers`, `recommended_status`, model identity, and independence confidence.

Production reviewer execution is owned by `run-reviewers`. The default provider is `mcp-deepseek`, which calls the project-local `resmax_multimodel` MCP server and writes raw traces to `reviews/raw/<reviewer_role>/<idea_id>.json`. Use `--provider stub` only for deterministic tests; stub output must never be counted as production review. Same-model fallback requires `--allow-same-model-review`; without it, same-model traces are preserved but routed to human gate and cannot support promotion.

Reviewer calls run concurrently by default (`--concurrency 5`) so the five role reviews for one idea can execute in parallel when the provider supports parallel API requests. Each concurrent task owns its own MCP stdio client; do not share one stdio client across threads. If a provider call fails after retries, `run-reviewers` writes a schema-valid `human_gate` ReviewTrace with an `external_reviewer_execution_failed` blocker instead of crashing the whole batch.

If reviewers request revision, this skill writes revise/human-gate artifacts through aggregation. It does not edit the source idea portfolio in place. The review loop is: aggregate blockers -> feed revise requests back to `resmax-idea` or a human -> append/regenerate a new idea portfolio -> run reviewers again.

## Outputs

```text
reviews/
  manifest.json
  evidence_packages/<idea_id>.json
  raw/<reviewer_role>/<idea_id>.json
  review_matrix.csv
  blocker_summary.md
  disagreement_report.md
  tournament_trace.jsonl
  promoted_ideas.jsonl
  killed_ideas.jsonl
  revise_ideas.jsonl
  human_gate_ideas.jsonl
```

Markdown files are display-only. Phase 7 should consume the JSON/JSONL artifacts.

## Aggregation Rule

```text
if any fatal blocker with evidence:
    status = killed
elif raw review is missing or invalid:
    status = human_gate
elif closest work is missing:
    status = revise
elif unresolved reviewer disagreement:
    status = human_gate
elif weak evidence or missing baseline:
    status = revise
else:
    status = promoted
```

The tournament trace is pairwise and blocker-first. Scores may appear in raw reviews as reviewer-local context, but they are never averaged into a promotion decision.
