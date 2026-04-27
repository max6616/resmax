# Phase 3 Research Pack Field Map

- `selected_subdirection.json`: selected Phase 2 subdirection and candidate budget.
- `evidence_spans.jsonl`: quoted source spans with source type, locator, parser, quote hash, and extraction status.
- `evidence_cards.jsonl`: reasoning units that cite span ids and declare relation, scope, strength, and evidence status.
- `claim_graph.json`: single-writer canonical claims and claim relations.
- `gap_map.json`: gaps that cite claims/evidence or explicitly use `missing_evidence`.
- `missing_source_report.json`: selected candidates without readable cached source.
- `missing_pdf_report.json`: selected candidates without cached PDF text layer.
- `manifest.json`: artifact list and sha256 hashes verified by `validate_research_pack.py`.
