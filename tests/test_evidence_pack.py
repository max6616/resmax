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


def test_fetch_pdf_suppresses_known_mupdf_diagnostics(tmp_path: Path, monkeypatch, capsys) -> None:
    sys.path.insert(0, str(SCRIPTS))
    from search_literature_lib import paper_source_fetch

    class FakeTools:
        def __init__(self) -> None:
            self.errors = True
            self.warnings = True

        def reset_mupdf_warnings(self) -> None:
            return None

        def mupdf_display_errors(self, on=None):
            if on is None:
                return int(self.errors)
            self.errors = bool(on)
            return self.errors

        def mupdf_display_warnings(self, on=None):
            if on is None:
                return int(self.warnings)
            self.warnings = bool(on)
            return self.warnings

        def mupdf_warnings(self) -> str:
            return "\n".join(
                [
                    "bogus font ascent/descent values (3117 / -2464)",
                    "... repeated 2 times...",
                    "unsupported error: cannot create appearance stream for Screen annotations",
                    "cannot create appearance stream",
                ]
            )

    class FakePage:
        def get_text(self, mode: str) -> str:
            assert mode == "text"
            return "extracted text"

    class FakeDoc:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def __iter__(self):
            return iter([FakePage()])

    class FakePyMuPDF:
        TOOLS = FakeTools()

        @staticmethod
        def open(path: Path) -> FakeDoc:
            assert path.name == "paper.pdf"
            return FakeDoc()

    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.7\nfixture")
    monkeypatch.setattr(paper_source_fetch, "pymupdf", FakePyMuPDF)
    monkeypatch.setattr(paper_source_fetch, "HAS_PYMUPDF", True)

    result = paper_source_fetch.fetch_pdf([], tmp_path)
    captured = capsys.readouterr()

    assert captured.err == ""
    assert result["ok"] is True
    assert result["text_chars"] == len("extracted text")
    assert result["diagnostics"] == {
        "pymupdf_known_nonfatal": ["bogus_font_metrics", "screen_annotation_appearance_stream"]
    }
    assert (tmp_path / "paper.pdftxt").read_text(encoding="utf-8") == "extracted text"


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
            "--mode",
            "smoke",
            "--allow-auto-select",
            "--allow-abstract-fallback",
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


def test_build_pack_requires_subdirection_or_auto_select_approval(tmp_path: Path) -> None:
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "build-pack",
            "--macro-dir",
            str(FIXTURE_MACRO),
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert result.returncode == 1
    assert "G1 subdirection selection gate required" in result.stdout + result.stderr
    gate = json.loads((tmp_path / "research_pack" / "pending_gate_g1.json").read_text(encoding="utf-8"))
    assert gate["gate_id"] == "G1"
    assert gate["default_action_if_no_answer"] == "stop"


def test_build_pack_requires_evidence_expansion_approval_when_sources_are_missing(tmp_path: Path) -> None:
    macro = tmp_path / "macro_copy"
    shutil.copytree(FIXTURE_MACRO, macro)
    shutil.rmtree(macro / "survey_v2" / "paper_sources" / "p-language-agent", ignore_errors=True)
    out_dir = tmp_path / "out"
    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "build-pack",
            "--macro-dir",
            str(macro),
            "--out-dir",
            str(out_dir),
            "--subdirection-id",
            "sdir_graph_reasoning",
            "--disable-oa-api",
        ]
    )
    assert result.returncode == 1
    assert "G2 evidence expansion gate required" in result.stdout + result.stderr
    pack = out_dir / "research_pack"
    gate = json.loads((pack / "pending_gate_g2.json").read_text(encoding="utf-8"))
    assert gate["gate_id"] == "G2"
    assert "source_materialization_report.json" in gate["artifact_to_show_before_asking"]

    rerun = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "build-pack",
            "--macro-dir",
            str(macro),
            "--out-dir",
            str(out_dir),
            "--subdirection-id",
            "sdir_graph_reasoning",
            "--disable-oa-api",
            "--allow-abstract-fallback",
        ]
    )
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    assert not (pack / "pending_gate_g2.json").exists()

    (pack / "pending_gate_g2.json").write_text(
        json.dumps({"schema_version": "0.1.0", "gate_id": "G2"}) + "\n",
        encoding="utf-8",
    )
    validate = _run([sys.executable, "-m", "resmax_survey_v2", "validate-pack", "--pack", str(pack)])
    assert validate.returncode == 1
    assert "stale pending gate artifact exists after manifest creation" in validate.stdout + validate.stderr


