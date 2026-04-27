from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from data_contracts import derive_pdf_contract, derive_source_text_contract, review_score_status

from .ids import input_hash, make_state_id
from .state import SCHEMA_VERSION, EvidenceStatus, Producer, SourceWeight, utc_now
from .trace import append_jsonl


PRODUCER = Producer(name="resmax_core.corpus_api", version=SCHEMA_VERSION)

FULL_TEXT_STATUSES = {"pdf_available", "preprint_available"}
LANDING_STATUSES = {
    "publisher_landing_only",
    "official_landing_only",
}
LISTING_STATUSES = {"source_listing_only"}
MISSING_STATUSES = {
    "",
    "missing_anchor_needs_search",
    "unresolved_after_search",
    "not_yet_public",
    "paywalled_landing",
}


@dataclass(frozen=True)
class SourceTextRecord:
    paper_id: str
    source_text_status: str
    source_text_url: str
    source_text_source: str
    source_text_evidence: str
    source_text_search_query: str
    source_text_checked_at: str
    pdf_status: str
    pdf_url: str
    pdf_source: str
    source_tier: str
    source_weight: str
    review_score_status: str
    has_code: bool
    has_dataset: bool
    has_pretrained_weights: bool


@dataclass(frozen=True)
class ReviewRecord:
    paper_id: str
    path: str
    review_available: str
    review_score_status: str
    review_score_mean: str
    review_num_reviewers: str
    data: Any


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    short_id: str
    title: str
    venue: str
    year: int
    conf_year: str
    authors: str
    abstract_raw: str
    source_text: SourceTextRecord
    source_tier: str
    source_weight: str
    metadata: Mapping[str, str]


@dataclass(frozen=True)
class PaperHit:
    paper_id: str
    rank: int
    score: float
    mode: str
    title: str
    venue: str
    year: int
    keyword_hits: int = 0
    embedding_score: float = 0.0
    source_tier: str = "unknown"
    source_weight: str = SourceWeight.UNKNOWN.value
    keyword_trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalTrace:
    schema_version: str
    state_id: str
    trace_id: str
    created_at: str
    input_hash: str
    parent_state_ids: list[str]
    producer: Producer
    research_spec_id: str
    query_id: str
    retrieval_method: str
    mode: str
    corpus_snapshot_hash: str
    accepted_index_sha256: str
    embedding_cache_meta: dict[str, Any]
    query: str
    query_payload: dict[str, Any]
    filters: dict[str, Any]
    top_k: int
    returned_paper_ids: list[str]
    degraded_reason: str
    result_count: int
    results: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SearchResults(list[PaperHit]):
    trace: RetrievalTrace

    def __init__(self, hits: Iterable[PaperHit], trace: RetrievalTrace) -> None:
        super().__init__(hits)
        self.trace = trace


@dataclass(frozen=True)
class CorpusHandle:
    accepted_csv: Path
    reviews_dir: Path | None
    embedding_cache: Path | None
    trace_path: Path | None
    accepted_index_sha256: str
    corpus_snapshot_hash: str
    embedding_cache_meta: Mapping[str, Any]
    papers: tuple[PaperRecord, ...]
    papers_by_id: Mapping[str, PaperRecord]
    rows_by_id: Mapping[str, Mapping[str, str]]


