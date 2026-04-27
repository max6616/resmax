from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / ".agents" / "skills" / "_shared"
SCHEMA = SHARED / "resmax_core" / "schemas" / "retrieval_trace.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "corpus_api" / "accepted_index.csv"
REVIEWS = ROOT / "tests" / "fixtures" / "corpus_api" / "reviews"
sys.path.insert(0, str(SHARED))

from resmax_core.corpus_api import (  # noqa: E402
    fetch_paper,
    fetch_review,
    fetch_source_text,
    load_corpus,
    search_papers,
)
from resmax_core.validators.common import load_json, validate_with_schema  # noqa: E402


def test_corpus_api_reads_fixture_and_fetches_records(tmp_path: Path) -> None:
    trace_path = tmp_path / "retrieval_trace.jsonl"
    handle = load_corpus(FIXTURE, reviews_dir=REVIEWS, trace_path=trace_path)

    paper = fetch_paper(handle, "p-graph-diffusion")
    assert paper.title == "Graph Diffusion Planning"
    assert paper.source_weight == "primary"

    source = fetch_source_text(handle, "p-graph-diffusion")
    assert source.source_text_status == "pdf_available"
    assert source.has_dataset is True

    review = fetch_review(handle, "p-graph-diffusion")
    assert review is not None
    assert review.review_score_status == "complete"
    assert review.data["forum_id"] == "forum-graph"

    hits = search_papers(handle, "scene graph", top_k=2, mode="keyword")
    assert [hit.paper_id for hit in hits] == ["p-scene-graph", "p-graph-diffusion"]
    assert hits.trace.returned_paper_ids == ["p-scene-graph", "p-graph-diffusion"]
    assert trace_path.exists()


def test_corpus_api_does_not_write_corpus_files(tmp_path: Path) -> None:
    before_csv = FIXTURE.read_bytes()
    review_path = REVIEWS / "ICLR_2024" / "forum-graph.json"
    before_review = review_path.read_bytes()

    handle = load_corpus(FIXTURE, reviews_dir=REVIEWS, trace_path=tmp_path / "trace.jsonl")
    search_papers(handle, "graph", top_k=2, mode="keyword")
    fetch_review(handle, "p-graph-diffusion")
    fetch_source_text(handle, "p-scene-graph")

    assert FIXTURE.read_bytes() == before_csv
    assert review_path.read_bytes() == before_review


def test_retrieval_trace_matches_schema(tmp_path: Path) -> None:
    trace_path = tmp_path / "retrieval_trace.jsonl"
    handle = load_corpus(FIXTURE, reviews_dir=REVIEWS, trace_path=trace_path)
    hits = search_papers(handle, "scene graph", top_k=2, mode="keyword")

    schema = load_json(SCHEMA)
    trace = hits.trace.to_dict()
    errors = validate_with_schema(trace, schema)
    assert not errors, [error.format() for error in errors]

    rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    errors = validate_with_schema(rows[0], schema)
    assert not errors, [error.format() for error in errors]
    assert rows[0]["accepted_index_sha256"].startswith("sha256:")
    assert rows[0]["returned_paper_ids"] == ["p-scene-graph", "p-graph-diffusion"]


def test_structured_keyword_query_requires_concept_groups_and_traces_hits(tmp_path: Path) -> None:
    trace_path = tmp_path / "retrieval_trace.jsonl"
    handle = load_corpus(FIXTURE, reviews_dir=REVIEWS, trace_path=trace_path)

    hits = search_papers(
        handle,
        "graph benchmark retrieval",
        top_k=3,
        mode="keyword",
        keyword_query={
            "required_concepts": [["graph", "scene graph"], ["benchmark", "evaluation", "dataset"]],
            "boost_phrases": ["scene graph", "graph diffusion"],
            "optional_terms": ["planning", "control"],
        },
        query_payload={
            "semantic_text": "graph benchmark retrieval",
            "keyword_query": {
                "required_concepts": [["graph", "scene graph"], ["benchmark", "evaluation", "dataset"]],
                "boost_phrases": ["scene graph", "graph diffusion"],
                "optional_terms": ["planning", "control"],
            },
        },
    )

    assert [hit.paper_id for hit in hits] == ["p-graph-diffusion"]
    assert hits[0].keyword_trace["required_concepts"]
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["query_payload"]["keyword_query"]["required_concepts"]
    assert trace["results"][0]["keyword_trace"]["boost_phrases"]


def test_embedding_cache_missing_returns_degraded_trace(tmp_path: Path) -> None:
    missing_cache = tmp_path / "missing_embedding_cache.npz"
    trace_path = tmp_path / "retrieval_trace.jsonl"
    handle = load_corpus(FIXTURE, reviews_dir=REVIEWS, embedding_cache=missing_cache, trace_path=trace_path)

    hits = search_papers(handle, "scene graph", top_k=2, mode="embedding")

    assert list(hits) == []
    assert "embedding cache not found" in hits.trace.degraded_reason
    assert hits.trace.embedding_cache_meta["exists"] is False
    row = json.loads(trace_path.read_text(encoding="utf-8"))
    assert row["mode"] == "embedding"
    assert row["result_count"] == 0
    assert "embedding cache not found" in row["degraded_reason"]
