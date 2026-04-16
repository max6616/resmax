"""Subagent-based paper scoring and main-agent review.

This module provides:
  Orchestrator (primary — used by main agent):
    1. build_orchestrator_prompt() — Generate prompt for a single orchestrator subagent
       that internally dispatches batch scoring to nested scorer subagents
    2. load_scores_file() — Load scores_raw.json written by the orchestrator

  Batch scoring (used by orchestrator subagent internally):
    3. build_batch_scoring_prompt() — Generate prompt for a scorer subagent (up to 10 papers)
    4. parse_batch_scoring_response() — Parse batch response with paper_id validation

  Single-paper scoring (fallback only):
    5. build_scoring_prompt() — Generate prompt for ONE paper (retry failures)
    6. parse_scoring_response() — Parse single-paper response

  Review & apply (used by main agent after orchestrator returns):
    7. review_score() — Check a score for obvious contradictions
    8. apply_scores() — Apply all scores to candidate papers and finalize

Main agent workflow:
  1. Call build_orchestrator_prompt() → send as single Task to orchestrator subagent
  2. Orchestrator writes scores_raw.json and returns the file path
  3. Main agent calls load_scores_file() to read scores
  4. Main agent calls apply_scores() once with the complete dict
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .models import CandidatePaper
from .filter_logger import FilterLog


# ---------------------------------------------------------------------------
# Scoring prompt template
# ---------------------------------------------------------------------------

SCORING_CRITERIA = """Scoring criteria for relevance to the research direction:

- S: Highly relevant. This paper directly addresses the same problem, proposes a closely related method, or is an essential baseline. Reading it is mandatory for anyone working in this direction.
- A: Clearly relevant. The paper shares significant overlap in methodology, problem formulation, or application domain. It provides valuable context or techniques that could directly inform the research.
- B: Moderately relevant. The paper has some connection — perhaps a shared technique, a related but different problem, or useful background. Worth noting but not a priority read.
- C: Weakly relevant. The connection is peripheral — tangential topic, distant methodology, or only superficially related keywords. Low priority for this specific direction."""


def _format_paper_block(paper: CandidatePaper) -> tuple[str, bool]:
    """Format a single paper's info block for inclusion in a prompt.

    Returns (formatted_text, needs_web_fetch).
    """
    parts = [
        f"  Title: {paper.title}",
        f"  Venue: {paper.venue} {paper.year}" if paper.venue else "",
        f"  Authors: {paper.authors}" if paper.authors else "",
    ]

    has_abstract = bool(paper.abstract_raw and paper.abstract_raw.strip())
    has_pdf = bool(paper.pdf_url and paper.pdf_url.strip())
    has_link = bool(paper.paper_link and paper.paper_link.strip())
    needs_fetch = False

    if has_abstract:
        parts.append(f"  Abstract: {paper.abstract_raw}")
        if paper.keywords_raw:
            parts.append(f"  Keywords: {paper.keywords_raw}")
    elif has_pdf:
        parts.append(f"  PDF URL: {paper.pdf_url}")
        parts.append("  [No abstract — you MUST read the PDF via WebFetch before scoring this paper]")
        needs_fetch = True
    elif has_link:
        parts.append(f"  Paper link: {paper.paper_link}")
        parts.append("  [No abstract/PDF — try WebFetch on the link; if inaccessible, score by title with low confidence]")
        needs_fetch = True
    else:
        parts.append("  [No abstract/PDF/link — title-only assessment, note low confidence in reason]")

    return "\n".join(p for p in parts if p), needs_fetch


def build_scoring_prompt(
    paper: CandidatePaper,
    direction: str,
    keywords: list[str],
) -> str:
    """Build the prompt for a subagent to score a single paper.

    DEPRECATED for normal use — prefer build_batch_scoring_prompt() for efficiency.
    Kept as fallback for retrying individual papers that failed batch parsing.
    """
    block, _ = _format_paper_block(paper)

    prompt = f"""You are evaluating a single academic paper for its relevance to a specific research direction.

Research direction: {direction}
Related keywords: {', '.join(keywords)}

