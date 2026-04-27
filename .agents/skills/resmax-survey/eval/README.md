# Resmax Survey Eval Baseline

This directory contains the Phase 1 deterministic retrieval baseline. It is intentionally small:

- no LLM judge;
- no web fallback;
- no production `paper_database/` requirement;
- no ROI scoring from citation count, keyword hits, or embedding similarity.

Run the fixture smoke:

```bash
python3 .agents/skills/resmax-survey/eval/run_baseline.py \
  --spec .agents/skills/resmax-survey/eval/pilot_specs/smoke_fixture.json \
  --out /tmp/resmax_eval_smoke
```

Artifacts:

- `baseline_results.json`: complete returned paper IDs and per-hit metadata.
- `metrics.json`: deterministic hit-rate, recall, and MRR summary.
- `retrieval_trace.jsonl`: schema-valid retrieval traces from `resmax_core.corpus_api`.
- `summary.md`: human-readable summary only.
