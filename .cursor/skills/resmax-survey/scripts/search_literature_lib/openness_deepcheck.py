"""Openness deep-check for S/A candidate papers (Stage 3.5).

Complements the lightweight global enrichment in `resmax-database` by
performing higher-cost, higher-signal checks on a small subset of papers
(typically just the S/A tier or all candidates).

Three levels, composable:

  Level A — passthrough (deterministic, zero network)
    Copy openness fields already populated on accepted_index.csv:
      code_url, code_is_real, code_stars, code_last_commit,
      code_primary_language, has_pretrained_weights, has_dataset

  Level B — HuggingFace Hub lookup (one API call per arxiv_id)
    For papers with arxiv_id, query the Hub for models/datasets tagged
    with that ID. Sets `hf_models`, `hf_datasets`.

  Level C — Agent-based repo review (prompt builder; caller dispatches)
    Returns a prompt per candidate that asks an agent to visit the repo
    URL, read README/top-level structure, and return a structured JSON
    verdict. Main agent is responsible for dispatching Task calls.

Extensibility hooks (documented, not implemented here):
  - PDF first-page scan for github URLs → `scan_pdf_for_code_urls(pdf_path)`
  - arXiv TeX source inspection          → `fetch_arxiv_source(arxiv_id)`
  - CodaLab / official code dumps        → `probe_codalab(paper)`

All functions are safe to call with partial data (missing arxiv_id, no
code_url, etc.). They return structured dicts and never raise.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .models import CandidatePaper


HF_API_URL = "https://huggingface.co/api"


# ---------------------------------------------------------------------------
# Level A: passthrough from accepted_index (fields already enriched globally)
# ---------------------------------------------------------------------------

PASSTHROUGH_FIELDS = [
    "code_url",
    "code_is_real",
    "code_stars",
    "code_last_commit",
    "code_primary_language",
    "has_pretrained_weights",
    "has_dataset",
]


def passthrough_openness_fields(
    candidate: CandidatePaper, source_row: dict
) -> dict[str, str]:
    """Copy pre-enriched openness fields from the accepted_index row.

    Writes directly onto the candidate object as attributes
    (if the attribute exists) and returns a dict of what was copied.
    """
    copied: dict[str, str] = {}
    for name in PASSTHROUGH_FIELDS:
        val = (source_row.get(name, "") or "").strip()
        if not val:
            continue
        copied[name] = val
        if hasattr(candidate, name):
            setattr(candidate, name, val)
    return copied


# ---------------------------------------------------------------------------
# Level B: HuggingFace Hub lookup by arxiv_id
# ---------------------------------------------------------------------------

def _hf_get(path: str, timeout: int = 15) -> Optional[list | dict]:
    url = f"{HF_API_URL}{path}" if path.startswith("/") else path
    req = urllib.request.Request(
        url, headers={"User-Agent": "resmax-survey-deepcheck/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None
    except Exception:
        return None


def hf_lookup_by_arxiv(arxiv_id: str) -> dict[str, list[str]]:
    """Return {"models": [...], "datasets": [...]} linked to arxiv_id.

    Only entries where arxiv_id appears in tags OR in the id itself are
    kept, to avoid false-positive title-substring matches.
    """
    result = {"models": [], "datasets": []}
    if not arxiv_id or not arxiv_id.strip():
        return result
    aid = arxiv_id.strip()

    def _match(entry: dict) -> bool:
        tags = entry.get("tags", []) or []
        entry_id = entry.get("id", "") or entry.get("modelId", "") or ""
        tag_str = " ".join(tags) if isinstance(tags, list) else str(tags)
        return aid in tag_str or aid in entry_id or f"arxiv:{aid}" in tag_str

    models = _hf_get(f"/models?search={urllib.parse.quote(aid)}&limit=10")
    if isinstance(models, list):
        for m in models:
            if _match(m):
                result["models"].append(m.get("id", "") or m.get("modelId", ""))

    datasets = _hf_get(f"/datasets?search={urllib.parse.quote(aid)}&limit=10")
    if isinstance(datasets, list):
        for d in datasets:
            if _match(d):
                result["datasets"].append(d.get("id", ""))

    return result


# ---------------------------------------------------------------------------
# Level C: agent prompt for repo quality review
# ---------------------------------------------------------------------------

REPO_REVIEW_PROMPT_TEMPLATE = """You are reviewing the openness of an academic paper.
Decide whether the authors have released a **real implementation** that would let
a researcher reproduce the paper's main results, or only a project page /
skeleton / placeholder.

