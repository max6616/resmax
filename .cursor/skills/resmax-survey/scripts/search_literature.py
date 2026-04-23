#!/usr/bin/env python3
"""Search related literature from the paper database for a given research direction.

Pipeline:
  1.   Dual-path retrieval: keyword (~50) + embedding (~50)
  2.   Dedup & merge (≤100 candidates)
  3.   Meta enrichment (ensure abstract + PDF link)
  3.5. Openness deepcheck (HF Hub lookup + repo-review prompt emission)
  4.   Generate unscored literature document
  5.   [Agent mode] Subagent per-paper scoring
  5.5. [Agent mode, optional] Dispatch repo-review prompts for S/A papers
  6.   [Agent mode] Main agent review
  7.   Sort by grade, generate final scored document

Stages 5-7 require the Cursor agent environment (subagent dispatch).
In script mode, the pipeline stops after stage 4 and outputs an unscored
document + CSV plus a `deepcheck_prompts.json` for the agent to pick up.

Examples:
  python3 search_literature.py \\
    --accepted paper_database/accepted_index.csv \\
    --direction "4D Gaussian Splatting for dynamic scene editing" \\
    --keywords "4DGS,gaussian splatting,dynamic scene editing,deformable Gaussian" \\
    --out-dir literature_research/4dgs_editing
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Auto-load .secrets/*.env and .localconfig/*.env into os.environ.
# File path: .cursor/skills/resmax-survey/scripts/search_literature.py
# parents: [0]=scripts, [1]=resmax-survey, [2]=skills
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
import secrets_loader  # noqa: E402,F401


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Search related literature from paper database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--accepted", required=True, help="Path to accepted_index.csv")
    p.add_argument("--direction", required=True, help="Research direction description")
    p.add_argument("--keywords", required=True, help="Comma-separated keywords")
    p.add_argument("--out-dir", default="", help="Output directory (default: literature_research/<direction_slug>)")
    p.add_argument("--config", default="", help="Path to config JSON (default: auto-detect)")
    p.add_argument("--cache-path", default="", help="Path to embedding cache .npz (default: from config)")
    p.add_argument("--device", default="cpu", help="Device for query encoding: cuda, mps, cpu")
    p.add_argument("--dim", type=int, default=0, help="Embedding dimension (0=use config)")

    p.add_argument("--embedding-top-k", type=int, default=0, help="Embedding top-K (0=use config)")
    p.add_argument("--keyword-top-k", type=int, default=0, help="Keyword top-K (0=use config)")
    p.add_argument("--max-candidates", type=int, default=0, help="Max merged candidates (0=use config)")

    return p.parse_args(argv)


def load_config(config_path: str) -> dict:
    if config_path and Path(config_path).exists():
        return json.loads(Path(config_path).read_text(encoding="utf-8"))
    default = Path(__file__).resolve().parent.parent / "config" / "default_config.json"
    if default.exists():
        return json.loads(default.read_text(encoding="utf-8"))
    return {}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)

    accepted_path = Path(args.accepted).resolve()
    if not accepted_path.exists():
        print(f"[ERROR] accepted index not found: {accepted_path}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from search_literature_lib.models import (
        load_accepted_index, write_research_index, direction_slug,
    )

    papers = load_accepted_index(accepted_path)
    print(f"[search] loaded {len(papers)} papers from {accepted_path}")

    emb_config = config.get("embedding", {})
    retrieval_config = config.get("retrieval", {})
    output_config = config.get("output", {})

    if args.cache_path:
        cache_path = Path(args.cache_path).resolve()
    else:
        cache_dir = Path(emb_config.get("cache_dir", "paper_database/embedding_cache"))
        if not cache_dir.is_absolute():
            cache_dir = Path.cwd() / cache_dir
        cache_filename = emb_config.get("cache_filename", "qwen3_8b.npz")
        cache_path = cache_dir / cache_filename

    model_name = emb_config.get("model_name", "Qwen/Qwen3-Embedding-8B")
    dimension = args.dim or emb_config.get("dimension", 0)
    instruction = emb_config.get("instruction_prefix", "")

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if not keywords:
        print("[ERROR] --keywords must contain at least one keyword", file=sys.stderr)
        return 1

    slug = direction_slug(args.direction)
    out_dir = Path(args.out_dir) if args.out_dir else Path("literature_research") / slug
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    lit_doc_path = out_dir / output_config.get("literature_doc_filename", "literature_list.md")
    index_path = out_dir / output_config.get("research_index_filename", "research_index.csv")
    log_path = out_dir / output_config.get("filter_log_filename", "filter_log.md")

    from search_literature_lib.keyword_filter import keyword_retrieve
    from search_literature_lib.embedding_filter import embedding_retrieve
    from search_literature_lib.candidate_merge import merge_candidates
    from search_literature_lib.meta_enrich import enrich_candidates
    from search_literature_lib.literature_doc import generate_unscored
    from search_literature_lib.filter_logger import FilterLog

    log = FilterLog(
        direction=args.direction,
        keywords=keywords,
        start_time=time.time(),
    )

    # --- Stage 1: Dual-path retrieval ---
    emb_top_k = args.embedding_top_k or retrieval_config.get("embedding_top_k", 50)
    kw_top_k = args.keyword_top_k or retrieval_config.get("keyword_top_k", 50)

    print(f"\n{'='*60}")
    print(f"[Stage 1] Dual-path retrieval")
    print(f"{'='*60}")

    keyword_results = None
    embedding_results = None

    with log.start_stage("retrieval"):
        try:
            keyword_results = keyword_retrieve(papers, keywords, top_k=kw_top_k)
            log.keyword_total_matches = sum(1 for p in papers
                if any(k.lower() in (p.title + " " + p.abstract_raw).lower() for k in keywords))
            log.keyword_kept = len(keyword_results)
        except Exception as e:
            log.log_error(f"Keyword retrieval failed: {e}")
            print(f"[WARN] keyword retrieval failed: {e}")

        if cache_path.exists():
            try:
                embedding_results = embedding_retrieve(
                    papers=papers,
                    direction=args.direction,
                    keywords=keywords,
                    cache_path=cache_path,
                    model_name=model_name,
                    dimension=dimension,
                    top_k=emb_top_k,
                    device=args.device,
                    instruction=instruction,
                )
                log.embedding_candidates = len(embedding_results)
                from search_literature_lib.embedding_filter import load_embedding_cache
                _, cached_ids, _ = load_embedding_cache(cache_path)
                log.embedding_cache_size = len(cached_ids)
            except Exception as e:
                log.log_error(f"Embedding retrieval failed: {e}")
                print(f"[WARN] embedding retrieval failed: {e}")
        else:
            msg = f"Embedding cache not found at {cache_path}, skipping embedding retrieval"
            log.log_error(msg)
            print(f"[WARN] {msg}")

    if not keyword_results and not embedding_results:
        print("[ERROR] both retrieval paths failed, cannot proceed", file=sys.stderr)
        log.write(log_path)
        return 1

    # --- Stage 2: Dedup & merge ---
    print(f"\n{'='*60}")
    print(f"[Stage 2] Dedup & merge")
    print(f"{'='*60}")

    max_cand = args.max_candidates or retrieval_config.get("max_candidates", 100)
    with log.start_stage("merge"):
        candidates = merge_candidates(
            keyword_results=keyword_results,
            embedding_results=embedding_results,
            max_candidates=max_cand,
            log=log,
        )

    # --- Stage 3: Meta enrichment ---
    print(f"\n{'='*60}")
    print(f"[Stage 3] Meta enrichment")
    print(f"{'='*60}")

    meta_config = config.get("meta_enrich", {})
    with log.start_stage("meta_enrich"):
        candidates = enrich_candidates(
            candidates,
            log=log,
            arxiv_delay=meta_config.get("arxiv_delay", 0.5),
            s2_delay=meta_config.get("s2_delay", 0.3),
        )

    abs_count = sum(1 for p in candidates if p.has_abstract)
    pdf_count = sum(1 for p in candidates if p.has_pdf_link)
    abs_pct = abs_count / len(candidates) * 100 if candidates else 0
    pdf_pct = pdf_count / len(candidates) * 100 if candidates else 0
    print(f"[meta-enrich] coverage: abstract {abs_count}/{len(candidates)} ({abs_pct:.0f}%), "
          f"PDF {pdf_count}/{len(candidates)} ({pdf_pct:.0f}%)")
    if abs_pct < 80:
        print(f"[WARN] abstract coverage below 80% — subagent scoring quality may be degraded")

    # --- Stage 3.5: Openness deepcheck (Level A passthrough + B HF lookup + C prompts) ---
    dc_config = config.get("openness_deepcheck", {}) or {}
    if dc_config.get("enabled", False):
        print(f"\n{'='*60}")
        print(f"[Stage 3.5] Openness deepcheck")
        print(f"{'='*60}")

        from search_literature_lib.openness_deepcheck import enrich_openness_deep
        import csv as _csv

        _csv.field_size_limit(10 * 1024 * 1024)
        rows_by_id: dict[str, dict] = {}
        with accepted_path.open("r", encoding="utf-8", newline="") as f:
            for _row in _csv.DictReader(f):
                pid = _row.get("paper_id", "")
                if pid:
                    rows_by_id[pid] = _row

        with log.start_stage("openness_deepcheck"):
            deep_results = enrich_openness_deep(
                candidates,
                accepted_index_rows_by_id=rows_by_id,
                enable_hf=dc_config.get("enable_hf_hub", True),
                hf_rate_limit_delay=dc_config.get("hf_rate_limit_delay", 0.3),
                verbose=True,
            )

        for pid, entry in deep_results.items():
            for cand in candidates:
                if cand.paper_id == pid:
                    cand.hf_models = ";".join(entry.get("hf_models", []) or [])
                    cand.hf_datasets = ";".join(entry.get("hf_datasets", []) or [])
                    break

        if dc_config.get("emit_repo_review_prompts", True):
            prompts_file = out_dir / "deepcheck_prompts.json"
            prompts_payload = {
                pid: {
                    "title": next((c.title for c in candidates if c.paper_id == pid), ""),
                    "code_url": next((c.code_url for c in candidates if c.paper_id == pid), ""),
                    "ai_score": next((c.ai_score for c in candidates if c.paper_id == pid), ""),
                    "prompt": entry.get("repo_review_prompt"),
                }
                for pid, entry in deep_results.items()
                if entry.get("repo_review_prompt")
            }
            prompts_file.write_text(
                json.dumps(prompts_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[deepcheck] wrote {len(prompts_payload)} repo-review prompts to {prompts_file.name}")

        with_code = sum(1 for c in candidates if c.code_url)
        with_real = sum(1 for c in candidates if c.code_is_real == "yes")
        with_weights = sum(1 for c in candidates if c.has_pretrained_weights == "yes")
        hf_model_hits = sum(1 for c in candidates if c.hf_models)
        print(
            f"[deepcheck] candidates with code_url={with_code}, confirmed real={with_real}, "
            f"weights={with_weights}, HF-model-hits={hf_model_hits}"
        )

    # --- Stage 4: Generate unscored document + CSV ---
    print(f"\n{'='*60}")
    print(f"[Stage 4] Generate unscored literature document")
    print(f"{'='*60}")

    generate_unscored(candidates, args.direction, lit_doc_path)
    write_research_index(index_path, candidates)
    print(f"[search] wrote research index: {index_path} ({len(candidates)} papers)")

    log.write(log_path)
    log_json_path = out_dir / "filter_log_state.json"
    log.save_json(log_json_path)

    print(f"\n{'='*60}")
    print(f"[search] Stages 1-4 complete. Output directory: {out_dir}")
    print(f"  Literature doc (unscored): {lit_doc_path}")
    print(f"  Research index CSV: {index_path}")
    print(f"  Filter log: {log_path}")
    print(f"  Filter log state: {log_json_path}")
    print(f"{'='*60}")
    print()
    print("[search] Stages 5-7 (subagent scoring, review, final sort) require")
    print("         the agent environment. The agent should:")
    print("         1. Load filter_log_state.json to restore pipeline state")
    print("         2. Read the research index CSV")
    print("         3. For each paper, dispatch a subagent with the scoring prompt")
    print("            (use build_scoring_prompt() from subagent_scorer)")
    print("         4. Review each score and apply adjustments")
    print("         5. Call the finalize step to generate the scored document")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