{SCORING_CRITERIA}

Paper to evaluate (paper_id: {paper.paper_id}):
{block}

TOOL USAGE RULES:
- To read a PDF or link, use ONLY the WebFetch tool. Do NOT use MinerU, Shell, or any file download tool.
- If WebFetch fails, fall back to whatever text is available above.
- Keep your response SHORT: just the JSON object.

Return your assessment as a JSON object:
{{"score": "S/A/B/C", "reason": "Your concise explanation (1-3 sentences)"}}

Return ONLY the JSON object, no other text."""

    return prompt


BATCH_SIZE = 10


def build_batch_scoring_prompt(
    papers: list[CandidatePaper],
    direction: str,
    keywords: list[str],
) -> str:
    """Build a prompt for a subagent to score a BATCH of papers (up to 10).

    IMPORTANT: This is the PRIMARY way to generate scoring prompts.
    Hand-writing prompts is FORBIDDEN.

    The prompt embeds each paper's paper_id and requires the subagent to
    return a JSON object keyed by paper_id, ensuring unambiguous matching.
    """
    if not papers:
        raise ValueError("papers list is empty")
    if len(papers) > BATCH_SIZE:
        raise ValueError(f"Batch size {len(papers)} exceeds maximum {BATCH_SIZE}")

    paper_blocks: list[str] = []
    any_needs_fetch = False
    for paper in papers:
        block, needs_fetch = _format_paper_block(paper)
        any_needs_fetch = any_needs_fetch or needs_fetch
        paper_blocks.append(f"[paper_id: {paper.paper_id}]\n{block}")

    papers_text = "\n\n".join(paper_blocks)
    id_list = ", ".join(f'"{p.paper_id}"' for p in papers)

    fetch_instruction = ""
    if any_needs_fetch:
        fetch_instruction = """
TOOL USAGE RULES:
- Some papers above lack abstracts and provide a PDF URL or paper link instead.
  For those papers, use ONLY the WebFetch tool to read the content before scoring.
  Do NOT use MinerU, Shell, or any file download tool.
- If WebFetch fails, fall back to whatever text is available."""

    prompt = f"""You are evaluating {len(papers)} academic papers for their relevance to a specific research direction.

Research direction: {direction}
Related keywords: {', '.join(keywords)}

{SCORING_CRITERIA}

Papers to evaluate:

{papers_text}
{fetch_instruction}

RESPONSE FORMAT (MANDATORY):
Return a JSON object where each key is the exact paper_id shown above in brackets.
The expected paper_ids are: [{id_list}]

Example format:
{{
  "VENUE_YEAR_001": {{"score": "A", "reason": "..."}},
  "VENUE_YEAR_002": {{"score": "C", "reason": "..."}}
}}

