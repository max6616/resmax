from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from resmax_core.corpus_api import fetch_paper, load_corpus, search_papers
from resmax_core.state import SCHEMA_VERSION, utc_now

from .cluster_subdirections import build_roi_rows, build_subdirection_map
from .plan_queries import load_query_families
from .query_embedding import QueryEmbeddingProvider
from .render_macro import write_macro_outputs


def retrieve_macro(
    *,
    spec_path: Path,
    accepted_csv: Path,
    out_dir: Path,
    source_policy_path: Path | None = None,
    query_families_path: Path | None = None,
    reviews_dir: Path | None = None,
    embedding_cache: Path | None = None,
    embedding_provider: str = "none",
    require_embedding: bool = False,
    per_query_k: int = 50,
    max_candidates: int | None = None,
) -> dict[str, Any]:
    started = time.time()
    print(f"[survey-v2] retrieve start spec={spec_path} accepted={accepted_csv}", flush=True)
    research_spec = _load_json(spec_path)
    source_policy_path = source_policy_path or spec_path.parent / "source_policy.json"
    query_families_path = query_families_path or spec_path.parent / "query_families.jsonl"
    source_policy = _load_json(source_policy_path)
    query_families = load_query_families(query_families_path)
    effective_max_candidates = _effective_max_candidates(research_spec, max_candidates)

    macro_dir = out_dir / "survey_v2" / "macro"
    macro_dir.mkdir(parents=True, exist_ok=True)
    trace_path = macro_dir / "retrieval_trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()
    query_embedding_trace_path = macro_dir / "query_embedding_trace.jsonl"
    if query_embedding_trace_path.exists():
        query_embedding_trace_path.unlink()

    print("[survey-v2] loading corpus and embedding cache metadata", flush=True)
    handle = load_corpus(accepted_csv, reviews_dir=reviews_dir, embedding_cache=embedding_cache, trace_path=trace_path)
    embedding_dimension = int(handle.embedding_cache_meta.get("dimension") or 0)
    print(
        "[survey-v2] loaded corpus "
        f"papers={len(handle.papers)} embedding_dim={embedding_dimension} "
        f"embedding_cache_exists={handle.embedding_cache_meta.get('exists')}",
        flush=True,
    )
    query_embedder = QueryEmbeddingProvider(embedding_provider, dimension=embedding_dimension)
    semantic_query_count = sum(
        1
        for family in query_families
        if _retrieval_mode(family) in {"embedding", "hybrid"}
        for _query in family["queries"]
    )
    if semantic_query_count:
        print(
            "[survey-v2] encoding query embeddings "
            f"provider={embedding_provider} queries={semantic_query_count} require={require_embedding}",
            flush=True,
        )
    query_embeddings = _encode_semantic_queries(query_families, query_embedder)
    if semantic_query_count:
        ok_count = sum(1 for result in query_embeddings.values() if result.ok)
        failed_count = semantic_query_count - ok_count
        elapsed = max((result.elapsed_sec for result in query_embeddings.values()), default=0.0)
        print(
            "[survey-v2] encoded query embeddings "
            f"ok={ok_count}/{semantic_query_count} failed={failed_count} elapsed_sec={elapsed:.1f}",
            flush=True,
        )
    aggregate: dict[str, dict[str, Any]] = {}
    trace_ids: list[str] = []
    query_embedding_records: list[dict[str, Any]] = []
    query_count = 0
    total_queries = sum(len(family["queries"]) for family in query_families)
    for family in query_families:
        mode = _retrieval_mode(family)
        for query in family["queries"]:
            query_count += 1
            semantic_text = _semantic_text(query)
            keyword_query = _keyword_query(query)
            query_payload = {
                "query_id": query["query_id"],
                "query_type": query.get("query_type", ""),
                "semantic_text": semantic_text,
                "keyword_query": keyword_query,
                "generation_reason": query.get("generation_reason") or query.get("intent", ""),
            }
            print(
                "[survey-v2] retrieve query "
                f"{query_count}/{total_queries} id={query['query_id']} role={family['family_role']} mode={mode}",
                flush=True,
            )
            filters = dict(family.get("filters", {}))
            if mode in {"embedding", "hybrid"}:
                embedding = query_embeddings.get(query["query_id"]) or query_embedder.encode(semantic_text)
                record = {
                    "query_id": query["query_id"],
                    "semantic_text": semantic_text,
                    "retrieval_mode": mode,
                    "provider": embedding.provider,
                    "ok": embedding.ok,
                    "dimension": embedding.dimension,
                    "elapsed_sec": round(embedding.elapsed_sec, 3),
                    "error": embedding.error,
                }
                query_embedding_records.append(record)
                if embedding.ok:
                    filters["_query_vector"] = embedding.vector
                elif require_embedding:
                    _write_jsonl(query_embedding_trace_path, query_embedding_records)
                    raise RuntimeError(f"query embedding failed for {query['query_id']}: {embedding.error}")
            hits = search_papers(
                handle,
                semantic_text,
                filters=filters,
                top_k=per_query_k,
                mode=mode,
                keyword_query=keyword_query,
                query_payload=query_payload,
                research_spec_id=research_spec["state_id"],
                query_id=query["query_id"],
            )
            hit_count = len(list(hits))
            print(
                "[survey-v2] retrieve result "
                f"{query_count}/{total_queries} id={query['query_id']} hits={hit_count} "
                f"trace_id={hits.trace.trace_id}",
                flush=True,
            )
            trace_ids.append(hits.trace.trace_id)
            for hit in hits:
                paper = fetch_paper(handle, hit.paper_id)
                row = aggregate.setdefault(hit.paper_id, _candidate_from_paper(paper))
                row["query_roles_set"].add(family["family_role"])
                row["query_ids_set"].add(query["query_id"])
                row["match_count"] += 1
                row["best_keyword_score"] = max(float(row["best_keyword_score"]), float(hit.keyword_hits or hit.score))
                if hit.embedding_score:
                    row["best_embedding_score"] = max(float(row.get("best_embedding_score", 0.0)), float(hit.embedding_score))

    _write_jsonl(query_embedding_trace_path, query_embedding_records)
    if require_embedding and query_embedding_records and any(not row["ok"] for row in query_embedding_records):
        failed = [row for row in query_embedding_records if not row["ok"]]
        raise RuntimeError(f"query embedding failed for {len(failed)} queries")
    candidates = [_finalize_candidate(row, research_spec) for row in aggregate.values()]
    candidates.sort(
        key=lambda row: (
            -float(row["candidate_grade_score"]),
            -int(row["match_count"]),
            -float(row["best_embedding_score"]),
            -float(row["best_keyword_score"]),
            row["title"],
            row["paper_id"],
        )
    )
    candidates = candidates[:effective_max_candidates]
    print(
        "[survey-v2] aggregating candidates "
        f"unique={len(aggregate)} kept={len(candidates)} max_candidates={effective_max_candidates}",
        flush=True,
    )
    subdirection_map = build_subdirection_map(candidates)
    roi_rows = build_roi_rows(subdirection_map)
    print(
        "[survey-v2] clustered subdirections "
        f"count={len(subdirection_map.get('subdirections', []))} elapsed_sec={time.time() - started:.1f}",
        flush=True,
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "research_spec_id": research_spec["state_id"],
        "source_policy_id": source_policy["state_id"],
        "accepted_index_sha256": handle.accepted_index_sha256,
        "corpus_snapshot_hash": handle.corpus_snapshot_hash,
        "paper_count": len(handle.papers),
        "query_family_count": len(query_families),
        "query_count": query_count,
        "candidate_count": len(candidates),
        "candidate_policy": {
            "macro_max_candidates": effective_max_candidates,
            "per_query_k": per_query_k,
        },
        "trace_ids": trace_ids,
        "query_embedding": {
            "provider": embedding_provider,
            "required": require_embedding,
            "embedding_cache": str(embedding_cache or ""),
            "embedding_dimension": embedding_dimension,
            "query_count": len(query_embedding_records),
            "encoded_query_count": sum(1 for row in query_embedding_records if row["ok"]),
            "failed_query_count": sum(1 for row in query_embedding_records if not row["ok"]),
            "trace": str(query_embedding_trace_path),
        },
        "artifacts": {
            "research_spec": str(spec_path),
            "source_policy": str(source_policy_path),
            "query_families": str(query_families_path),
            "broad_candidates": str(macro_dir / "broad_candidates.csv"),
            "retrieval_trace": str(trace_path),
            "query_embedding_trace": str(query_embedding_trace_path),
            "subdirection_map": str(macro_dir / "subdirection_map.json"),
            "subdirection_roi_table": str(macro_dir / "subdirection_roi_table.csv"),
            "macro_survey_report": str(macro_dir / "macro_survey_report.md"),
        },
    }
    write_macro_outputs(
        out_dir=out_dir,
        research_spec=research_spec,
        source_policy=source_policy,
        candidates=candidates,
        subdirection_map=subdirection_map,
        roi_rows=roi_rows,
        manifest=manifest,
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retrieve a Survey V2 macro candidate pack.")
    parser.add_argument("--spec", required=True, type=Path, help="Path to survey_v2/spec/research_spec.json.")
    parser.add_argument("--accepted", required=True, type=Path, help="Path to accepted_index.csv.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Output root for survey_v2 artifacts.")
    parser.add_argument("--source-policy", type=Path, default=None, help="Path to source_policy.json.")
    parser.add_argument("--query-families", type=Path, default=None, help="Path to query_families.jsonl.")
    parser.add_argument("--reviews-dir", type=Path, default=None, help="Optional reviews directory.")
    parser.add_argument("--embedding-cache", type=Path, default=None, help="Optional embedding cache.")
    parser.add_argument("--embedding-provider", choices=["none", "ssh", "hash"], default="none", help="Query embedding provider.")
    parser.add_argument("--require-embedding", action="store_true", help="Fail if hybrid/embedding queries cannot be encoded.")
    parser.add_argument("--per-query-k", type=int, default=50, help="Top-K per query family query.")
    parser.add_argument("--max-candidates", type=int, default=None, help="Maximum broad candidates after dedup.")
    args = parser.parse_args(argv)

    manifest = retrieve_macro(
        spec_path=args.spec,
        accepted_csv=args.accepted,
        out_dir=args.out_dir,
        source_policy_path=args.source_policy,
        query_families_path=args.query_families,
        reviews_dir=args.reviews_dir,
        embedding_cache=args.embedding_cache,
        embedding_provider=args.embedding_provider,
        require_embedding=args.require_embedding,
        per_query_k=args.per_query_k,
        max_candidates=args.max_candidates,
    )
    print(f"[survey-v2] wrote macro pack to {args.out_dir / 'survey_v2'}")
    print(f"[survey-v2] candidates={manifest['candidate_count']} traces={len(manifest['trace_ids'])}")
    return 0


def _candidate_from_paper(paper: Any) -> dict[str, Any]:
    source = paper.source_text
    metadata = paper.metadata
    return {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "venue": paper.venue,
        "year": str(paper.year),
        "conf_year": paper.conf_year,
        "abstract_raw": paper.abstract_raw,
        "keywords_raw": metadata.get("keywords_raw", ""),
        "paper_link": metadata.get("paper_link", ""),
        "landing_url": metadata.get("landing_url", ""),
        "pdf_url": metadata.get("pdf_url", ""),
        "doi": metadata.get("doi", ""),
        "arxiv_id": metadata.get("arxiv_id", ""),
        "openreview_forum_id": metadata.get("openreview_forum_id", ""),
        "source_tier": paper.source_tier,
        "source_weight": paper.source_weight,
        "source_text_status": source.source_text_status,
        "source_text_url": source.source_text_url,
        "source_text_source": source.source_text_source,
        "source_text_evidence": source.source_text_evidence,
        "source_text_search_query": source.source_text_search_query,
        "review_score_status": source.review_score_status,
        "query_roles_set": set(),
        "query_ids_set": set(),
        "match_count": 0,
        "best_keyword_score": 0.0,
        "best_embedding_score": 0.0,
        "has_code": "yes" if source.has_code else "no",
        "has_dataset": "yes" if source.has_dataset else "no",
        "has_pretrained_weights": "yes" if source.has_pretrained_weights else "no",
    }


def _finalize_candidate(row: dict[str, Any], research_spec: dict[str, Any]) -> dict[str, Any]:
    positive, difficulty, unknowns, evidence_status = _rough_roi_fields(row)
    clean = dict(row)
    clean["query_roles"] = "|".join(sorted(clean.pop("query_roles_set")))
    clean["query_ids"] = "|".join(sorted(clean.pop("query_ids_set")))
    clean["best_keyword_score"] = f"{float(clean['best_keyword_score']):.4f}"
    clean["best_embedding_score"] = f"{float(clean.get('best_embedding_score', 0.0)):.6f}"
    grade = _candidate_grade(clean, research_spec)
    clean["candidate_grade"] = grade["grade"]
    clean["candidate_grade_score"] = f"{grade['score']:.4f}"
    clean["candidate_grade_reasons"] = "|".join(grade["reasons"])
    clean["rough_positive_signal"] = "|".join(positive) or "unknown"
    clean["rough_difficulty_signal"] = "|".join(difficulty) or "unknown"
    clean["rough_roi_confidence"] = "low"
    clean["rough_roi_evidence_status"] = evidence_status
    clean["roi_unknowns"] = "|".join(unknowns)
    clean["subdirection_id"] = ""
    return clean


def _candidate_grade(row: dict[str, Any], research_spec: dict[str, Any]) -> dict[str, Any]:
    text = f"{row.get('title', '')} {row.get('abstract_raw', '')} {row.get('keywords_raw', '')}".lower()
    role_count = len([part for part in str(row.get("query_roles", "")).split("|") if part])
    anchor_terms = _anchor_terms(research_spec)
    anchor_hits = sum(1 for term in anchor_terms if term in text)
    target_terms = ("4dgs", "4d", "gaussian", "splatting", "editing", "edit", "action", "temporal", "real-time", "feed-forward")
    target_hits = sum(1 for term in target_terms if term in text)
    source_weight_bonus = {
        "primary": 0.8,
        "secondary": 0.4,
        "weak": 0.2,
    }.get(str(row.get("source_weight", "")).lower(), 0.0)
    source_status = row.get("source_text_status")
    full_text_bonus = 1.5 if source_status in {"pdf_available", "preprint_available"} else 0.0
    anchor_bonus = 0.7 if row.get("pdf_url") or row.get("arxiv_id") or row.get("openreview_forum_id") or row.get("doi") else 0.0
    missing_source_penalty = -1.2 if source_status in {"", "missing_anchor_needs_search", "unresolved_after_search", "not_yet_public"} else 0.0
    reuse_bonus = 0.3 if row.get("has_code") == "yes" or row.get("has_dataset") == "yes" or row.get("has_pretrained_weights") == "yes" else 0.0
    recency_bonus = 0.3 if _to_int(row.get("year", "0")) >= 2024 else 0.0
    embedding_score = max(0.0, float(row.get("best_embedding_score") or 0.0))
    keyword_score = max(0.0, min(float(row.get("best_keyword_score") or 0.0), 6.0))
    match_count = max(0, _to_int(row.get("match_count", "0")))
    score = (
        min(role_count, 7) * 0.35
        + min(match_count, 7) * 0.18
        + min(keyword_score, 6.0) * 0.12
        + min(embedding_score, 1.0) * 2.0
        + min(anchor_hits, 8) * 0.22
        + min(target_hits, 8) * 0.25
        + source_weight_bonus
        + full_text_bonus
        + anchor_bonus
        + missing_source_penalty
        + reuse_bonus
        + recency_bonus
    )
    reasons: list[str] = []
    if role_count >= 4:
        reasons.append("multi_role_retrieval")
    if embedding_score > 0.55:
        reasons.append("semantic_match")
    if target_hits >= 3:
        reasons.append("target_terms")
    if full_text_bonus:
        reasons.append("source_available")
    if anchor_bonus:
        reasons.append("source_anchor")
    if reuse_bonus:
        reasons.append("implementation_signal")
    if not reasons:
        reasons.append("low_signal")
    if score >= 6.2:
        grade = "S"
    elif score >= 4.6:
        grade = "A"
    elif score >= 3.0:
        grade = "B"
    else:
        grade = "C"
    return {"grade": grade, "score": score, "reasons": reasons}


def _anchor_terms(research_spec: dict[str, Any]) -> list[str]:
    raw = f"{research_spec.get('problem_anchor', '')} {research_spec.get('raw_intent', '')}".lower()
    terms = []
    for token in raw.replace("-", " ").replace("/", " ").split():
        clean = "".join(ch for ch in token if ch.isalnum())
        if len(clean) >= 3 and clean not in {"the", "and", "for", "with", "that", "this", "from", "into", "venue", "target", "weeks"}:
            terms.append(clean)
    return _dedupe(terms)


def _rough_roi_fields(row: dict[str, Any]) -> tuple[list[str], list[str], list[str], str]:
    text = f"{row.get('title', '')} {row.get('abstract_raw', '')} {row.get('keywords_raw', '')}".lower()
    positive: list[str] = []
    difficulty: list[str] = []
    unknowns = ["benchmark_burden", "compute_burden", "baseline_burden", "reviewer_risk"]

    if int(row["year"] or 0) >= 2024:
        positive.append("recent_top_venue")
    if row["has_code"] == "yes" or row["has_dataset"] == "yes" or row["has_pretrained_weights"] == "yes":
        positive.append("implementation_reuse")
    if any(term in text for term in ("benchmark", "evaluation", "dataset")):
        positive.append("benchmark_mentions")
        unknowns = [item for item in unknowns if item != "benchmark_burden"]

    if row["has_code"] == "no":
        difficulty.append("implementation_reference_unknown")
    difficulty.extend(["compute_burden_unknown", "baseline_burden_unknown"])
    if row["source_weight"] in {"unknown", "weak"}:
        difficulty.append("source_evidence_weak")
        evidence_status = "unknown"
    else:
        evidence_status = "weak"
    return _dedupe(positive), _dedupe(difficulty), _dedupe(unknowns), evidence_status


def _retrieval_mode(family: dict[str, Any]) -> str:
    mode = family.get("retrieval_mode") or "keyword"
    if mode in {"keyword", "embedding", "hybrid"}:
        return mode
    return "keyword"


def _encode_semantic_queries(query_families: list[dict[str, Any]], query_embedder: QueryEmbeddingProvider) -> dict[str, Any]:
    items: list[tuple[str, str]] = []
    for family in query_families:
        if _retrieval_mode(family) not in {"embedding", "hybrid"}:
            continue
        for query in family.get("queries", []):
            items.append((query["query_id"], _semantic_text(query)))
    results = query_embedder.encode_many([text for _, text in items])
    return {query_id: result for (query_id, _), result in zip(items, results)}


def _semantic_text(query: dict[str, Any]) -> str:
    semantic_text = str(query.get("semantic_text") or query.get("text") or "").strip()
    if not semantic_text:
        raise ValueError(f"query {query.get('query_id', '<unknown>')} has no semantic_text/text")
    return semantic_text


def _keyword_query(query: dict[str, Any]) -> dict[str, Any]:
    keyword_query = query.get("keyword_query")
    if isinstance(keyword_query, dict):
        return keyword_query
    text = str(query.get("text") or query.get("semantic_text") or "").strip()
    if not text:
        raise ValueError(f"query {query.get('query_id', '<unknown>')} has no keyword_query/text")
    return {"optional_terms": text.split()}


def _effective_max_candidates(research_spec: dict[str, Any], max_candidates: int | None) -> int:
    if max_candidates is not None:
        return max(1, int(max_candidates))
    spec_limit = _to_int(str(research_spec.get("budget_policy", {}).get("macro_max_candidates", "")))
    return max(400, spec_limit, 1)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_int(value: str) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
