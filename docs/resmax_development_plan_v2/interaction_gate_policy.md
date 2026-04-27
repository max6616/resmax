# Resmax Interaction Gate Policy

Default execution mode is production/user-facing. Production/default execution is interactive and approval-required. Non-interactive continuation is allowed only when the user explicitly declares test, dev, debug, or smoke, and the command also carries the matching opt-in flag.

## G0 Initial Goal Constraints

- gate_id: G0
- phase: before Phase 2
- trigger: user asks for a production research survey without explicit goal constraints
- user question: What is the research goal, target venue, time/compute/team budget, and non-goals?
- allowed answers: provide constraints; narrow the topic; stop
- default action if no answer: stop before Phase 2
- artifact to show before asking: none, or the current user intent summary
- artifact written after decision: `survey_v2/spec/research_spec.json`
- non_interactive exception: only test/dev/debug/smoke with explicit fixture intent

## G1 Subdirection Selection

- gate_id: G1
- phase: Phase 2 -> Phase 3
- trigger: Phase 2 produced `subdirection_map` and `subdirection_roi_table`
- user question: Which `subdirection_id` should enter Phase 3?
- allowed answers: choose `subdirection_id`; rerun Phase 2; stop; explicit non-production `--allow-auto-select`
- default action if no answer: stop before Phase 3
- artifact to show before asking: `survey_v2/macro/subdirection_map.json`, `survey_v2/macro/subdirection_roi_table.csv`, `survey_v2/macro/macro_survey_report.md`
- artifact written after decision: `research_pack/selected_subdirection.json` or `research_pack/pending_gate_g1.json`
- non_interactive exception: `--mode smoke|dev|debug|test --allow-auto-select`

## G2 Evidence Expansion Strategy

- gate_id: G2
- phase: after Phase 3 source materialization
- trigger: readable full text is missing, source coverage is weak, or `abstract_fallback` would be used
- user question: Replenish source, allow approved MinerU/manual cache, allow Sci-Hub, continue with weak abstract fallback, or switch direction?
- allowed answers: replenish source cache; provide manual/MinerU markdown; allow Sci-Hub; `--allow-abstract-fallback`; switch subdirection; stop
- default action if no answer: stop before weak/degraded evidence enters claim/gap synthesis
- artifact to show before asking: `source_materialization_report.json`; `missing_source_report.json` and `missing_pdf_report.json` if extraction already ran
- artifact written after decision: `research_pack/pending_gate_g2.json`, then `evidence_spans.jsonl` and `evidence_cards.jsonl` only after approval
- non_interactive exception: `--mode smoke|dev|debug|test --allow-abstract-fallback`

## G3 ROI Unknown And Blocker Review

- gate_id: G3
- phase: after Phase 4
- trigger: `roi_lens.json` contains high-priority gaps with unknowns or reviewer blockers
- user question: Which unknowns/blockers must be resolved before idea generation?
- allowed answers: approve as known risk; request follow-up retrieval; lower priority; drop gap; stop
- default action if no answer: do not treat unknown as safe-to-continue
- artifact to show before asking: `roi_lens.json`, `gap_roi_table.csv`, `risk_register.md`, `idea_seed_constraints.md`
- artifact written after decision: updated `idea_seed_constraints.md` or a pending decision note
- non_interactive exception: test/dev/debug/smoke fixtures with explicit expected unknown handling

## G4 Idea Portfolio Review

- gate_id: G4
- phase: after Phase 5
- trigger: `ideas/idea_cards.jsonl` and closest-work checks are written
- user question: Which ideas enter Phase 6 review, should any human seed be added, and which ideas are discarded?
- allowed answers: select idea ids; add human seed; drop idea ids; regenerate; stop
- default action if no answer: do not spend reviewer budget
- artifact to show before asking: `ideas/idea_cards.jsonl`, `idea_report.md`, `closest_work_checks.jsonl`, `cheapest_falsification.md`
- artifact written after decision: review shortlist or updated idea portfolio
- non_interactive exception: test/dev/debug/smoke with explicit `--max-ideas`, `--all-ideas`, or fixture selection

## G5 Reviewer Execution Configuration

- gate_id: G5
- phase: before Phase 6 reviewer calls
- trigger: external reviewer execution would start
- user question: Which reviewer roles/models should run, and is same-model fallback allowed?
- allowed answers: approve role/model config; reduce roles; allow `--allow-same-model-review`; stop
- default action if no answer: do not call reviewers
- artifact to show before asking: `reviews/evidence_packages/<idea_id>.json`, reviewer role list, provider/model config
- artifact written after decision: `reviews/raw/<reviewer_role>/<idea_id>.json`
- non_interactive exception: test/dev/debug/smoke with explicit provider and fallback flags

## G6 Promotion And Human Gate

- gate_id: G6
- phase: after Phase 6 aggregation
- trigger: `promoted_ideas.jsonl`, `revise_ideas.jsonl`, `human_gate_ideas.jsonl`, or `killed_ideas.jsonl` is written
- user question: Which promoted ideas enter Phase 7, which revise/human_gate cases should be repaired, and which killed paths are accepted?
- allowed answers: approve promoted ids; request revision; human adjudicate; accept kill; stop
- default action if no answer: do not auto-promote disputed ideas to Phase 7
- artifact to show before asking: `blocker_summary.md`, `disagreement_report.md`, `tournament_trace.jsonl`, status JSONL files
- artifact written after decision: Phase 7 input shortlist or revision notes
- non_interactive exception: deterministic test/dev/debug/smoke fixtures

## G7 Experiment Budget Approval

- gate_id: G7
- phase: after Phase 7 planning, before any real experiment
- trigger: `experiment_blueprint.json` and human gate package are written
- user question: Approve the minimal falsification plan, budget, baseline, dataset, and metric for execution?
- allowed answers: approve execution; request cheaper plan; change baseline/dataset/metric; reject; stop
- default action if no answer: plan only; do not run training, evaluation, code edits, or paper-result claims
- artifact to show before asking: `experiment_blueprint.json`, `minimal_falsification_plan.md`, `baseline_contract.md`, `metric_contract.md`, `human_gate.md`
- artifact written after decision: approved experiment run config for a future experiment skill
- non_interactive exception: test/dev/debug/smoke dry runs only; no production result claims

## G8 Negative Memory Writeback

- gate_id: G8
- phase: after Phase 7 decision
- trigger: killed, rejected, blocked, or infeasible paths could be written to long-term memory
- user question: Should these structured failures be written to negative memory?
- allowed answers: approve `--confirm-write`; reject writeback; edit reasons; stop
- default action if no answer: do not write memory
- artifact to show before asking: `killed_ideas.jsonl`, `human_gate_ideas.jsonl`, `experiment_blueprint.json`, proposed memory rows
- artifact written after decision: `resmax_memory/negative_memory.jsonl`, `reviewer_blockers.jsonl`, `failed_gap_paths.jsonl`, `infeasible_experiments.jsonl`
- non_interactive exception: test/dev/debug/smoke only with explicit `--confirm-write`