RULES:
- You MUST include ALL {len(papers)} paper_ids listed above. Do not skip any.
- Each paper_id key MUST exactly match the paper_id shown in brackets — do not invent or modify IDs.
- Each value MUST have "score" (one of S/A/B/C) and "reason" (1-3 sentences).
- Return ONLY the JSON object, no other text."""

    return prompt


# ---------------------------------------------------------------------------
# Parse subagent response
# ---------------------------------------------------------------------------

def parse_scoring_response(response: str) -> tuple[str, str]:
    """Parse a subagent's scoring response (single-paper mode).

    Returns (score, reason). Falls back to ("", "") if parsing fails.
    """
    # Try JSON extraction
    json_match = re.search(r'\{[^{}]*"score"[^{}]*\}', response, re.S)
    if json_match:
        try:
            data = json.loads(json_match.group())
            score = str(data.get("score", "")).strip().upper()
            reason = str(data.get("reason", "")).strip()
            if score in ("S", "A", "B", "C"):
                return score, reason
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback: look for score pattern in text
    score_match = re.search(r'\b(score|grade|rating)\s*[:=]\s*["\']?([SABC])["\']?', response, re.I)
    if score_match:
        score = score_match.group(2).upper()
        reason_match = re.search(r'\b(reason|explanation|rationale)\s*[:=]\s*["\']?(.+?)(?:["\']?\s*[,}]|$)', response, re.I | re.S)
        reason = reason_match.group(2).strip() if reason_match else "Parsed from unstructured response"
        return score, reason

    return "", f"Failed to parse scoring response: {response[:200]}"


def parse_batch_scoring_response(
    response: str,
    expected_ids: list[str],
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Parse a subagent's batch scoring response.

    Args:
        response: Raw subagent response text (should be a JSON object keyed by paper_id)
        expected_ids: The paper_ids that were sent in this batch

    Returns:
        (scores, missing_ids) where:
          scores: dict mapping paper_id -> (score, reason) for successfully parsed entries
          missing_ids: list of paper_ids that were expected but not found or failed to parse

    ID validation rules:
      - Only keys that exactly match an expected_id are accepted
      - Unknown keys (not in expected_ids) are silently ignored
      - Missing or malformed entries are reported in missing_ids for retry
    """
    expected_set = set(expected_ids)
    scores: dict[str, tuple[str, str]] = {}
    missing: list[str] = list(expected_ids)  # start with all, remove as found

    # Extract the outermost JSON object from the response
    # The response may contain markdown fences or extra text
    cleaned = response.strip()
    # Strip markdown code fences if present
    fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.S)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # Find the outermost { ... }
    brace_start = cleaned.find('{')
    if brace_start == -1:
        return scores, missing

    depth = 0
    brace_end = -1
    for i in range(brace_start, len(cleaned)):
        if cleaned[i] == '{':
            depth += 1
        elif cleaned[i] == '}':
            depth -= 1
            if depth == 0:
                brace_end = i
                break

    if brace_end == -1:
        return scores, missing

    json_str = cleaned[brace_start:brace_end + 1]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return scores, missing

    if not isinstance(data, dict):
        return scores, missing

    for pid in list(missing):
        if pid not in data:
            continue
        entry = data[pid]
        if not isinstance(entry, dict):
            continue
        score = str(entry.get("score", "")).strip().upper()
        reason = str(entry.get("reason", "")).strip()
        if score in ("S", "A", "B", "C"):
            scores[pid] = (score, reason)
            missing.remove(pid)

    return scores, missing


# ---------------------------------------------------------------------------
# Main agent review
# ---------------------------------------------------------------------------

_GRADE_ORDER = {"S": 3, "A": 2, "B": 1, "C": 0}


def review_score(
    paper: CandidatePaper,
    ai_score: str,
    ai_reason: str,
    direction: str,
) -> tuple[str, str]:
    """Review a subagent's score for obvious contradictions.

    Returns (adjusted_score, adjust_reason).
    If no adjustment needed, returns ("", "").

    Only adjusts when there's a clear mismatch between the score and
    observable evidence (title/abstract vs. direction alignment).
    """
    if not ai_score or ai_score not in _GRADE_ORDER:
        return "", ""

    title_lower = paper.title.lower()
    abstract_lower = paper.abstract_raw.lower() if paper.abstract_raw else ""
    direction_lower = direction.lower()

    direction_words = set(re.findall(r'\b\w{4,}\b', direction_lower))
    title_words = set(re.findall(r'\b\w{4,}\b', title_lower))
    overlap = direction_words & title_words
    overlap_ratio = len(overlap) / max(len(direction_words), 1)

    # Case 1: Scored S but title has almost no overlap with direction
    if ai_score == "S" and overlap_ratio < 0.1 and not paper.keyword_hits:
        return "A", f"Downgraded: title has minimal keyword overlap with direction (overlap={overlap_ratio:.0%})"

    # Case 2: Scored C but title strongly overlaps with direction
    if ai_score == "C" and overlap_ratio > 0.5:
        return "B", f"Upgraded: title has strong keyword overlap with direction (overlap={overlap_ratio:.0%})"

    # Case 3: Scored S/A but abstract explicitly states a very different domain
    # (This is a heuristic — only flag extreme cases)
    if ai_score in ("S", "A") and not paper.abstract_raw:
        pass  # Can't verify without abstract

    return "", ""


