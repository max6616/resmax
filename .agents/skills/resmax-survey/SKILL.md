---
name: resmax-survey
description: Normalize external AI/human survey outputs into reproducible, falsifiable, provenance-tracked research assets with bounded local verification.
---

# resmax-survey

## New Default Positioning

`resmax-survey` is now a survey normalizer by default. It accepts external AI or human research outputs and converts them into structured assets that are reproducible, verifiable, falsifiable, provenance-tracked, evidence-pointed, explicit about missing evidence, and ready for `resmax-idea`, `resmax-review`, or experiment planning.

External inputs are candidate material, not verified facts. `paper_database/accepted_index.csv` is used as a high-quality accepted-paper whitelist and falsification base. Embedding/keyword retrieval is used as novelty falsifier, closest-work checker, and deterministic sanity checker, not as an open-domain discovery engine.

The unique human-facing entrypoint for a normalizer run is:

```text
literature_research/<topic>/survey_report.md
```

JSON, JSONL, CSV, and `manifest.json` are the factual assets and downstream contract.

## Accepted Inputs

Provide one or more of:

```text
external_report.md
seed_papers.csv
seed_papers.jsonl
seed_papers.md
seed_claims.jsonl
seed_gaps.jsonl
seed_ideas.jsonl
```

Recommended layout before running:

```text
survey_inputs/<topic>/
  external_report.md
  seed_papers.csv
  seed_claims.jsonl
  seed_gaps.jsonl
  seed_ideas.jsonl
```

Default command:

```bash
python3 .agents/skills/resmax-survey/scripts/survey_normalizer.py run-all \
  --topic <topic> \
  --input-dir survey_inputs/<topic> \
  --accepted paper_database/accepted_index.csv \
  --out-dir literature_research/<topic>

python3 .agents/skills/resmax-survey/scripts/validate_normalized_survey.py validate \
  --dir literature_research/<topic>
```

`survey_normalizer.py validate --dir literature_research/<topic>` is also supported.

## Non-Goals

- Do not perform open-domain discovery from scratch.
- Do not replicate Deep Research, GPT-5.5 Pro, Claude, Gemini, or web-scale literature search.
- Do not generate final ideas, recommendations, experiment plans, papers, or implementation tasks.
- Do not add a new database, vector DB, server, dashboard, crawler, queue, knowledge graph engine, or multi-agent orchestration.
- Do not treat external reports, LLM outputs, or seed files as verified facts.
- Do not generate multiple competing main Markdown reports.
- Do not hard-code specific research directions in the generic path.
- Do not expand scope into `resmax-database`, `resmax-embedding`, `resmax-review`, or `resmax-idea` beyond the minimal contract handoff.

## Normalizer-First Flow

Each stage has a bounded contract:

| Stage | Input | Output | LLM allowed | Local DB / embedding | Source materialization | Failure handling | Degraded mode | Required |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1. Preflight | external inputs, accepted_index, optional caches | `inputs/input_manifest.json`, initial `manifest.json` fields | No | Existence/hash checks only | No | Stop if no external input; mark missing accepted_index as parse-only | Missing embedding falls back to keyword; missing reviews/sources recorded | Yes |
| 2. Input normalization | report and seed files | `normalized/*`, `provenance_spans.jsonl`, `parse_errors.jsonl` | Optional extraction only; must mark model extraction | No | No | Bad rows go to `parse_errors.jsonl`; do not silently drop | Empty asset class is skipped | Yes |
| 3. Paper list audit | normalized seed papers, accepted_index | `audit/paper_audit.csv`, identity map, verified/external-only/uncertain/dropped sets | No by default | accepted_index identity match | No | Ambiguous rows become `uncertain`; duplicates become `dropped` | No accepted_index means no verified local facts | Yes |
| 4. Retrieval as falsification | claims, gaps, ideas, audit sets | `retrieval/*` traces and candidates | No | accepted_index; embedding optional | No | Every target records trace, ranking reason, drop reason | Keyword fallback if embedding unavailable | Yes |
| 5. Source materialization for critical evidence | verified/candidate papers needing content facts | `sources/source_manifest.jsonl`, missing source records | No | Source cache status only unless explicitly materialized | Required for content-level facts | Missing source does not stop run; writes missing evidence | Metadata-only identity allowed | Yes |
| 6. Per-paper secondary asset extraction | accepted metadata, source status, seed notes | `assets/paper_assets.jsonl`, `asset_mentions.jsonl`, `asset_stats.csv` | Optional extractor only, must cite source spans | accepted metadata; source cache optional | Required for verified content fields | Unknown fields stay empty and enter `missing_evidence` | Low confidence metadata extraction allowed | Yes |
| 7. Claim / gap normalization | seed claims/gaps, evidence, retrieval checks | `claim_graph.json`, `gap_map.jsonl`, falsification summary | Optional classification only | closest-work traces | Required before verified content claim | External claims stay unverified; gaps without closest work blocked | Follow-up query generated | Yes |
| 8. Report compilation | all structured artifacts | `survey_report.md` | Optional wording only, no new facts | No new retrieval | No | Report must link assets and missing evidence | Report may say evidence unavailable | Yes |
| 9. Downstream contract generation | assets, gaps, retrieval, missing evidence | `downstream/survey_contract.json`, compat pack | No | No | No | Blocking missing evidence prevents downstream readiness | Legacy compat emitted with explicit warnings | Yes |
| 10. Validation | full run directory | `validation/validation_report.json/.md` | No | No | No | FAIL blocks downstream use | Warnings allowed; errors must be fixed | Yes |

