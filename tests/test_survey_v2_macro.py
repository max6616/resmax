from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "resmax-survey" / "scripts"
SHARED = ROOT / ".agents" / "skills" / "_shared"
ACCEPTED = ROOT / "tests" / "fixtures" / "resmax_core" / "corpus" / "accepted_index_small.csv"

sys.path.insert(0, str(SHARED))

from resmax_core.validators.common import load_json, validate_with_schema  # noqa: E402


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS)
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=_env(), text=True, capture_output=True, check=False)


def _write_fixture_embedding_cache(tmp_path: Path) -> Path:
    import numpy as np

    cache_path = tmp_path / "qwen3_fixture.npz"
    np.savez_compressed(
        cache_path,
        embeddings=np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
            ],
            dtype=np.float32,
        ),
        paper_ids=np.array(["p-scene-graph", "p-graph-diffusion", "p-language-agent"], dtype=np.str_),
        meta=json.dumps({"model_name": "fixture-embedding", "dimension": 4, "count": 3}),
    )
    return cache_path


def _write_agent_query_output(out_dir: Path, raw_intent: str) -> Path:
    path = out_dir / "survey_v2" / "spec" / "query_planner_agent_output.json"
    families = []
    roles = [
        "direct_baseline",
        "method_donor",
        "benchmark_opportunity",
        "implementation_reference",
        "negative_evidence",
        "reviewer_risk",
        "survey_or_taxonomy",
    ]
    for role in roles:
        families.append(
            {
                "family_role": role,
                "information_need": f"Find {role} papers for 4DGS editing from the raw intent.",
                "retrieval_mode": "hybrid",
                "filters": {},
                "queries": [
                    {
                        "query_id": f"q_{role}_1",
                        "semantic_text": f"4DGS editing dynamic Gaussian Splatting temporal coherence {role}",
                        "keyword_query": {
                            "required_concepts": [["4DGS", "4D Gaussian Splatting", "dynamic Gaussian"], ["editing", "scene editing"]],
                            "boost_phrases": ["4D Gaussian Splatting editing", "temporal coherence"],
                            "optional_terms": ["benchmark", "public dataset", "real-time"],
                        },
                        "query_type": "semantic_and_keyword",
                        "generation_reason": f"Traceable to raw_intent: {raw_intent}",
                    },
                    {
                        "query_id": f"q_{role}_2",
                        "semantic_text": f"feed-forward Gaussian editing dynamic scene action coherence {role}",
                        "keyword_query": {
                            "required_concepts": [["feed-forward", "feedforward", "one-shot"], ["Gaussian editing", "3DGS editing", "4DGS editing"]],
                            "boost_phrases": ["feed-forward Gaussian editing", "action coherence"],
                            "optional_terms": ["implementation", "evaluation", "visual quality"],
                        },
                        "query_type": "semantic_and_keyword",
                        "generation_reason": f"Traceable to raw_intent: {raw_intent}",
                    },
                ],
            }
        )
    payload = {"schema_version": "0.1.0", "raw_intent": raw_intent, "query_families": families}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _plan_queries_from_agent_output(out_dir: Path, raw_intent: str) -> None:
    agent_output = _write_agent_query_output(out_dir, raw_intent)
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "plan-queries",
            "--spec",
            str(out_dir / "survey_v2" / "spec" / "research_spec.json"),
            "--agent-output",
            str(agent_output),
            "--out",
            str(out_dir / "survey_v2" / "spec" / "query_families.jsonl"),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_compile_spec_handles_missing_target_venue_and_role_queries(tmp_path: Path) -> None:
    out_dir = tmp_path / "macro"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "compile-spec",
            "--intent",
            "4DGS editing with low compute budget",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    spec_path = out_dir / "survey_v2" / "spec" / "research_spec.json"
    policy_path = out_dir / "survey_v2" / "spec" / "source_policy.json"
    request_path = out_dir / "survey_v2" / "spec" / "query_planner_request.json"
    prompt_path = out_dir / "survey_v2" / "spec" / "query_planner_prompt.md"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert spec["target_venue"] == "unknown"
    assert "target_venue" in spec["unknowns"]
    assert spec["compute_budget"] == "unknown"
    assert spec["search_profile"]["core_topic"] == "4DGS editing"
    assert spec["budget_policy"]["macro_max_candidates"] >= 400
    assert spec["budget_policy"]["max_targeted_evidence_candidates"] >= 50
    assert policy_path.exists()
    assert request_path.exists()
    assert prompt_path.exists()
    assert not (out_dir / "survey_v2" / "spec" / "query_families.jsonl").exists()

    _plan_queries_from_agent_output(out_dir, spec["raw_intent"])

    schema = load_json(ROOT / ".agents" / "skills" / "_shared" / "resmax_core" / "schemas" / "query_family.schema.json")
    query_path = out_dir / "survey_v2" / "spec" / "query_families.jsonl"
    families = [json.loads(line) for line in query_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {family["family_role"] for family in families} >= {"direct_baseline", "reviewer_risk"}
    for family in families:
        assert family["information_need"]
        assert family["retrieval_mode"] == "hybrid"
        assert family["planner"]["raw_intent"] == spec["raw_intent"]
        assert 2 <= len(family["queries"]) <= 4
        assert family["queries"][0]["query_type"] == "semantic_and_keyword"
        assert family["queries"][0]["semantic_text"]
        assert family["queries"][0]["keyword_query"]["required_concepts"]
        assert family["queries"][0]["keyword_query"]["boost_phrases"]
        assert family["queries"][0]["generation_reason"]
        errors = validate_with_schema(family, schema)
        assert not errors, [error.format() for error in errors]


def test_4dgs_editing_siggraph_4w_query_plan_is_structured(tmp_path: Path) -> None:
    out_dir = tmp_path / "macro"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "compile-spec",
            "--intent",
            "4DGS editing for SIGGRAPH target in 4 weeks with 1 researcher and public datasets only",
            "--out-dir",
            str(out_dir),
            "--target-venue",
            "SIGGRAPH",
            "--timeline",
            "4 weeks",
            "--team-size",
            "1 researcher",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    spec = json.loads((out_dir / "survey_v2" / "spec" / "research_spec.json").read_text(encoding="utf-8"))
    assert spec["raw_intent"].startswith("4DGS editing")
    assert spec["search_profile"]["core_topic"] == "4DGS editing"
    assert "4D Gaussian Splatting" in spec["search_profile"]["entities"]
    assert any("SIGGRAPH" in item for item in spec["search_profile"]["constraints"])
    _plan_queries_from_agent_output(out_dir, spec["raw_intent"])

    families = [
        json.loads(line)
        for line in (out_dir / "survey_v2" / "spec" / "query_families.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {family["family_role"] for family in families} == {
        "direct_baseline",
        "method_donor",
        "benchmark_opportunity",
        "implementation_reference",
        "negative_evidence",
        "reviewer_risk",
        "survey_or_taxonomy",
    }
    for family in families:
        for query in family["queries"]:
            assert "4DGS editing" in query["semantic_text"] or "4D Gaussian Splatting" in " ".join(
                query["keyword_query"]["boost_phrases"]
            )
            assert query["keyword_query"]["required_concepts"]
            assert query["keyword_query"]["boost_phrases"]
            assert spec["raw_intent"] in query["generation_reason"]


def test_retrieve_macro_generates_trace_and_low_confidence_roi(tmp_path: Path) -> None:
    out_dir = tmp_path / "macro"
    cache_path = _write_fixture_embedding_cache(tmp_path)
    compile_result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "compile-spec",
            "--intent",
            "4DGS editing with low compute budget",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    _plan_queries_from_agent_output(out_dir, "4DGS editing with low compute budget")

    retrieve_result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "retrieve-macro",
            "--spec",
            str(out_dir / "survey_v2" / "spec" / "research_spec.json"),
            "--accepted",
            str(ACCEPTED),
            "--embedding-cache",
            str(cache_path),
            "--embedding-provider",
            "hash",
            "--out-dir",
            str(out_dir),
            "--max-candidates",
            "20",
        ]
    )
    assert retrieve_result.returncode == 0, retrieve_result.stdout + retrieve_result.stderr

    trace_path = out_dir / "survey_v2" / "macro" / "retrieval_trace.jsonl"
    assert trace_path.exists()
    traces = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert traces
    assert all(trace["research_spec_id"].startswith("research_spec:") for trace in traces)
    assert all(trace["query_payload"]["semantic_text"] for trace in traces)
    assert all("keyword_query" in trace["query_payload"] for trace in traces)
    assert any(trace["returned_paper_ids"] for trace in traces)

    with (out_dir / "survey_v2" / "macro" / "broad_candidates.csv").open("r", encoding="utf-8", newline="") as f:
        candidates = list(csv.DictReader(f))
    assert candidates
    assert all(row["rough_roi_confidence"] == "low" for row in candidates)
    assert {row["rough_roi_evidence_status"] for row in candidates} <= {"weak", "unknown", "insufficient_evidence"}
    assert all(row["query_roles"] for row in candidates)
    assert all(row["subdirection_id"] for row in candidates)
    assert all(row["subdirection_ids"] for row in candidates)

    with (out_dir / "survey_v2" / "macro" / "subdirection_roi_table.csv").open("r", encoding="utf-8", newline="") as f:
        roi_rows = list(csv.DictReader(f))
    assert roi_rows
    assert all(row["rough_roi_confidence"] == "low" for row in roi_rows)
    assert all(row["compute_burden"] == "unknown" for row in roi_rows)
    assert all(row["baseline_burden"] == "unknown" for row in roi_rows)

    validate_result = _run([sys.executable, "-m", "resmax_survey_v2", "validate", "--dir", str(out_dir)])
    assert validate_result.returncode == 0, validate_result.stdout + validate_result.stderr