def load_corpus(
    accepted_csv: str | Path,
    reviews_dir: str | Path | None = None,
    embedding_cache: str | Path | None = None,
    *,
    trace_path: str | Path | None = None,
) -> CorpusHandle:
    accepted_path = Path(accepted_csv).resolve()
    if not accepted_path.exists():
        raise FileNotFoundError(f"accepted_index.csv not found: {accepted_path}")

    review_path = Path(reviews_dir).resolve() if reviews_dir else None
    cache_path = Path(embedding_cache).resolve() if embedding_cache else None
    trace_sink = Path(trace_path).resolve() if trace_path else None

    accepted_hash = _sha256_file(accepted_path)
    embedding_meta = _embedding_cache_meta(cache_path)

    papers: list[PaperRecord] = []
    rows_by_id: dict[str, Mapping[str, str]] = {}
    with accepted_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            paper = _paper_from_row(row)
            if not paper.paper_id:
                continue
            papers.append(paper)
            rows_by_id[paper.paper_id] = MappingProxyType(dict(row))

    papers_by_id = {paper.paper_id: paper for paper in papers}
    snapshot_hash = input_hash(
        {
            "accepted_index_sha256": accepted_hash,
            "embedding_cache_meta": dict(embedding_meta),
            "paper_count": len(papers),
        }
    )

    return CorpusHandle(
        accepted_csv=accepted_path,
        reviews_dir=review_path,
        embedding_cache=cache_path,
        trace_path=trace_sink,
        accepted_index_sha256=accepted_hash,
        corpus_snapshot_hash=snapshot_hash,
        embedding_cache_meta=MappingProxyType(dict(embedding_meta)),
        papers=tuple(papers),
        papers_by_id=MappingProxyType(papers_by_id),
        rows_by_id=MappingProxyType(rows_by_id),
    )


def search_papers(
    handle: CorpusHandle,
    query: str,
    filters: Mapping[str, Any] | None = None,
    top_k: int = 50,
    mode: str = "keyword",
    keyword_query: Mapping[str, Any] | None = None,
    query_payload: Mapping[str, Any] | None = None,
    *,
    research_spec_id: str = "ad_hoc",
    query_id: str = "",
) -> SearchResults:
    clean_mode = mode.strip().lower()
    clean_filters = _public_filters(filters or {})
    top_k = max(0, int(top_k))

    if clean_mode == "keyword":
        hits, degraded_reason = _keyword_search(handle, query, filters or {}, top_k, keyword_query=keyword_query)
    elif clean_mode == "embedding":
        hits, degraded_reason = _embedding_search(handle, query, filters or {}, top_k)
    elif clean_mode == "hybrid":
        keyword_hits, keyword_degraded = _keyword_search(handle, query, filters or {}, top_k, keyword_query=keyword_query)
        embedding_hits, embedding_degraded = _embedding_search(handle, query, filters or {}, top_k)
        hits = _merge_hits(keyword_hits, embedding_hits, top_k)
        degraded_reason = "; ".join(x for x in (keyword_degraded, embedding_degraded) if x)
    else:
        raise ValueError(f"unsupported retrieval mode: {mode!r}")

    trace = _make_retrieval_trace(
        handle=handle,
        query=query,
        query_payload=_trace_query_payload(query, keyword_query, query_payload),
        filters=clean_filters,
        mode=clean_mode,
        top_k=top_k,
        hits=hits,
        degraded_reason=degraded_reason,
        research_spec_id=research_spec_id,
        query_id=query_id,
    )
    if handle.trace_path:
        append_jsonl(handle.trace_path, trace.to_dict())
    return SearchResults(hits, trace)


def fetch_paper(handle: CorpusHandle, paper_id: str) -> PaperRecord:
    try:
        return handle.papers_by_id[paper_id]
    except KeyError as exc:
        raise KeyError(f"paper not found: {paper_id}") from exc


def fetch_review(handle: CorpusHandle, paper_id: str) -> ReviewRecord | None:
    row = handle.rows_by_id.get(paper_id)
    if row is None:
        raise KeyError(f"paper not found: {paper_id}")

    path = _find_review_path(handle, row)
    if path is None:
        return None

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return ReviewRecord(
        paper_id=paper_id,
        path=str(path),
        review_available=row.get("review_available", ""),
        review_score_status=_row_review_score_status(row),
        review_score_mean=row.get("review_score_mean", ""),
        review_num_reviewers=row.get("review_num_reviewers", ""),
        data=data,
    )


def fetch_source_text(handle: CorpusHandle, paper_id: str) -> SourceTextRecord:
    return fetch_paper(handle, paper_id).source_text


def _paper_from_row(row: Mapping[str, str]) -> PaperRecord:
    source_text = _source_text_from_row(row)
    metadata = MappingProxyType(dict(row))
    return PaperRecord(
        paper_id=row.get("paper_id", ""),
        short_id=row.get("short_id", ""),
        title=row.get("title", ""),
        venue=row.get("venue", ""),
        year=_to_int(row.get("year", "")),
        conf_year=row.get("conf_year", ""),
        authors=row.get("authors", ""),
        abstract_raw=row.get("abstract_raw", ""),
        source_text=source_text,
        source_tier=source_text.source_tier,
        source_weight=source_text.source_weight,
        metadata=metadata,
    )