## Artifact Layout

Default run output:

```text
literature_research/<topic>/
  survey_report.md
  manifest.json

  inputs/
    input_manifest.json
    external_report.md
    seed_papers.csv
    seed_papers.jsonl
    seed_papers.md
    seed_claims.jsonl
    seed_gaps.jsonl
    seed_ideas.jsonl

  normalized/
    normalized_inputs.json
    provenance_spans.jsonl
    seed_papers.normalized.jsonl
    seed_claims.normalized.jsonl
    seed_gaps.normalized.jsonl
    seed_ideas.normalized.jsonl
    parse_errors.jsonl

  audit/
    paper_audit.csv
    paper_identity_map.jsonl
    verified_paper_set.jsonl
    external_only_papers.jsonl
    uncertain_papers.jsonl
    dropped_papers.jsonl
    audit_summary.json

  retrieval/
    retrieval_requests.jsonl
    retrieval_trace.jsonl
    closest_work_candidates.jsonl
    falsification_checks.jsonl
    infra_search_results.jsonl
    followup_queries.jsonl

  sources/
    source_manifest.jsonl
    source_materialization_report.json
    missing_sources.jsonl

  assets/
    paper_assets.jsonl
    asset_mentions.jsonl
    evidence_cards.jsonl
    claim_graph.json
    gap_map.jsonl
    asset_stats.csv
    falsification_summary.csv
    missing_evidence.jsonl

  downstream/
    survey_contract.json
    research_pack_compat/
      manifest.json
      evidence_cards.jsonl
      claim_graph.json
      gap_map.json
      closest_work_candidates.jsonl
      missing_evidence.jsonl

  validation/
    validation_report.json
    validation_report.md
```

Rules:

- `survey_report.md` is the only top-level human main report.
- Structured files are the source of truth.
- `manifest.json` records inputs, outputs, hashes, cache status, coverage, retrieval modes, provenance summary, degradation summary, validation status, and downstream contract path.
- Do not add scattered Markdown summaries outside the validation report and input copies.

## Retrieval Modes

Retrieval is bounded. Every request must include `target_type`, `target_id`, `purpose`, `query`, `retrieval_mode`, candidate list, ranking reason, drop reason, and `trace_id`. Per-target top-k must stay capped.

Supported modes:

1. `seed-list verifier`: match seed papers to accepted_index, dedupe, align IDs.
2. `local omission checker`: find obvious accepted-index papers omitted from the external report or seed set.
3. `closest-work search`: find nearest accepted papers for a claim, gap, idea, method description, or asset text.
4. `claim falsifier`: flag claims that may be overstrong, outdated, or contradicted by accepted work.
5. `gap falsifier`: check whether a gap may already be covered by accepted work.
6. `infra search`: retrieve and count dataset, benchmark, baseline, metric, base model, codebase, and task mentions.
7. `follow-up query suggester`: generate bounded queries when local evidence is insufficient.

Required retrieval outputs:

```text
retrieval/retrieval_requests.jsonl
retrieval/retrieval_trace.jsonl
retrieval/closest_work_candidates.jsonl
retrieval/falsification_checks.jsonl
retrieval/infra_search_results.jsonl
retrieval/followup_queries.jsonl
```

Retrieval must not automatically expand into full-field paper discovery.

## Source Materialization Policy

Metadata is sufficient only for:

- paper existence;
- title;
- authors;
- venue;
- year;
- accepted/local whitelist status.

Readable source evidence is required for:

- method contribution;
- limitation;
- dataset;
- benchmark;
- metric;
- baseline comparison;
- experimental protocol;
- ablation;
- compute/cost;
- failure case;
- reviewer concern.

If PDF, TeX, OpenReview, or other readable source evidence is unavailable:

- do not stop the whole run;
- write `sources/missing_sources.jsonl`;
- write `assets/missing_evidence.jsonl`;
- lower confidence for affected claim/asset/gap;
- do not mark the content as verified.

Do not mechanically chase a fixed readable-source coverage percentage. Coverage is measured by critical claim evidence, critical asset evidence, closest-work trace coverage, and explicit missing evidence.

## Secondary Asset Schema

`paper_assets.jsonl` must include at least:

```text
paper_id, canonical_title, audit_status, venue, year, source_status,
tasks, problem_settings, method_types, base_models, backbones,
datasets, benchmarks, metrics, baselines, experimental_protocols,
ablations, compute_cost, data_cost, annotation_cost,
code_availability, data_availability, claimed_contributions,
limitations, failure_cases, reviewer_signals, reuse_opportunities,
implementation_barriers, missing_fields, evidence_card_ids,
confidence, provenance
```

`asset_mentions.jsonl` must include:

```text
mention_id, paper_id, asset_type, normalized_name, surface_form,
role, evidence_card_id, confidence, source_span, provenance
```

`evidence_cards.jsonl` must include:

```text
evidence_id, paper_id, source_id, source_type, locator, quote_hash,
target_id, target_type, evidence_kind, support_relation,
content_summary, confidence, extraction_method, provenance
```

`claim_graph.json` must contain `schema_version`, `claims`, and `edges`. Each claim includes:

```text
claim_id, text, claim_type, origin, status, paper_ids,
evidence_ids, counter_evidence_ids, confidence
```

`gap_map.jsonl`, `closest_work_candidates.jsonl`, `missing_evidence.jsonl`, `asset_stats.csv`, and `manifest.json` follow the schemas enforced by `validate_normalized_survey.py`.

## Report Requirements

`survey_report.md` must include:

1. Executive summary
2. Input sources and trust boundary
3. Paper audit summary
4. Verified / external-only / uncertain / dropped papers
5. Key paper layers
6. Infrastructure profile
7. High-frequency datasets / benchmarks / baselines / metrics / base models
8. Claim graph summary
9. Gap map summary
10. Closest-work / novelty-risk summary
11. Missing evidence
12. Low-cost opportunities
13. Reviewer blocker hints
14. Downstream handoff boundary for `resmax-idea`
15. Artifact index with paths and hashes

The report should be dense and navigable. It must link structured files, avoid dumping every row, avoid generating full ideas or experiment plans, and avoid promoting external assumptions to verified conclusions.

## Downstream Contract

The normalizer writes:

```text
downstream/survey_contract.json
```

Required fields:

```text
schema_version, topic, verified_paper_set_path, claim_graph_path,
gap_map_path, closest_work_candidates_path, paper_assets_path,
asset_stats_path, evidence_cards_path, missing_evidence_path,
implementation_constraints, reviewer_blocker_hints, seed_opportunities,
warnings, provenance_summary, validation_status
```

Downstream consumers must distinguish:

- verified local metadata;
- external claims;
- deterministic/model inference;
- missing evidence.

Blocking missing evidence prevents `downstream_ready`. A gap without closest-work candidates must not enter review-ready idea generation.

## Validation Policy

Run the validator after every normalizer run:

```bash
python3 .agents/skills/resmax-survey/scripts/validate_normalized_survey.py validate \
  --dir literature_research/<topic>
```

The validator checks:

- artifact existence;
- schema validity;
- manifest hashes;
- input/output provenance;
- paper audit consistency;
- retrieval trace coverage;
- evidence pointer consistency;
- missing evidence consistency;
- critical claim coverage;
- gap falsification status;
- downstream contract completeness;
- survey report links;
- single main report entry;
- absence of generic direction-specific hard-code in the generic path;
- absence of unbounded discovery behavior.

Outputs:

```text
validation/validation_report.json
validation/validation_report.md
```

If validation is `FAIL`, do not hand off to `resmax-idea` except as a debugging fixture.

## Legacy / Optional Discovery Path

The old `survey_v2` macro discovery and ResearchPack path is retained as legacy/optional. Use it only when the user explicitly wants local corpus-driven direction discovery, subdirection selection, ResearchPack generation, or ROI-lens artifacts.

Legacy command shape:

```bash
PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 compile-spec \
  --intent "research intent" \
  --out-dir literature_research/<topic>

PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 plan-queries \
  --spec literature_research/<topic>/survey_v2/spec/research_spec.json \
  --agent-output literature_research/<topic>/survey_v2/spec/query_planner_agent_output.json \
  --out literature_research/<topic>/survey_v2/spec/query_families.jsonl

PYTHONPATH=.agents/skills/resmax-survey/scripts python3 -m resmax_survey_v2 retrieve-macro \
  --spec literature_research/<topic>/survey_v2/spec/research_spec.json \
  --accepted paper_database/accepted_index.csv \
  --embedding-cache paper_database/embedding_cache/qwen3_8b.npz \
  --embedding-provider ssh \
  --require-embedding \
  --out-dir literature_research/<topic>
```

Legacy rules:

- Legacy Markdown outputs are display-only and must not compete with normalizer `survey_report.md`.
- Legacy source coverage gates are for ResearchPack runs, not the normalizer default.
- Legacy ROI lens remains optional and does not generate final ideas.
- Any old direction-specific fixture must stay in tests/fixtures or an explicit topic profile, not generic code.

## Old Literature-List Path

Only use for the old `research_index.csv` / `literature_list.md` workflow:

```bash
SKILL_ROOT=.agents/skills/resmax-survey

python3 $SKILL_ROOT/scripts/search_literature.py \
  --accepted paper_database/accepted_index.csv \
  --direction "research direction description" \
  --keywords "keyword1,keyword2,keyword3" \
  --out-dir literature_research/<topic>

python3 $SKILL_ROOT/scripts/stage5_5_deepcheck.py \
  --dir literature_research/<topic> \
  --accepted paper_database/accepted_index.csv \
  --grades S
```

This path is legacy. Do not use it for the default normalizer flow.