def test_record_source_replenishment_writes_jsonable_idempotent_provenance(tmp_path: Path) -> None:
    pack = tmp_path / "out" / "research_pack"
    pack.mkdir(parents=True)
    cache_dir = tmp_path / "source_cache" / "ICLR_2025__fast_feedforward_3d_gaussian_splatting_compression"
    cache_dir.mkdir(parents=True)
    (cache_dir / "paper.pdftxt").write_text("Full text from a legal public paper cache.\n", encoding="utf-8")
    (cache_dir / "paper.pdf").write_bytes(b"%PDF-1.7\nfixture")

    paper_id = "ICLR_2025::fast_feedforward_3d_gaussian_splatting_compression"
    (pack / "source_materialization_report.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "created_at": "2026-04-28T04:24:33Z",
                "cache_dir": str(tmp_path / "source_cache"),
                "counts": {
                    "selected_candidate_count": 1,
                    "readable_source_count": 0,
                    "missing_readable_source_count": 1,
                },
                "records": [
                    {
                        "paper_id": paper_id,
                        "title": "Fast Feedforward 3D Gaussian Splatting Compression",
                        "paper_dir": "ICLR_2025__fast_feedforward_3d_gaussian_splatting_compression",
                    }
                ],
                "web_search_replenishment": [
                    {
                        "paper_id": paper_id,
                        "title": "Fast Feedforward 3D Gaussian Splatting Compression",
                        "cache_dir": str(cache_dir),
                        "recovered_doi": "10.48550/arxiv.2410.08017",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    args = [
        sys.executable,
        "-m",
        "resmax_survey_v2",
        "record-source-replenishment",
        "--pack",
        str(pack),
        "--paper-id",
        paper_id,
        "--source-url",
        "https://arxiv.org/abs/2410.08017",
        "--source-url",
        "https://openreview.net/forum?id=DCandSZ2F1",
        "--note",
        "legal public arXiv/OpenReview source cache",
    ]
    result = _run(args)
    assert result.returncode == 0, result.stdout + result.stderr
    rerun = _run(args)
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr

    log = json.loads((pack / "source_replenishment_log.json").read_text(encoding="utf-8"))
    assert log["record_count"] == 1
    record = log["records"][0]
    assert record["paper_id"] == paper_id
    assert record["cache_dir"] == str(cache_dir.resolve())
    assert record["source_urls"] == [
        "https://arxiv.org/abs/2410.08017",
        "https://openreview.net/forum?id=DCandSZ2F1",
    ]
    assert record["readable_source_count"] == 1
    assert record["readable_source_files"][0]["path"] == str((cache_dir / "paper.pdftxt").resolve())
    assert record["auxiliary_source_files"][0]["path"] == str((cache_dir / "paper.pdf").resolve())
    assert "PosixPath" not in json.dumps(log)


def test_build_pack_manifest_includes_existing_source_replenishment_log(tmp_path: Path) -> None:
    pack = tmp_path / "research_pack"
    pack.mkdir(parents=True)
    (pack / "source_replenishment_log.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "record_count": 2,
                "records": [
                    {"paper_id": "p-scene-graph", "source_urls": ["https://example.test/selected"]},
                    {"paper_id": "p-stale-other", "source_urls": ["https://example.test/stale"]},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run(
        [
            sys.executable,
            "-m",
            "resmax_survey_v2",
            "build-pack",
            "--macro-dir",
            str(FIXTURE_MACRO),
            "--out-dir",
            str(tmp_path),
            "--disable-oa-api",
            "--mode",
            "smoke",
            "--allow-auto-select",
            "--allow-abstract-fallback",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr

    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    artifacts = {artifact["path"]: artifact for artifact in manifest["artifacts"]}
    assert "source_replenishment_log.json" in artifacts
    assert artifacts["source_replenishment_log.json"]["kind"] == "source_replenishment_log"
    replenishment = json.loads((pack / "source_replenishment_log.json").read_text(encoding="utf-8"))
    assert replenishment["record_count"] == 1
    assert [record["paper_id"] for record in replenishment["records"]] == ["p-scene-graph"]

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
            "--mode",
            "smoke",
            "--allow-abstract-fallback",
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
            "--mode",
            "smoke",
            "--allow-auto-select",
            "--allow-abstract-fallback",
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