def _source_text_from_row(row: Mapping[str, str]) -> SourceTextRecord:
    pdf = derive_pdf_contract(row)
    source_text = derive_source_text_contract(
        {
            **row,
            "landing_url": row.get("landing_url", "") or pdf.landing_url,
            "pdf_url": row.get("pdf_url", "") or pdf.pdf_url,
            "pdf_status": row.get("pdf_status", "") or pdf.pdf_status,
            "pdf_source": row.get("pdf_source", "") or pdf.pdf_source,
        }
    )
    source_text_status = row.get("source_text_status", "") or source_text.source_text_status
    source_text_url = row.get("source_text_url", "") or source_text.source_text_url
    source_text_source = row.get("source_text_source", "") or source_text.source_text_source
    source_text_evidence = row.get("source_text_evidence", "") or source_text.source_text_evidence
    source_text_search_query = row.get("source_text_search_query", "") or source_text.source_text_search_query
    pdf_status = row.get("pdf_status", "") or pdf.pdf_status
    pdf_url = row.get("pdf_url", "") or pdf.pdf_url
    pdf_source = row.get("pdf_source", "") or pdf.pdf_source
    source_tier, source_weight = _derive_source_tier_and_weight(
        source_text_status=source_text_status,
        review_status=_row_review_score_status(row),
        pdf_status=pdf_status,
        code_url=row.get("code_url", ""),
        has_dataset=row.get("has_dataset", ""),
        has_pretrained_weights=row.get("has_pretrained_weights", ""),
    )

    return SourceTextRecord(
        paper_id=row.get("paper_id", ""),
        source_text_status=source_text_status,
        source_text_url=source_text_url,
        source_text_source=source_text_source,
        source_text_evidence=source_text_evidence,
        source_text_search_query=source_text_search_query,
        source_text_checked_at=row.get("source_text_checked_at", ""),
        pdf_status=pdf_status,
        pdf_url=pdf_url,
        pdf_source=pdf_source,
        source_tier=source_tier,
        source_weight=source_weight,
        review_score_status=_row_review_score_status(row),
        has_code=bool((row.get("code_url", "") or "").strip()),
        has_dataset=_is_yes(row.get("has_dataset", "")),
        has_pretrained_weights=_is_yes(row.get("has_pretrained_weights", "")),
    )


def _derive_source_tier_and_weight(
    *,
    source_text_status: str,
    review_status: str,
    pdf_status: str,
    code_url: str,
    has_dataset: str,
    has_pretrained_weights: str,
) -> tuple[str, str]:
    status = (source_text_status or "").strip()
    has_review = review_status in {"complete", "partial", "no_scores"}
    has_openness = bool((code_url or "").strip()) or _is_yes(has_dataset) or _is_yes(has_pretrained_weights)
    has_pdf = pdf_status == "available"

    if status in FULL_TEXT_STATUSES or has_pdf:
        return "full_text", SourceWeight.PRIMARY.value
    if status in LANDING_STATUSES:
        weight = SourceWeight.SECONDARY.value if has_review or has_openness else SourceWeight.TERTIARY.value
        return "landing_only", weight
    if status in LISTING_STATUSES:
        return "listing_only", SourceWeight.TERTIARY.value
    if status == "not_yet_public":
        return "not_public", SourceWeight.NOT_APPLICABLE.value
    if status in MISSING_STATUSES:
        if has_review or has_openness:
            return "metadata_plus_aux", SourceWeight.WEAK.value
        return "metadata_only", SourceWeight.UNKNOWN.value
    return "unknown", SourceWeight.UNKNOWN.value


