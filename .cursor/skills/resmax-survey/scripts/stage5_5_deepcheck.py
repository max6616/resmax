#!/usr/bin/env python3
"""Stage 5.5 deepcheck runner — usable on an already-scored research_index.

Reads an existing `research_index.csv` produced by stages 1-5, filters by
`final_score` (default S), and runs:

  * Stage 3.5 re-apply (Level A passthrough + Level B HuggingFace Hub)
  * Stage 5.5.a paper-source fetch (arxiv-to-prompt; mineru fallback list)
  * Stage 5.5.b repo-review prompt emission (with mined github URLs)

Outputs (in the direction's out-dir):

  * `research_index.csv`           — updated in place with deepcheck columns
  * `deepcheck_prompts.json`       — agent-dispatchable prompts (Stage 5.5.b)
  * `deepcheck_missing_source.json` — candidates that need mineru fallback;
                                      the main agent picks these up, calls
                                      the MinerU MCP tool, then invokes
                                      `register_mineru_md()` via a follow-up
                                      run.
  * `paper_sources/<paper_id>.tex` — cached LaTeX source (or `.md` after
                                      mineru)

This script is NON-AGENT: it does not dispatch Task subagents. The main
agent reads `deepcheck_prompts.json` and runs the reviews, then calls
`apply_repo_review_results()` and re-runs this script to persist the
results back into the CSV.

Example:
    python3 stage5_5_deepcheck.py \
        --dir literature_research/4dgs_editing \
        --accepted paper_database/accepted_index.csv \
        --grades S
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dir", required=True, help="literature_research/<slug> directory")
    p.add_argument("--accepted", required=True, help="paper_database/accepted_index.csv")
    p.add_argument("--grades", default="S", help="Comma-separated final_score grades to deepcheck (default: S)")
    p.add_argument("--enable-hf", action="store_true", default=True, help="Run HuggingFace Hub lookup")
    p.add_argument("--no-hf", dest="enable_hf", action="store_false")
    p.add_argument("--hf-delay", type=float, default=0.3, help="Sleep between HF API calls")
    p.add_argument("--overwrite-sources", action="store_true", help="Ignore cached tex/md and refetch")
    p.add_argument("--disable-oa-api", action="store_true",
                   help="Skip OA aggregator fallback (Unpaywall/OpenAlex/S2)")
    p.add_argument("--disable-sci-hub", action="store_true",
                   help="Skip Sci-Hub gray fallback (opt-out; on by default)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from search_literature_lib.models import (
        load_research_index, write_research_index, RESEARCH_INDEX_FIELDS,
    )
    from search_literature_lib.openness_deepcheck import (
        passthrough_openness_fields, hf_lookup_by_arxiv, build_repo_review_prompt,
    )
    from search_literature_lib.paper_source_fetch import (
        fetch_and_cache_source, derive_pdf_candidates, HAS_ARXIV_TO_PROMPT,
    )

    out_dir = Path(args.dir).resolve()
    if not out_dir.exists():
        print(f"[ERROR] direction dir not found: {out_dir}", file=sys.stderr)
        return 1

    index_path = out_dir / "research_index.csv"
    if not index_path.exists():
        print(f"[ERROR] research_index.csv not found in {out_dir}", file=sys.stderr)
        return 1

    accepted_path = Path(args.accepted).resolve()
    if not accepted_path.exists():
        print(f"[ERROR] accepted_index not found: {accepted_path}", file=sys.stderr)
        return 1

    grades = {g.strip().upper() for g in args.grades.split(",") if g.strip()}

    candidates = load_research_index(index_path)
    selected = [c for c in candidates if c.final_score in grades]
    print(f"[deepcheck] loaded {len(candidates)} candidates; selected {len(selected)} with final_score in {grades}")

    if not selected:
        print("[deepcheck] nothing to do")
        return 0

    csv.field_size_limit(10 * 1024 * 1024)
    rows_by_id: dict[str, dict] = {}
    with accepted_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            pid = row.get("paper_id", "")
            if pid:
                rows_by_id[pid] = row

    # --- Level A passthrough ---
    for cand in selected:
        row = rows_by_id.get(cand.paper_id, {})
        if row:
            passthrough_openness_fields(cand, row)

    # --- Level B HuggingFace Hub ---
    if args.enable_hf:
        import time as _time
        for cand in selected:
            if not cand.arxiv_id:
                continue
            hf = hf_lookup_by_arxiv(cand.arxiv_id)
            cand.hf_models = ";".join(hf["models"]) if hf["models"] else cand.hf_models
            cand.hf_datasets = ";".join(hf["datasets"]) if hf["datasets"] else cand.hf_datasets
            if hf["models"] and not cand.has_pretrained_weights:
                cand.has_pretrained_weights = "yes"
            if hf["datasets"] and not cand.has_dataset:
                cand.has_dataset = "public"
            _time.sleep(args.hf_delay)

    # --- Stage 5.5.a Paper-source fetch (three-layer: TeX + PDF + pre-existing MD) ---
    if not HAS_ARXIV_TO_PROMPT:
        print("[WARN] arxiv-to-prompt not installed; TeX path unavailable — run `pip install arxiv-to-prompt`")

    src_cache = out_dir / "paper_sources"
    missing_source: list[dict] = []
    missing_pdf: list[dict] = []
    for cand in selected:
        row = rows_by_id.get(cand.paper_id, {})
        # Derive PDF fallback candidates from every identifier the paper has.
        # accepted_index doesn't currently store `doi`, but this future-proofs
        # the plumbing once resmax-database is fixed to populate it.
        doi_value = row.get("doi", "")
        pdf_candidates = derive_pdf_candidates(
            pdf_url=cand.pdf_url or row.get("pdf_url", ""),
            arxiv_id=cand.arxiv_id or row.get("arxiv_id", ""),
            openreview_forum_id=row.get("openreview_forum_id", ""),
            doi=doi_value,
            paper_link=cand.paper_link or row.get("paper_link", ""),
        )
        desc = fetch_and_cache_source(
            cand.paper_id, cand.arxiv_id, src_cache,
            pdf_url_candidates=pdf_candidates,
            doi=doi_value,
            title=cand.title,
            enable_oa_api=not args.disable_oa_api,
            enable_sci_hub=not args.disable_sci_hub,
            overwrite=args.overwrite_sources,
        )
        cand.source_cache_path = desc["paper_dir"]
        # Only list "reader" tags in source_cache_type; arxiv tarball is
        # a raw archive companion to tex, no downstream reader uses it directly.
        reader_tags = [t for t in desc["sources_present"] if t != "arxiv"]
        cand.source_cache_type = ",".join(reader_tags) if reader_tags else "none"
        merged_urls = list(desc["github_urls"]) + [
            u for u in desc["project_page_urls"] if u not in desc["github_urls"]
        ]
        cand.paper_github_urls = ";".join(merged_urls)

        def _tag_chars(tag: str) -> int:
            return desc["text_chars"].get(tag, 0)

        errs = "; ".join(f"{k}:{v}" for k, v in desc["errors"].items() if v)
        print(
            f"  [src] {cand.paper_id[:55]:<55} "
            f"have={','.join(desc['sources_present']) or 'none':<20} "
            f"chars[tex/pdf/md]={_tag_chars('tex')}/{_tag_chars('pdftxt')}/{_tag_chars('md')} "
            f"gh={len(desc['github_urls'])} io={len(desc['project_page_urls'])} "
            f"{('| ' + errs) if errs else ''}"
        )

        # Need MinerU fallback only when NEITHER tex nor pdf text-layer worked.
        has_readable = ("tex" in desc["sources_present"]) or ("pdf" in desc["sources_present"])
        if not has_readable:
            missing_source.append({
                "paper_id": cand.paper_id,
                "title": cand.title,
                "arxiv_id": cand.arxiv_id,
                "pdf_url": cand.pdf_url,
                "paper_link": cand.paper_link,
                "paper_dir": desc["paper_dir"],
                "errors": desc["errors"],
            })
        # Track PDF-specifically missing papers (every paper MUST have a PDF).
        if "pdf" not in desc["sources_present"]:
            fallback = desc["errors"].get("pdf_fallback", {}) or {}
            oa_info = fallback.get("oa_api", {})
            sh_info = fallback.get("sci_hub", {})
            # Terminal category after full fallback chain:
            #   no_oa_copy_found : OA APIs unanimously is_oa=False AND Sci-Hub
            #                      explicitly reports "not in database". This is
            #                      a documented dead-end, not a retriable error.
            #   fallback_failed  : some layer errored/rate-limited; worth a retry.
            #   unknown          : fallback chain not fully run (e.g. no doi/title).
            oa_ran = "oa_api" in fallback
            sh_ran = "sci_hub" in fallback
            if oa_ran and (oa_info.get("is_oa_any") is False) and sh_ran and (not sh_info.get("ok")):
                category = "no_oa_copy_found"
                hint = (
                    "All legal OA aggregators agree no author self-archived copy "
                    "exists AND Sci-Hub has no entry. This paper genuinely has "
                    "no automatically retrievable PDF. Options: (1) drop it from "
                    "deep-check, (2) mark for institutional-network retry later, "
                    "(3) request PDF from authors directly."
                )
            elif oa_ran or sh_ran:
                category = "fallback_failed"
                hint = (
                    "Fallback chain ran but didn't yield a PDF. Check attempt "
                    "errors below; common causes: transient 429/5xx, mirror "
                    "domain rotation, title mismatch. Re-running may help."
                )
            else:
                category = "unknown"
                hint = (
                    "Fallback chain not invoked (likely no DOI and no title). "
                    "Fix the upstream resmax-database data or pass a title."
                )
            missing_pdf.append({
                "paper_id": cand.paper_id,
                "title": cand.title,
                "paper_dir": desc["paper_dir"],
                "category": category,
                "pdf_candidates_tried": [a["url"] for a in desc["errors"].get("pdf_attempts", [])],
                "attempt_errors": desc["errors"].get("pdf_attempts", []),
                "fallback_diagnostic": fallback,
                "hint": hint,
            })

    # --- Stage 5.5.b Repo-review prompt emission ---
    prompts_payload: dict[str, dict] = {}
    for cand in selected:
        prompt = build_repo_review_prompt(cand)
        if not prompt:
            continue
        prompts_payload[cand.paper_id] = {
            "title": cand.title,
            "code_url": cand.code_url,
            "paper_github_urls": cand.paper_github_urls,
            "ai_score": cand.ai_score,
            "final_score": cand.final_score,
            "source_cache_path": cand.source_cache_path,
            "source_cache_type": cand.source_cache_type,
            "prompt": prompt,
        }

    prompts_file = out_dir / "deepcheck_prompts.json"
    prompts_file.write_text(
        json.dumps(prompts_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[deepcheck] wrote {len(prompts_payload)} prompts -> {prompts_file.name}")

    missing_file = out_dir / "deepcheck_missing_source.json"
    missing_file.write_text(
        json.dumps(missing_source, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if missing_source:
        print(
            f"[deepcheck] {len(missing_source)} selected papers have NO readable source -> "
            f"{missing_file.name}; agent should run MinerU or the user must supply the PDF"
        )

    # PDFs specifically: every paper must have paper.pdf. Surface the gaps loudly.
    missing_pdf_file = out_dir / "deepcheck_missing_pdf.json"
    missing_pdf_file.write_text(
        json.dumps(missing_pdf, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if missing_pdf:
        from collections import Counter
        cat_counts = Counter(m["category"] for m in missing_pdf)
        print(f"[deepcheck] !! {len(missing_pdf)} selected papers have NO paper.pdf yet:")
        for cat, n in cat_counts.most_common():
            print(f"    category={cat}: {n}")
        for m in missing_pdf:
            print(f"    - [{m['category']}] {m['paper_id'][:70]}")
            for att in m["attempt_errors"][:5]:
                print(f"        tried: {att['url'][:100]} -> {att['error'][:80]}")
            fallback = m.get("fallback_diagnostic") or {}
            if fallback.get("oa_api"):
                oa = fallback["oa_api"]
                print(f"        oa_api: is_oa_any={oa.get('is_oa_any')} "
                      f"recovered_doi={oa.get('recovered_doi','') or '-'} "
                      f"recovered_arxiv={oa.get('recovered_arxiv_id','') or '-'} "
                      f"found_urls={oa.get('pdf_urls_found')}")
            if fallback.get("sci_hub"):
                sh = fallback["sci_hub"]
                mirrors_tried = len(sh.get("evidence") or [])
                print(f"        sci_hub: ok={sh.get('ok')} mirrors_tried={mirrors_tried} "
                      f"error={sh.get('error','') or '-'}")
            print(f"      hint: {m['hint']}")

    # --- Persist back to research_index.csv (full schema rewrite) ---
    write_research_index(index_path, candidates)
    print(f"[deepcheck] updated {index_path.name} with {len(RESEARCH_INDEX_FIELDS)} columns")

    # Quick summary
    with_code = sum(1 for c in selected if c.code_url)
    with_paper_gh = sum(1 for c in selected if c.paper_github_urls)
    with_source = sum(1 for c in selected if c.source_cache_type and c.source_cache_type != "none")
    with_pdf = sum(1 for c in selected if c.source_cache_type and "pdf" in c.source_cache_type.split(","))
    print(
        f"[deepcheck] summary (on {len(selected)} selected): "
        f"code_url={with_code}, paper_github_urls={with_paper_gh}, "
        f"source_cached={with_source}, pdf_cached={with_pdf}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