# ---------------------------------------------------------------------------
# Apply scores to candidates
# ---------------------------------------------------------------------------

def apply_scores(
    candidates: list[CandidatePaper],
    scores: dict[str, tuple[str, str]],
    direction: str,
    log: FilterLog | None = None,
) -> list[CandidatePaper]:
    """Apply subagent scores to candidates, run review, and set final_score.

    Args:
        candidates: List of CandidatePaper to score
        scores: Dict mapping paper_id -> (ai_score, ai_reason)
        direction: Research direction string
        log: Optional FilterLog for recording

    Returns the same list with scoring fields populated.
    """
    for p in candidates:
        if p.paper_id not in scores:
            continue

        ai_score, ai_reason = scores[p.paper_id]
        p.ai_score = ai_score
        p.ai_reason = ai_reason

        if log:
            log.log_scoring_result(p.paper_id, p.title, ai_score, ai_reason)

        adjusted, adjust_reason = review_score(p, ai_score, ai_reason, direction)
        if adjusted:
            p.review_adjusted = adjusted
            p.review_adjust_reason = adjust_reason
            p.final_score = adjusted
            if log:
                log.log_adjustment(p.paper_id, p.title, ai_score, adjusted, adjust_reason)
        else:
            p.final_score = ai_score

        p.importance = p.final_score

    # Final stats
    grade_counts = {"S": 0, "A": 0, "B": 0, "C": 0}
    for p in candidates:
        if p.final_score in grade_counts:
            grade_counts[p.final_score] += 1

    if log:
        log.final_s = grade_counts["S"]
        log.final_a = grade_counts["A"]
        log.final_b = grade_counts["B"]
        log.final_c = grade_counts["C"]

    print(f"[scorer] final distribution: S={grade_counts['S']}, A={grade_counts['A']}, "
          f"B={grade_counts['B']}, C={grade_counts['C']}")

    return candidates


# ---------------------------------------------------------------------------
# Orchestrator: single subagent that dispatches all batch scoring
# ---------------------------------------------------------------------------

SCORES_RAW_FILENAME = "scores_raw.json"