PAPER
  Title: {title}
  Venue: {venue}
  Abstract (excerpt):
    {abstract_excerpt}

KNOWN LINKS (at least one is present — they may be inconsistent, cross-check them)
  Primary code URL (from accepted list): {code_url}
  GitHub URLs mined from paper body:      {paper_github_urls}
  Project/page URL:                        {project_url}
  Repo stars (if known):                   {stars}
  Last push (if known):                    {last_commit}
  Primary language (if known):             {primary_lang}

TASK
  1. WebFetch the most authoritative URL first (prefer a github.com/<owner>/<repo>
     mined from the paper body; otherwise fall back to the primary code URL; otherwise
     the project page).
  2. If you land on a project page, look for a GitHub link on that page and WebFetch it.
  3. If the github URL is a 404, empty, or obviously a template, report accordingly.
  4. Read README, top-level file listing, and any `scripts/` or `configs/` directory.
  5. Assess whether the repo contains:
     - Actual training/inference code for the paper's method?
     - A requirements/environment file?
     - Config files or scripts to reproduce the main table/figure?
     - Pretrained weights (links or checkpoints) — including HuggingFace, Drive, etc.?
     - Dataset (included, linked, or documented)?

OUTPUT — return ONLY a JSON object with these keys:
{{
  "resolved_repo_url": "the github URL you actually reviewed, or \\"\\" if none reachable",
  "code_quality": "full" | "partial" | "skeleton" | "dead" | "project_page_only",
  "has_pretrained_weights_confirmed": "yes" | "no" | "linked",
  "has_dataset_confirmed": "public" | "private" | "standard" | "unknown",
  "reproduction_readiness": 0-5 integer,
  "notes": "one-sentence justification (include star count and last push date if seen)"
}}

Definitions:
  full               = training + inference + config, runnable end-to-end
  partial            = inference only, OR missing configs/scripts
  skeleton           = README promise + stub code, not runnable
  dead               = 404, empty, or last commit > 2 years before paper year
  project_page_only  = only a project page exists, no code repo reachable

