"""Orchestrator for agent-based abstract enrichment (Layer 3 fallback).

Provides:
  1. build_enrich_orchestrator_prompt() — Generate prompt for an orchestrator subagent
     that dispatches web-search abstract enrichment to nested subagents
  2. load_enrich_results_file() — Load enriched abstracts from the JSON written by orchestrator

The orchestrator subagent:
  - Reads the CSV to find papers missing abstracts (filtered by conf_year if specified)
  - Splits them into batches of 5
  - For each batch, spawns a searcher subagent that uses WebSearch to find abstracts
  - Collects results and writes to enrich_results.json
  - Main agent reads the JSON and writes abstracts back to CSV
"""
from __future__ import annotations

import json
from pathlib import Path


ENRICH_RESULTS_FILENAME = "enrich_results.json"
ENRICH_BATCH_SIZE = 5


def build_enrich_orchestrator_prompt(
    csv_path: str,
    out_dir: str,
    conf_year_filter: str = "",
) -> str:
    """Build the prompt for an orchestrator subagent to find missing abstracts.

    Args:
        csv_path: Absolute path to accepted_index.csv
        out_dir: Absolute path to directory where enrich_results.json will be written
        conf_year_filter: If set, only process rows where conf_year matches this value
    """
    results_path = f"{out_dir}/{ENRICH_RESULTS_FILENAME}"
    filter_clause = f'\nOnly process rows where conf_year == "{conf_year_filter}".' if conf_year_filter else ""

    return f"""You are an abstract enrichment orchestrator. Your job is to find missing abstracts for academic papers by dispatching web search tasks to nested subagents.

TASK:
1. Read {csv_path} (CSV) and identify papers with empty abstract_raw{filter_clause}
2. Split these papers into batches of {ENRICH_BATCH_SIZE}
3. For each batch, spawn a searcher subagent to find abstracts via web search
4. Collect all found abstracts and write to {results_path}
5. Return: ENRICH_DONE:{results_path}

STEP-BY-STEP INSTRUCTIONS:

Step 1 — Identify missing abstracts:
Read {csv_path} using the Read tool. Parse as CSV. Collect all rows where abstract_raw is empty or whitespace-only. Record paper_id, title, authors, venue, year for each.

If no papers are missing abstracts, write an empty JSON object {{}} to {results_path} and return immediately.

Step 2 — Build searcher prompts:
Split papers into batches of up to {ENRICH_BATCH_SIZE}. For each batch, build a prompt following this EXACT format:

---BEGIN SEARCHER PROMPT TEMPLATE---
You are searching for abstracts of academic papers. For each paper below, use WebSearch to find its abstract.

Papers to search:

[paper_id: XXXX]
  Title: <exact title>
  Authors: <authors>
  Venue: <venue> <year>

[paper_id: YYYY]
  Title: <exact title>
  Authors: <authors>
  Venue: <venue> <year>

SEARCH STRATEGY (for each paper):
1. Search the exact title in quotes: "<title>"
2. If no results, remove special characters/abbreviations and retry
3. Look for the abstract on: arXiv, ACM DL, IEEE Xplore, Semantic Scholar, ResearchGate, OpenReview
4. If the found title differs significantly from the original, verify by checking the author list
5. Extract the full abstract text

RESPONSE FORMAT:
Return a JSON object keyed by paper_id:
{{
  "XXXX": {{"abstract": "The full abstract text...", "source": "arXiv"}},
  "YYYY": {{"abstract": "", "source": "", "note": "Not found after exhaustive search"}}
}}

RULES:
- Include ALL paper_ids. Do not skip any.
- Each key MUST exactly match the paper_id in brackets.
- If abstract is found: set "abstract" to the full text and "source" to where you found it.
- If not found: set "abstract" to empty string and add "note" explaining what you tried.
- Return ONLY the JSON object, no other text.
---END SEARCHER PROMPT TEMPLATE---

Step 3 — Dispatch searcher subagents:
Send each batch prompt as a Task (subagent_type="generalPurpose", model="fast").
You may send 2 batches in parallel.

Step 4 — Parse responses:
For each searcher response, extract the JSON object. Validate that:
- Each key matches an expected paper_id
- "abstract" field exists

If a searcher fails to return valid JSON, retry that batch once.

Step 5 — Write results:
Merge all results into a single JSON object and write to {results_path}:
{{
  "paper_id_1": {{"abstract": "...", "source": "arXiv"}},
  "paper_id_2": {{"abstract": "", "source": "", "note": "Not found"}},
  ...
}}

Use the Write tool to create {results_path}.

Step 6 — Return confirmation:
Respond with exactly: ENRICH_DONE:{results_path}

CONSTRAINTS:
- paper_id is the ONLY matching key. Copy exactly from CSV.
- Do NOT modify or invent paper_ids.
- Every paper with missing abstract must appear in the output JSON.
- Keep your own output minimal. Execute, don't narrate."""


def load_enrich_results_file(results_path: str) -> dict[str, dict]:
    """Load enrich_results.json written by the orchestrator.

    Returns dict mapping paper_id -> {"abstract": str, "source": str, ...}.
    """
    path = Path(results_path)
    if not path.exists():
        raise FileNotFoundError(f"Enrich results file not found: {results_path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {results_path}, got {type(data).__name__}")

    found = sum(1 for v in data.values() if isinstance(v, dict) and v.get("abstract", "").strip())
    total = len(data)
    print(f"[enrich] loaded {total} entries, {found} with abstracts, {total - found} not found")
    return data


def apply_enrich_results(csv_path: str, results: dict[str, dict]) -> tuple[int, int]:
    """Write found abstracts back to accepted_index.csv.

    Returns (updated_count, skipped_count).
    """
    import csv

    path = Path(csv_path)
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    if not fieldnames:
        raise ValueError(f"CSV has no headers: {csv_path}")

    updated = 0
    skipped = 0
    for row in rows:
        pid = row.get("paper_id", "")
        if pid not in results:
            continue
        entry = results[pid]
        abstract = entry.get("abstract", "").strip() if isinstance(entry, dict) else ""
        if abstract and not row.get("abstract_raw", "").strip():
            row["abstract_raw"] = abstract
            updated += 1
        else:
            skipped += 1

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[enrich] updated {updated} abstracts, skipped {skipped}")
    return updated, skipped