def _keyword_search(
    handle: CorpusHandle,
    query: str,
    filters: Mapping[str, Any],
    top_k: int,
    *,
    keyword_query: Mapping[str, Any] | None = None,
) -> tuple[list[PaperHit], str]:
    parsed_query = _parse_keyword_query(query, keyword_query)
    if not parsed_query["required_concepts"] and not parsed_query["boost_phrases"] and not parsed_query["optional_terms"]:
        return [], "empty keyword query"

    scored: list[tuple[PaperRecord, float, int, dict[str, Any]]] = []
    for paper in handle.papers:
        if not _matches_filters(paper, filters):
            continue
        score, hit_count, trace = _score_keyword_match(paper, parsed_query)
        if score > 0:
            scored.append((paper, score, hit_count, trace))

    scored.sort(key=lambda item: (-item[1], item[0].title.lower(), item[0].paper_id))
    result: list[PaperHit] = []
    for rank, (paper, score, hits, trace) in enumerate(scored[:top_k], 1):
        result.append(
            PaperHit(
                paper_id=paper.paper_id,
                rank=rank,
                score=float(score),
                mode="keyword",
                title=paper.title,
                venue=paper.venue,
                year=paper.year,
                keyword_hits=hits,
                source_tier=paper.source_tier,
                source_weight=paper.source_weight,
                keyword_trace=trace,
            )
        )
    return result, ""


def _parse_keyword_query(query: str, keyword_query: Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(keyword_query, Mapping):
        return {
            "required_concepts": _concept_groups(keyword_query.get("required_concepts", [])),
            "boost_phrases": _string_list(keyword_query.get("boost_phrases", [])),
            "optional_terms": _string_list(keyword_query.get("optional_terms", [])),
        }
    return {
        "required_concepts": [],
        "boost_phrases": [],
        "optional_terms": _query_terms(query),
    }


def _concept_groups(value: Any) -> list[list[str]]:
    groups: list[list[str]] = []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return groups
    for group in value:
        terms = _string_list(group)
        if terms:
            groups.append(terms)
    return groups


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence):
        values = [str(item) for item in value]
    else:
        values = []
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        clean = re.sub(r"\s+", " ", item.strip().lower())
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _score_keyword_match(paper: PaperRecord, keyword_query: Mapping[str, Any]) -> tuple[float, int, dict[str, Any]]:
    fields = _search_fields(paper)
    score = 0.0
    hit_count = 0
    matched_required: list[dict[str, Any]] = []
    matched_phrases: list[dict[str, Any]] = []
    matched_terms: list[dict[str, Any]] = []

    for group in keyword_query["required_concepts"]:
        best = _best_match(group, fields, base_score=3.0)
        if best is None:
            return 0.0, 0, {}
        score += best["score"]
        hit_count += 1
        matched_required.append({"group": group, **best})

    for phrase in keyword_query["boost_phrases"]:
        match = _best_match([phrase], fields, base_score=2.0, phrase_only=True)
        if match is not None:
            score += match["score"]
            hit_count += 1
            matched_phrases.append(match)

    for term in keyword_query["optional_terms"]:
        match = _best_match([term], fields, base_score=0.5)
        if match is not None:
            score += match["score"]
            hit_count += 1
            matched_terms.append(match)

    if score <= 0:
        return 0.0, 0, {}
    return (
        round(score, 4),
        hit_count,
        {
            "score": round(score, 4),
            "required_concepts": matched_required,
            "boost_phrases": matched_phrases,
            "optional_terms": matched_terms,
        },
    )


