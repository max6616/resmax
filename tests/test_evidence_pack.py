from __future__ import annotations

import json
import os
import csv
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "resmax-survey" / "scripts"
FIXTURE_MACRO = ROOT / "tests" / "fixtures" / "resmax_survey_v2" / "macro_smoke"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS)
    return env


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, env=_env(), text=True, capture_output=True, check=False)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_source_cache_default_scope() -> None:
    sys.path.insert(0, str(SCRIPTS))
    from resmax_survey_v2.phase3_pack import GLOBAL_SOURCE_CACHE, _effective_source_cache_dir

    repo_macro = ROOT / "literature_research" / "demo"
    tmp_macro = Path("/tmp/resmax-demo")

    assert _effective_source_cache_dir(repo_macro, None) == GLOBAL_SOURCE_CACHE.resolve()
    assert _effective_source_cache_dir(tmp_macro, None) == (tmp_macro / "survey_v2" / "paper_sources").resolve()


def _add_fixture_abstracts(path: Path) -> None:
    broad = path / "survey_v2" / "macro" / "broad_candidates.csv"
    with broad.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if "abstract_raw" not in fieldnames:
        insert_at = fieldnames.index("conf_year") + 1
        fieldnames.insert(insert_at, "abstract_raw")
    for row in rows:
        row["abstract_raw"] = (
            "This abstract reports benchmark evaluation dataset baseline and compute limitations "
            "for targeted evidence extraction when cached full text is unavailable."
        )
    with broad.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_build_pack_generates_cards_claims_gaps_and_missing_reports(tmp_path: Path) -> None:
    macro = tmp_path / "macro_copy"
    shutil.copytree(FIXTURE_MACRO, macro)
    shutil.rmtree(macro / "survey_v2" / "paper_sources" / "p-language-agent", ignore_errors=True)
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "build-pack",
            "--macro-dir",
            str(macro),
            "--out-dir",
            str(tmp_path),
            "--disable-oa-api",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    pack = tmp_path / "research_pack"
    selected = json.loads((pack / "selected_subdirection.json").read_text(encoding="utf-8"))
    assert selected["selected_subdirection_id"] == "sdir_graph_reasoning"
    assert selected["auto_selected"] is True

    spans = _jsonl(pack / "evidence_spans.jsonl")
    cards = _jsonl(pack / "evidence_cards.jsonl")
    span_ids = {span["state_id"] for span in spans}
    assert spans
    assert cards
    assert all(card["evidence_span_ids"] for card in cards)
    assert all(span_id in span_ids for card in cards for span_id in card["evidence_span_ids"])
    assert all(span["source_type"] in {"arxiv_tex", "official_pdf_text"} for span in spans)
    assert all(span["quote_hash"].startswith("sha256:") for span in spans)
    assert all(card["scope"] == "sdir_graph_reasoning" for card in cards)
    assert {card["relation"] for card in cards} >= {"supports", "motivates"}

    claim_graph = json.loads((pack / "claim_graph.json").read_text(encoding="utf-8"))
    gap_map = json.loads((pack / "gap_map.json").read_text(encoding="utf-8"))
    assert claim_graph["claims"]
    assert all(claim["scope"] == "sdir_graph_reasoning" for claim in claim_graph["claims"])
    assert gap_map["gaps"]
    assert {gap["gap_type"] for gap in gap_map["gaps"]}

    missing_source = json.loads((pack / "missing_source_report.json").read_text(encoding="utf-8"))
    missing_pdf = json.loads((pack / "missing_pdf_report.json").read_text(encoding="utf-8"))
    assert {row["paper_id"] for row in missing_source["records"]} == {"p-language-agent"}
    assert {row["paper_id"] for row in missing_pdf["records"]} >= {"p-language-agent"}

    materialization = json.loads((pack / "source_materialization_report.json").read_text(encoding="utf-8"))
    assert materialization["policy"]["targeted_selected_candidates_only"] is True
    assert materialization["policy"]["full_library_full_text_parsing"] is False
    assert materialization["policy"]["sci_hub_enabled"] is False
    assert materialization["counts"]["selected_candidate_count"] == 3
    assert materialization["counts"]["readable_source_count"] == 2
    assert materialization["counts"]["missing_readable_source_count"] == 1

    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_materialization"]["selected_candidate_count"] == 3
    assert manifest["source_materialization"]["readable_source_count"] == 2

    validate = _run([sys.executable, "-m", "resmax_survey_v2", "validate-pack", "--pack", str(pack)])
    assert validate.returncode == 0, validate.stdout + validate.stderr


def test_select_extract_compile_commands_can_run_separately(tmp_path: Path) -> None:
    select = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "select-subdirection",
            "--macro-dir",
            str(FIXTURE_MACRO),
            "--out-dir",
            str(tmp_path),
            "--subdirection-id",
            "sdir_graph_reasoning",
        ]
    )
    assert select.returncode == 0, select.stdout + select.stderr

    extract = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "extract-evidence",
            "--macro-dir",
            str(FIXTURE_MACRO),
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert extract.returncode == 0, extract.stdout + extract.stderr

    compile_result = _run([sys.executable, "-m", "resmax_survey_v2", "compile-tension", "--out-dir", str(tmp_path)])
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    assert (tmp_path / "research_pack" / "claim_graph.json").exists()
    assert (tmp_path / "research_pack" / "gap_map.json").exists()


def test_build_pack_uses_accepted_index_abstract_when_cached_source_is_missing(tmp_path: Path) -> None:
    macro = tmp_path / "macro_copy"
    shutil.copytree(FIXTURE_MACRO, macro)
    shutil.rmtree(macro / "survey_v2" / "paper_sources")
    _add_fixture_abstracts(macro)

    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "build-pack",
            "--macro-dir",
            str(macro),
            "--out-dir",
            str(tmp_path / "out"),
            "--disable-oa-api",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    pack = tmp_path / "out" / "research_pack"
    spans = _jsonl(pack / "evidence_spans.jsonl")
    cards = _jsonl(pack / "evidence_cards.jsonl")
    assert spans
    assert cards
    assert {span["source_type"] for span in spans} == {"accepted_index"}
    assert {span["span_type"] for span in spans} == {"abstract"}
    assert all(span["source"]["kind"] == "accepted_index" for span in spans)

    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["evidence_coverage"]["abstract_fallback_count"] == 3

    missing_source = json.loads((pack / "missing_source_report.json").read_text(encoding="utf-8"))
    assert len(missing_source["records"]) == 3
    assert all(row["abstract_fallback_used"] is True for row in missing_source["records"])

    validate = _run([sys.executable, "-m", "resmax_survey_v2", "validate-pack", "--pack", str(pack)])
    assert validate.returncode == 1
    assert "zero full-text EvidenceSpans" in validate.stdout + validate.stderr
