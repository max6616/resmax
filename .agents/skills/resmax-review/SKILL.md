---
name: resmax-review
description: Review a validated idea portfolio with standard evidence packages, heterogeneous raw reviews, blocker-first aggregation, and pairwise tournament traces.
---

# resmax-review

## When To Use

Use this skill after `resmax-idea` has produced a validated `ideas/` portfolio from a validated ROI-aware `research_pack/`.

This skill reviews candidates. It does not generate new ideas, edit `idea_cards.jsonl`, run experiments, write experiment blueprints, or summarize away raw reviewer outputs.

Production/default execution is interactive. Stop before spending reviewer budget, reducing reviewer independence, or promoting a disputed idea. Full non-interactive execution is allowed only when the user explicitly says test/dev/debug/smoke; reviewer fallback still requires explicit opt-in flags such as `--allow-same-model-review`.

## Linear Workflow

```bash
PYTHONPATH=.agents/skills/resmax-review/scripts python3 -m resmax_review build-packages \
  --ideas literature_research/<topic>/ideas \
  --out literature_research/<topic>/reviews
```

Before reviewer execution, ask which reviewer models/roles to use and whether same-model fallback is allowed.

```bash
PYTHONPATH=.agents/skills/resmax-review/scripts python3 -m resmax_review run-reviewers \
  --ideas literature_research/<topic>/ideas \
  --out literature_research/<topic>/reviews \
  --provider mcp-deepseek \
  --concurrency 5
```

```bash
PYTHONPATH=.agents/skills/resmax-review/scripts python3 -m resmax_review aggregate \
  --ideas literature_research/<topic>/ideas \
  --raw-reviews literature_research/<topic>/reviews/raw \
  --out literature_research/<topic>/reviews

PYTHONPATH=.agents/skills/resmax-review/scripts python3 -m resmax_review validate \
  --reviews literature_research/<topic>/reviews
```

After aggregation, ask what to do with `promoted`, `revise`, `human_gate`, and `killed` ideas. Disputed ideas must not be auto-promoted into experiment planning.

Use `--pack literature_research/<topic>/research_pack` only when `ideas/manifest.json` does not point to the source pack. By default, send only the internally selected top review-ready idea to external reviewers; use `--max-ideas N` for a shortlist, or `--all-ideas` only for explicit portfolio-wide regression/audit runs.

## Reviewer Protocol

- Each reviewer reads only `reviews/evidence_packages/<idea_id>.json`.
- Evidence packages may include structured IdeaCard fields, closest-work checks, ResearchSpec, EvidenceCards, ClaimGraph/Gaps, ROI lens entries, paper roles, and reviewer pressure notes.
- Evidence packages must not include display-only reports such as `idea_report.md`, `strongest_rejection_cases.md`, or `cheapest_falsification.md`.
- Required reviewer roles: `novelty`, `theory_or_mechanism`, `experiment`, `engineering`, `reviewer_pressure`.
- Raw review JSON must match `.agents/skills/_shared/resmax_core/schemas/review_trace.schema.json` and preserve prompt, prompt hash, raw response, blockers, recommended status, model identity, and independence confidence.
- Default provider is `mcp-deepseek`; `--provider stub` is only for deterministic tests and never counts as production review.
- Same-model fallback requires `--allow-same-model-review`; allowed traces must set `review_independence_confidence=low` and explain `fallback_reason`.
- Reviewer calls run concurrently by default (`--concurrency 5`); each concurrent task owns its own MCP stdio client.
- Provider failure after retries writes a schema-valid `human_gate` ReviewTrace with an `external_reviewer_execution_failed` blocker.

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

Markdown files are display-only. Downstream planning consumes the JSON/JSONL artifacts.

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

Do not promote by average score. Scores may appear in raw reviews as reviewer-local context, but they are never averaged into a promotion decision.

## Boundaries

- Reviewer inputs must be standard evidence packages, not generator persuasive pitch.
- Raw reviewer prompt and response must be preserved in `reviews/raw/<reviewer_role>/<idea_id>.json`.
- Any fatal blocker with cited evidence kills promotion.
- Missing raw reviews route the idea to `human_gate_ideas.jsonl`.
- Missing closest work routes the idea to revision unless a stronger fatal blocker kills it.
- Revision requests are written to new review artifacts. `ideas/idea_cards.jsonl` is append-only input and must not be modified.
- Review loop: aggregate blockers, send revise requests back to `resmax-idea` or a human, append/regenerate a new idea portfolio, then review again.