def test_retrieve_macro_can_require_query_embeddings_with_cache(tmp_path: Path) -> None:
    out_dir = tmp_path / "macro"
    cache_path = _write_fixture_embedding_cache(tmp_path)

    compile_result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "compile-spec",
            "--intent",
            "4DGS editing with low compute budget",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    _plan_queries_from_agent_output(out_dir, "4DGS editing with low compute budget")

    retrieve_result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "retrieve-macro",
            "--spec",
            str(out_dir / "survey_v2" / "spec" / "research_spec.json"),
            "--accepted",
            str(ACCEPTED),
            "--embedding-cache",
            str(cache_path),
            "--embedding-provider",
            "hash",
            "--require-embedding",
            "--out-dir",
            str(out_dir),
            "--max-candidates",
            "20",
        ]
    )
    assert retrieve_result.returncode == 0, retrieve_result.stdout + retrieve_result.stderr

    query_embedding_trace = out_dir / "survey_v2" / "macro" / "query_embedding_trace.jsonl"
    embedding_rows = [json.loads(line) for line in query_embedding_trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert embedding_rows
    assert all(row["ok"] is True for row in embedding_rows)
    assert {row["provider"] for row in embedding_rows} == {"hash"}
    assert {row["dimension"] for row in embedding_rows} == {4}

    traces = [
        json.loads(line)
        for line in (out_dir / "survey_v2" / "macro" / "retrieval_trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert traces
    assert {trace["mode"] for trace in traces} == {"hybrid"}
    assert all(not trace["degraded_reason"] for trace in traces)

    validate_result = _run([sys.executable, "-m", "resmax_survey_v2", "validate", "--dir", str(out_dir)])
    assert validate_result.returncode == 0, validate_result.stdout + validate_result.stderr


def test_validate_fails_when_source_policy_is_missing(tmp_path: Path) -> None:
    out_dir = tmp_path / "macro"
    compile_result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "compile-spec",
            "--intent",
            "scene graph benchmark opportunity",
            "--out-dir",
            str(out_dir),
        ]
    )
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    (out_dir / "survey_v2" / "spec" / "source_policy.json").unlink()

    validate_result = _run([sys.executable, "-m", "resmax_survey_v2", "validate", "--dir", str(out_dir)])
    assert validate_result.returncode == 1
    assert "source_policy.json" in validate_result.stdout + validate_result.stderr