Return nothing else. No markdown fences, no prose outside the JSON."""


def _pick_project_url(candidate: CandidatePaper) -> str:
    """Return the non-github code_url if any, otherwise empty."""
    code_url = (getattr(candidate, "code_url", "") or "").strip()
    if code_url and "github.com/" not in code_url.lower():
        return code_url
    return ""


def build_repo_review_prompt(
    candidate: CandidatePaper, abstract_char_limit: int = 600
) -> Optional[str]:
    """Return a repo-review prompt, or None if there is nothing to review.

    The prompt is emitted whenever ANY of these is present:
      - `code_url` (github or project page)
      - `paper_github_urls` mined from the paper source (Stage 5.5.a)

    This is deliberately looser than the previous github-only constraint,
    because 3DGS / CV papers frequently publish only a project page in the
    accepted list; the real github repo is mined from the paper body or
    the project page itself by the reviewing agent.
    """
    code_url = (getattr(candidate, "code_url", "") or "").strip()
    paper_github_urls = (getattr(candidate, "paper_github_urls", "") or "").strip()

    if not code_url and not paper_github_urls:
        return None

    abstract = (candidate.abstract_raw or "")[:abstract_char_limit]
    if len(candidate.abstract_raw or "") > abstract_char_limit:
        abstract += " ..."

    project_url = _pick_project_url(candidate)

    return REPO_REVIEW_PROMPT_TEMPLATE.format(
        title=candidate.title,
        venue=f"{candidate.venue} {candidate.year}",
        abstract_excerpt=abstract or "(no abstract available)",
        code_url=code_url or "(none)",
        paper_github_urls=paper_github_urls or "(none found in paper body)",
        project_url=project_url or "(none)",
        stars=getattr(candidate, "code_stars", "") or "?",
        last_commit=(getattr(candidate, "code_last_commit", "") or "?")[:10],
        primary_lang=getattr(candidate, "code_primary_language", "") or "?",
    )


# ---------------------------------------------------------------------------
# Future hooks — not implemented; raise NotImplementedError so callers can
# detect them and fall back gracefully.
# ---------------------------------------------------------------------------

def scan_pdf_for_code_urls(pdf_path: str) -> list[str]:
    """Extract github / project URLs from a downloaded PDF.

    Reserved for a future implementation that uses pdfplumber / pypdf to
    read the first page footnote (where most papers declare their repo).
    """
    raise NotImplementedError(
        "scan_pdf_for_code_urls: implement with pdfplumber when PDF downloads are wired in"
    )


def fetch_arxiv_source(arxiv_id: str) -> Optional[str]:
    """Download the arXiv .tar.gz LaTeX source and return extracted path.

    Reserved for a future implementation. LaTeX source often contains the
    canonical code URL in \\url{...} or comments.
    """
    raise NotImplementedError(
        "fetch_arxiv_source: implement when we need LaTeX-source-level enrichment"
    )


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

def enrich_openness_deep(
    candidates: list[CandidatePaper],
    accepted_index_rows_by_id: dict[str, dict],
    enable_hf: bool = True,
    hf_rate_limit_delay: float = 0.3,
    verbose: bool = True,
) -> dict[str, dict]:
    """Run Level A + Level B on every candidate.

    Args:
      candidates: list of CandidatePaper (typically post-scoring, S/A only)
      accepted_index_rows_by_id: {paper_id: row_dict} from accepted_index.csv
      enable_hf: if False, skip HuggingFace Hub lookups
      hf_rate_limit_delay: sleep between HF API calls
      verbose: print per-paper progress

    Returns:
      Dict mapping paper_id -> deepcheck result dict:
        {
          "passthrough": {...},    # fields copied from accepted_index
          "hf_models": [...],      # HuggingFace model IDs
          "hf_datasets": [...],    # HuggingFace dataset IDs
          "repo_review_prompt": str or None,  # None if no code_url
        }

    Level C (repo review) prompts are returned but NOT dispatched here —
    the caller (main agent) is responsible for running them via Task().
    """
    results: dict[str, dict] = {}

    for i, cand in enumerate(candidates):
        entry = {
            "passthrough": {},
            "hf_models": [],
            "hf_datasets": [],
            "repo_review_prompt": None,
        }

        # Level A
        row = accepted_index_rows_by_id.get(cand.paper_id, {})
        if row:
            entry["passthrough"] = passthrough_openness_fields(cand, row)

        # Level B
        if enable_hf and cand.arxiv_id:
            hf = hf_lookup_by_arxiv(cand.arxiv_id)
            entry["hf_models"] = hf["models"]
            entry["hf_datasets"] = hf["datasets"]
            if hf["models"] and not getattr(cand, "has_pretrained_weights", ""):
                cand.has_pretrained_weights = "yes"
            if hf["datasets"] and not getattr(cand, "has_dataset", ""):
                cand.has_dataset = "public"
            time.sleep(hf_rate_limit_delay)

        # Level C (prompt only)
        entry["repo_review_prompt"] = build_repo_review_prompt(cand)

        results[cand.paper_id] = entry

        if verbose:
            has_code = "Y" if entry["passthrough"].get("code_url") else "-"
            hf_m = len(entry["hf_models"])
            hf_d = len(entry["hf_datasets"])
            print(
                f"  [{i + 1}/{len(candidates)}] {cand.paper_id[:40]:<40} "
                f"code={has_code} hf_m={hf_m} hf_d={hf_d}",
                flush=True,
            )

    return results


def write_deepcheck_results_md(
    candidates: list[CandidatePaper],
    review_results: dict[str, dict],
    out_path,
    *,
    grade_filter: set[str] | None = None,
    missing_pdf_ids: set[str] | None = None,
    title: str = "Stage 5.5 Deep Check Results (S papers)",
    note_char_limit: int = 220,
) -> int:
    """Render a human-readable Markdown table summarising repo reviews.

    Writes one row per candidate selected by `grade_filter` (default {"S"}).
    Papers without a review are still emitted with `unknown` columns and a
    short Notes cell explaining why (no code link, missing PDF, ...).

    Parameters
    ----------
    candidates : list of CandidatePaper (ordered)
    review_results : dict[paper_id -> review json]
    out_path : str | Path
    grade_filter : optional set of final_score values to include (default {"S"})
    missing_pdf_ids : optional set of paper_ids that terminated with no PDF
                      copy (used to render a specific 'PDF unavailable' note)
    title : markdown H1 title
    note_char_limit : truncate notes to this many chars (adds '...' suffix)

    Returns the number of rows written.
    """
    from datetime import datetime, timezone
    from pathlib import Path

    grade_set = grade_filter if grade_filter else {"S"}
    missing_pdf_ids = missing_pdf_ids or set()
    lines = [
        f"# {title}",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| Paper | Resolved Repo | Quality | Weights | Dataset | Readiness | Notes |",
        "|-------|---------------|---------|---------|---------|-----------|-------|",
    ]
    rows_written = 0
    for cand in candidates:
        if cand.final_score not in grade_set:
            continue
        review = review_results.get(cand.paper_id) if isinstance(review_results, dict) else None
        title_short = (cand.title or "")[:50]
        if review and isinstance(review, dict):
            resolved = (review.get("resolved_repo_url") or "").strip() or "—"
            quality = review.get("code_quality", "") or "unknown"
            weights = review.get("has_pretrained_weights_confirmed", "") or "unknown"
            dataset = review.get("has_dataset_confirmed", "") or "unknown"
            try:
                readiness = int(review.get("reproduction_readiness", 0) or 0)
            except (TypeError, ValueError):
                readiness = 0
            notes = (review.get("notes") or "").strip().replace("|", "/")
        else:
            resolved = "—"
            quality = "unknown"
            weights = "unknown"
            dataset = "unknown"
            readiness = 0
            if cand.paper_id in missing_pdf_ids:
                notes = "PDF unavailable (no_oa_copy_found terminal). See deepcheck_missing_pdf.json."
            else:
                notes = "No reviewable code/project link found in accepted_index or paper source."
        if len(notes) > note_char_limit:
            notes = notes[:note_char_limit].rstrip() + "..."
        lines.append(
            f"| {title_short} | {resolved} | {quality} | {weights} | {dataset} | "
            f"{readiness}/5 | {notes} |"
        )
        rows_written += 1
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows_written


def apply_repo_review_results(
    candidates: list[CandidatePaper],
    review_results: dict[str, dict],
) -> int:
    """Merge agent-returned repo reviews back onto candidates.

    Args:
      candidates: list of CandidatePaper
      review_results: {paper_id: {code_quality, has_pretrained_weights_confirmed, ...}}

    Writes these dataclass fields if present on the candidate:
      - code_quality
      - has_pretrained_weights (overrides if review says yes/no)
      - has_dataset (overrides if review says public/private)
      - reproduction_readiness

    Returns count of candidates updated.
    """
    updated = 0
    for cand in candidates:
        review = review_results.get(cand.paper_id)
        if not review or not isinstance(review, dict):
            continue
        resolved = (review.get("resolved_repo_url") or "").strip()
        if resolved and hasattr(cand, "code_url"):
            # Overwrite code_url when the review found a real repo that
            # differs from the (often project-page) value passed in.
            if "github.com/" in resolved.lower() and (
                not cand.code_url or "github.com/" not in cand.code_url.lower()
            ):
                cand.code_url = resolved
        cq = review.get("code_quality", "") or ""
        if cq and hasattr(cand, "code_quality"):
            cand.code_quality = cq
        pw = review.get("has_pretrained_weights_confirmed", "") or ""
        if pw in ("yes", "linked") and hasattr(cand, "has_pretrained_weights"):
            cand.has_pretrained_weights = "yes"
        elif pw == "no" and hasattr(cand, "has_pretrained_weights"):
            cand.has_pretrained_weights = "no"
        ds = review.get("has_dataset_confirmed", "") or ""
        if ds in ("public", "private", "standard") and hasattr(cand, "has_dataset"):
            cand.has_dataset = ds if ds != "standard" else "standard_only"
        rr = review.get("reproduction_readiness", None)
        if rr is not None and hasattr(cand, "reproduction_readiness"):
            try:
                cand.reproduction_readiness = int(rr)
            except (TypeError, ValueError):
                pass
        updated += 1
    return updated