def _best_match(
    terms: Sequence[str],
    fields: Mapping[str, str],
    *,
    base_score: float,
    phrase_only: bool = False,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for term in terms:
        clean = re.sub(r"\s+", " ", str(term).strip().lower())
        if not clean:
            continue
        for field_name, field_text in fields.items():
            if not _matches_term(clean, field_text, phrase_only=phrase_only):
                continue
            weighted = base_score * _field_multiplier(field_name)
            if best is None or weighted > float(best["score"]):
                best = {
                    "term": clean,
                    "field": field_name,
                    "score": round(weighted, 4),
                }
    return best


def _matches_term(term: str, field_text: str, *, phrase_only: bool) -> bool:
    if not term or not field_text:
        return False
    if " " in term or phrase_only:
        return term in field_text
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", field_text) is not None


def _search_fields(paper: PaperRecord) -> dict[str, str]:
    return {
        "title": _normalize_text(paper.title),
        "keywords": _normalize_text(" ".join([paper.metadata.get("keywords_raw", ""), paper.metadata.get("topic", "")])),
        "abstract": _normalize_text(paper.abstract_raw),
    }


def _field_multiplier(field_name: str) -> float:
    if field_name == "title":
        return 2.0
    if field_name == "keywords":
        return 1.5
    return 1.0


def _normalize_text(value: str) -> str:
    clean = re.sub(r"[^a-z0-9+._-]+", " ", (value or "").lower())
    return re.sub(r"\s+", " ", clean).strip()


def _embedding_search(
    handle: CorpusHandle,
    query: str,
    filters: Mapping[str, Any],
    top_k: int,
) -> tuple[list[PaperHit], str]:
    cache_path = handle.embedding_cache
    if cache_path is None:
        return [], "embedding cache path not configured"
    if not cache_path.exists():
        return [], f"embedding cache not found: {cache_path}"

    query_vector = filters.get("_query_vector") or filters.get("query_vector")
    if query_vector is None:
        return [], "embedding query vector not supplied"

    try:
        import numpy as np
    except ImportError:
        return [], "numpy is required for embedding retrieval"

    data = np.load(cache_path, allow_pickle=False)
    embeddings = data["embeddings"]
    paper_ids = [str(x) for x in data["paper_ids"].tolist()]
    qvec = np.array(query_vector, dtype="float32")
    if qvec.ndim != 1:
        return [], "embedding query vector must be a one-dimensional array"
    if embeddings.ndim != 2 or embeddings.shape[0] != len(paper_ids):
        return [], "embedding cache has invalid embeddings/paper_ids shape"

    target_dim = min(int(qvec.shape[0]), int(embeddings.shape[1]))
    if target_dim <= 0:
        return [], "embedding query vector or cache has zero dimension"
    qvec = qvec[:target_dim]
    embeddings = embeddings[:, :target_dim]
    qnorm = np.linalg.norm(qvec)
    if qnorm:
        qvec = qvec / qnorm
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embeddings = embeddings / norms
    scores = embeddings @ qvec

    candidates: list[tuple[PaperRecord, float]] = []
    for idx, paper_id in enumerate(paper_ids):
        paper = handle.papers_by_id.get(paper_id)
        if paper and _matches_filters(paper, filters):
            candidates.append((paper, float(scores[idx])))
    candidates.sort(key=lambda item: (-item[1], item[0].title.lower(), item[0].paper_id))

    hits: list[PaperHit] = []
    for rank, (paper, score) in enumerate(candidates[:top_k], 1):
        hits.append(
            PaperHit(
                paper_id=paper.paper_id,
                rank=rank,
                score=score,
                mode="embedding",
                title=paper.title,
                venue=paper.venue,
                year=paper.year,
                embedding_score=score,
                source_tier=paper.source_tier,
                source_weight=paper.source_weight,
            )
        )
    return hits, ""


def _merge_hits(keyword_hits: Sequence[PaperHit], embedding_hits: Sequence[PaperHit], top_k: int) -> list[PaperHit]:
    by_id: dict[str, dict[str, Any]] = {}
    keyword_ids = {hit.paper_id for hit in keyword_hits}
    embedding_ids = {hit.paper_id for hit in embedding_hits}
    for hit in keyword_hits:
        row = by_id.setdefault(
            hit.paper_id,
            {"hit": hit, "rrf": 0.0, "keyword_hits": 0, "embedding_score": 0.0, "keyword_trace": {}},
        )
        row["rrf"] += 1.0 / (60.0 + hit.rank)
        row["keyword_hits"] = max(int(row["keyword_hits"]), int(hit.keyword_hits or hit.score))
        row["keyword_trace"] = hit.keyword_trace or row["keyword_trace"]
    for hit in embedding_hits:
        row = by_id.setdefault(
            hit.paper_id,
            {"hit": hit, "rrf": 0.0, "keyword_hits": 0, "embedding_score": 0.0, "keyword_trace": {}},
        )
        row["rrf"] += 1.0 / (60.0 + hit.rank)
        row["embedding_score"] = max(float(row["embedding_score"]), float(hit.embedding_score or hit.score))
    merged = list(by_id.items())
    merged.sort(key=lambda item: (-float(item[1]["rrf"]), item[1]["hit"].title.lower(), item[0]))
    return [
        PaperHit(
            paper_id=paper_id,
            rank=rank,
            score=float(row["rrf"]),
            mode="hybrid" if paper_id in keyword_ids and paper_id in embedding_ids else ("keyword" if paper_id in keyword_ids else "embedding"),
            title=row["hit"].title,
            venue=row["hit"].venue,
            year=row["hit"].year,
            keyword_hits=int(row["keyword_hits"]),
            embedding_score=float(row["embedding_score"]),
            source_tier=row["hit"].source_tier,
            source_weight=row["hit"].source_weight,
            keyword_trace=dict(row.get("keyword_trace") or {}),
        )
        for rank, (paper_id, row) in enumerate(merged[:top_k], 1)
    ]


def _make_retrieval_trace(
    *,
    handle: CorpusHandle,
    query: str,
    query_payload: Mapping[str, Any],
    filters: Mapping[str, Any],
    mode: str,
    top_k: int,
    hits: Sequence[PaperHit],
    degraded_reason: str,
    research_spec_id: str,
    query_id: str,
) -> RetrievalTrace:
    returned_ids = [hit.paper_id for hit in hits]
    results = []
    for hit in hits:
        result = {
            "paper_id": hit.paper_id,
            "rank": hit.rank,
            "score": float(hit.score),
            "evidence_status": _evidence_status(fetch_paper(handle, hit.paper_id)),
        }
        if hit.keyword_trace:
            result["keyword_trace"] = hit.keyword_trace
        results.append(result)
    trace_input = {
        "accepted_index_sha256": handle.accepted_index_sha256,
        "embedding_cache_meta": dict(handle.embedding_cache_meta),
        "query": query,
        "query_payload": dict(query_payload),
        "filters": dict(filters),
        "mode": mode,
        "top_k": top_k,
        "returned_paper_ids": returned_ids,
        "degraded_reason": degraded_reason,
    }
    state_id = make_state_id("retrieval_trace", trace_input)
    clean_query_id = query_id or make_state_id("query", {"query": query, "filters": dict(filters), "mode": mode}, length=12)
    return RetrievalTrace(
        schema_version=SCHEMA_VERSION,
        state_id=state_id,
        trace_id=state_id,
        created_at=utc_now(),
        input_hash=input_hash(trace_input),
        parent_state_ids=[],
        producer=PRODUCER,
        research_spec_id=research_spec_id or "ad_hoc",
        query_id=clean_query_id,
        retrieval_method=mode if mode in {"keyword", "embedding", "hybrid"} else "metadata",
        mode=mode,
        corpus_snapshot_hash=handle.corpus_snapshot_hash,
        accepted_index_sha256=handle.accepted_index_sha256,
        embedding_cache_meta=dict(handle.embedding_cache_meta),
        query=query,
        query_payload=dict(query_payload),
        filters=dict(filters),
        top_k=top_k,
        returned_paper_ids=returned_ids,
        degraded_reason=degraded_reason,
        result_count=len(hits),
        results=results,
    )


def _evidence_status(paper: PaperRecord) -> str:
    status = paper.source_text.source_text_status
    if status in FULL_TEXT_STATUSES or status in LANDING_STATUSES or status in LISTING_STATUSES:
        return EvidenceStatus.SUPPORTED.value
    if status in MISSING_STATUSES:
        return EvidenceStatus.NOT_FOUND.value
    return EvidenceStatus.UNKNOWN.value


def _embedding_cache_meta(cache_path: Path | None) -> dict[str, Any]:
    if cache_path is None:
        return {
            "path": "",
            "exists": False,
            "paper_count": 0,
            "dimension": 0,
            "model_name": "",
            "degraded_reason": "embedding cache path not configured",
        }
    if not cache_path.exists():
        return {
            "path": str(cache_path),
            "exists": False,
            "paper_count": 0,
            "dimension": 0,
            "model_name": "",
            "degraded_reason": f"embedding cache not found: {cache_path}",
        }

    meta: dict[str, Any] = {
        "path": str(cache_path),
        "exists": True,
        "sha256": _sha256_file(cache_path),
        "paper_count": 0,
        "dimension": 0,
        "model_name": "",
        "degraded_reason": "",
    }
    try:
        import numpy as np

        data = np.load(cache_path, allow_pickle=False)
        if "paper_ids" in data.files:
            meta["paper_count"] = int(len(data["paper_ids"]))
        if "embeddings" in data.files:
            embeddings = data["embeddings"]
            if len(embeddings.shape) == 2:
                meta["dimension"] = int(embeddings.shape[1])
        if "meta" in data.files:
            raw_meta = json.loads(str(data["meta"]))
            if isinstance(raw_meta, dict):
                meta["model_name"] = raw_meta.get("model_name", raw_meta.get("model", ""))
                meta["raw"] = raw_meta
    except Exception as exc:
        meta["exists"] = True
        meta["degraded_reason"] = f"embedding cache metadata unavailable: {exc}"
    return meta


def _find_review_path(handle: CorpusHandle, row: Mapping[str, str]) -> Path | None:
    candidates: list[Path] = []
    detail = (row.get("review_detail_path", "") or "").strip()
    if detail:
        raw = Path(detail)
        candidates.extend([raw, handle.accepted_csv.parent / raw, handle.accepted_csv.parent.parent / raw])

    forum_id = (row.get("openreview_forum_id", "") or "").strip()
    conf_year = (row.get("conf_year", "") or "").strip()
    if handle.reviews_dir and forum_id:
        if conf_year:
            candidates.append(handle.reviews_dir / conf_year / f"{forum_id}.json")
        candidates.append(handle.reviews_dir / f"{forum_id}.json")

    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _matches_filters(paper: PaperRecord, filters: Mapping[str, Any]) -> bool:
    for key, expected in filters.items():
        if key in {"_query_vector", "query_vector"}:
            continue
        actual = _field_value(paper, key)
        if not _value_matches(actual, expected):
            return False
    return True


def _value_matches(actual: Any, expected: Any) -> bool:
    if expected is None:
        return True
    if isinstance(expected, Mapping):
        if "in" in expected:
            return _value_matches(actual, expected["in"])
        if "min" in expected and _to_float(actual) < float(expected["min"]):
            return False
        if "max" in expected and _to_float(actual) > float(expected["max"]):
            return False
        return True
    if isinstance(expected, (list, tuple, set)):
        return str(actual) in {str(item) for item in expected}
    return str(actual) == str(expected)


def _field_value(paper: PaperRecord, key: str) -> Any:
    if hasattr(paper, key):
        return getattr(paper, key)
    if hasattr(paper.source_text, key):
        return getattr(paper.source_text, key)
    return paper.metadata.get(key, "")


def _public_filters(filters: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in filters.items() if key not in {"_query_vector", "query_vector"}}


def _trace_query_payload(
    query: str,
    keyword_query: Mapping[str, Any] | None,
    query_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if isinstance(query_payload, Mapping) and query_payload:
        return dict(query_payload)
    payload: dict[str, Any] = {"semantic_text": query}
    if isinstance(keyword_query, Mapping):
        payload["keyword_query"] = {
            "required_concepts": _concept_groups(keyword_query.get("required_concepts", [])),
            "boost_phrases": _string_list(keyword_query.get("boost_phrases", [])),
            "optional_terms": _string_list(keyword_query.get("optional_terms", [])),
        }
    return payload


def _query_terms(query: str) -> list[str]:
    return [part for part in re.split(r"[\s,;]+", query.lower().strip()) if part]


def _search_text(paper: PaperRecord) -> str:
    return " ".join(
        [
            paper.title,
            paper.abstract_raw,
            paper.metadata.get("keywords_raw", ""),
            paper.metadata.get("topic", ""),
        ]
    ).lower()


def _row_review_score_status(row: Mapping[str, str]) -> str:
    return row.get("review_score_status", "") or review_score_status(row)


def _is_yes(value: str) -> bool:
    return (value or "").strip().lower() in {"yes", "true", "1", "y"}


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