def build_orchestrator_prompt(
    research_index_path: str,
    direction: str,
    keywords: list[str],
    out_dir: str,
    scorer_lib_path: str,
) -> str:
    """Build the prompt for an orchestrator subagent.

    The orchestrator subagent will:
      1. Read research_index.csv to get all candidate papers
      2. Split into batches of 10
      3. For each batch, spawn a nested scorer subagent (Task, model="fast")
      4. Parse responses, retry failures with single-paper fallback
      5. Write all scores to scores_raw.json
      6. Return the path to scores_raw.json

    Args:
        research_index_path: Absolute path to research_index.csv
        direction: Research direction description
        keywords: List of keywords
        out_dir: Absolute path to output directory
        scorer_lib_path: Absolute path to search_literature_lib directory
    """
    keywords_str = ", ".join(keywords)
    scores_out = f"{out_dir}/{SCORES_RAW_FILENAME}"

    return f"""You are a scoring orchestrator. Your job is to score all candidate papers for relevance to a research direction by dispatching batches to nested scorer subagents.

TASK:
1. Read the file {research_index_path} (CSV) to get all candidate papers
2. Split papers into batches of 10
3. For each batch, use the Task tool to spawn a scorer subagent (subagent_type="generalPurpose", model="fast")
4. Parse each scorer's response, retry any failures with single-paper prompts
5. Write ALL collected scores to {scores_out}
6. Return the exact string: SCORES_WRITTEN:{scores_out}

RESEARCH DIRECTION: {direction}
KEYWORDS: {keywords_str}

STEP-BY-STEP INSTRUCTIONS:

Step 1 — Load candidates:
Read {research_index_path} using the Read tool. Parse it as CSV. Extract paper_id, title, venue, year, authors, abstract_raw, keywords_raw, paper_link, pdf_url for each row.

Step 2 — Build batch prompts:
Split all papers into batches of up to 10. For each batch, build a scoring prompt following this EXACT format:

---BEGIN BATCH PROMPT TEMPLATE---
You are evaluating N academic papers for their relevance to a specific research direction.

Research direction: {direction}
Related keywords: {keywords_str}

Scoring criteria for relevance to the research direction:

- S: Highly relevant. This paper directly addresses the same problem, proposes a closely related method, or is an essential baseline.
- A: Clearly relevant. The paper shares significant overlap in methodology, problem formulation, or application domain.
- B: Moderately relevant. The paper has some connection — perhaps a shared technique, a related but different problem, or useful background.
- C: Weakly relevant. The connection is peripheral — tangential topic, distant methodology, or only superficially related keywords.

Papers to evaluate:

[paper_id: XXXX]
  Title: ...
  Venue: ...
  Authors: ...
  Abstract: ...

[paper_id: YYYY]
  Title: ...
  ...

RESPONSE FORMAT (MANDATORY):
Return a JSON object where each key is the exact paper_id shown above in brackets.

Example format:
{{"XXXX": {{"score": "A", "reason": "..."}}, "YYYY": {{"score": "C", "reason": "..."}}}}

RULES:
- Include ALL paper_ids. Do not skip any.
- Each key MUST exactly match the paper_id in brackets.
- Each value MUST have "score" (S/A/B/C) and "reason" (1-3 sentences).
- Return ONLY the JSON object, no other text.
---END BATCH PROMPT TEMPLATE---

For papers WITH abstract_raw: include the abstract, do NOT include PDF URL.
For papers WITHOUT abstract_raw but with pdf_url: include PDF URL and add "[No abstract — you MUST read the PDF via WebFetch before scoring this paper]".
For papers with neither: add "[No abstract/PDF/link — title-only assessment, note low confidence in reason]".

Step 3 — Send each batch prompt as a Task:
Use Task tool with subagent_type="generalPurpose", model="fast" for each batch.
You may send 2-3 batches in parallel.

Step 4 — Parse responses:
For each scorer response, extract the JSON object. For each expected paper_id:
- If found with valid score (S/A/B/C) and reason: record it
- If missing or invalid: add to retry list

For retry papers, send individual prompts (one paper per Task) using the same scoring criteria.

Step 5 — Write scores:
Collect all scores into a single JSON object and write it to {scores_out}:
{{
  "paper_id_1": {{"score": "A", "reason": "..."}},
  "paper_id_2": {{"score": "S", "reason": "..."}},
  ...
}}

Use the Write tool to create {scores_out} with this JSON content.

Step 6 — Return confirmation:
After writing, respond with exactly: SCORES_WRITTEN:{scores_out}

CONSTRAINTS:
- paper_id is the ONLY matching key. Never use list index, sequence number, or title.
- Do NOT modify paper_ids. Copy them exactly from the CSV.
- Do NOT skip any paper. Every paper_id in the CSV must appear in the output JSON.
- Keep your own output minimal. Do not narrate each step — just execute."""


def load_scores_file(scores_path: str) -> dict[str, tuple[str, str]]:
    """Load scores_raw.json written by the orchestrator subagent.

    Returns dict mapping paper_id -> (score, reason).
    Validates that each entry has a valid score.
    """
    from pathlib import Path
    path = Path(scores_path)
    if not path.exists():
        raise FileNotFoundError(f"Scores file not found: {scores_path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {scores_path}, got {type(data).__name__}")

    scores: dict[str, tuple[str, str]] = {}
    invalid: list[str] = []
    for pid, entry in data.items():
        if not isinstance(entry, dict):
            invalid.append(pid)
            continue
        score = str(entry.get("score", "")).strip().upper()
        reason = str(entry.get("reason", "")).strip()
        if score in ("S", "A", "B", "C"):
            scores[pid] = (score, reason)
        else:
            invalid.append(pid)

    if invalid:
        print(f"[scorer] WARNING: {len(invalid)} entries with invalid scores: {invalid[:5]}...")

    print(f"[scorer] loaded {len(scores)} scores from {scores_path}")
    return scores
