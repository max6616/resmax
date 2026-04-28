from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from resmax_core.ids import input_hash, make_state_id, stable_hash
from resmax_core.state import SCHEMA_VERSION, utc_now

from .fs_hygiene import remove_known_os_metadata
from search_literature_lib.paper_source_fetch import derive_pdf_candidates, fetch_and_cache_source


PRODUCER = {"name": "resmax_survey_v2.phase3_pack", "version": SCHEMA_VERSION, "run_id": "phase3"}
REPO_ROOT = Path(__file__).resolve().parents[5]
GLOBAL_SOURCE_CACHE = REPO_ROOT / "paper_database" / "source_cache"
MAX_DEFAULT_EVIDENCE_CANDIDATES = 30
DEFAULT_MODE = "production"
NON_INTERACTIVE_MODES = {"test", "dev", "debug", "smoke"}
EVIDENCE_TERMS = (
    "benchmark",
    "evaluation",
    "dataset",
    "baseline",
    "limitation",
    "limited",
    "fails",
    "lack",
    "missing",
    "compute",
    "cost",
    "efficient",
    "low compute",
    "resource",
    "improve",
    "outperform",
    "ablation",
    "transfer",
)

GAP_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "gap_type": "evidence_tension",
        "terms": ("limitation", "limited", "fails", "failure", "error", "robustness", "generalization", "challenge"),
        "min_cards": 2,
    },
    {
        "gap_type": "method_transfer",
        "terms": ("implementation", "code", "open-source", "open source", "pretrained", "weights", "reproduce", "reproducibility"),
        "min_cards": 2,
    },
    {
        "gap_type": "benchmark_protocol_gap",
        "terms": ("benchmark", "evaluation", "dataset", "metric", "baseline", "compare", "comparison", "ablation", "protocol"),
        "min_cards": 2,
    },
    {
        "gap_type": "resource_arbitrage",
        "terms": ("compute", "cost", "efficient", "efficiency", "runtime", "real-time", "realtime", "resource", "fast"),
        "min_cards": 2,
    },
)


def resolve_macro_root(path: Path) -> Path:
    path = path.resolve()
    if (path / "survey_v2" / "macro").exists():
        return path
    if path.name == "survey_v2" and (path / "macro").exists():
        return path.parent
    if path.name == "macro" and path.parent.name == "survey_v2":
        return path.parent.parent
    raise FileNotFoundError(f"cannot locate survey_v2/macro under: {path}")


def resolve_pack_dir(path: Path) -> Path:
    path = path.resolve()
    return path if path.name == "research_pack" else path / "research_pack"


def select_subdirection(
    *,
    macro_dir: Path,
    out_dir: Path,
    subdirection_id: str = "",
    max_candidates: int | None = None,
    allow_auto_select: bool = False,
    mode: str = DEFAULT_MODE,
) -> dict[str, Any]:
    macro_root = resolve_macro_root(macro_dir)
    pack_dir = resolve_pack_dir(out_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)
    remove_known_os_metadata(pack_dir)

    research_spec = _load_json(macro_root / "survey_v2" / "spec" / "research_spec.json")
    subdirection_map = _load_json(macro_root / "survey_v2" / "macro" / "subdirection_map.json")
    roi_rows = _read_csv(macro_root / "survey_v2" / "macro" / "subdirection_roi_table.csv")
    candidates = _read_csv(macro_root / "survey_v2" / "macro" / "broad_candidates.csv")

    entries = {entry["subdirection_id"]: entry for entry in subdirection_map.get("subdirections", [])}
    auto_selected = False
    selection_method = "explicit_subdirection_id"
    selected_id = subdirection_id.strip()
    if not selected_id:
        if not allow_auto_select:
            _write_pending_gate(
                pack_dir,
                gate_id="G1",
                phase="Phase 2 -> Phase 3",
                trigger="build-pack or select-subdirection was called without --subdirection-id",
                user_question=(
                    "Select one subdirection_id from subdirection_map.json or subdirection_roi_table.csv, "
                    "or explicitly rerun with --allow-auto-select for a non-production smoke/dev/debug/test path."
                ),
                allowed_answers=[
                    "rerun with --subdirection-id <id>",
                    "rerun with --allow-auto-select only for smoke/dev/debug/test",
                    "stop and refine the Phase 2 macro survey",
                ],
                default_action="stop",
                artifacts_to_show=[
                    "survey_v2/macro/subdirection_map.json",
                    "survey_v2/macro/subdirection_roi_table.csv",
                    "survey_v2/macro/macro_survey_report.md",
                ],
                mode=mode,
            )
            raise ValueError(
                "G1 subdirection selection gate required: pass --subdirection-id, "
                "or explicitly pass --allow-auto-select for a smoke/dev/debug/test path."
            )
        if not roi_rows:
            raise ValueError("subdirection_roi_table.csv has no rows")
        selected_id = _auto_select_subdirection(roi_rows, candidates, research_spec)
        auto_selected = True
        selection_method = "auto_intent_roi_match"
    if selected_id not in entries:
        raise ValueError(f"subdirection_id not found in subdirection_map: {selected_id}")
    _clear_pending_gate(pack_dir, "G1")

    candidate_limit = _candidate_limit(research_spec, max_candidates)
    selected_candidates = [row for row in candidates if row.get("subdirection_id") == selected_id]
    selected_candidates.sort(
        key=lambda row: (
            _grade_sort_key(row),
            -_to_float(row.get("candidate_grade_score", "0")),
            -_to_float(row.get("best_embedding_score", "0")),
            -_to_int(row.get("match_count", "0")),
            -_to_float(row.get("best_keyword_score", "0")),
            -_source_availability_score(row),
            row.get("title", ""),
            row.get("paper_id", ""),
        )
    )
    selected_candidates = selected_candidates[:candidate_limit]
    if not selected_candidates:
        raise ValueError(f"selected subdirection has no candidate rows: {selected_id}")

    roi_snapshot = next((row for row in roi_rows if row.get("subdirection_id") == selected_id), {})
    entry = entries[selected_id]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "selected_at": utc_now(),
        "selected_subdirection_id": selected_id,
        "label": entry.get("label", selected_id),
        "description": entry.get("description", ""),
        "auto_selected": auto_selected,
        "selection_method": selection_method,
        "execution_mode": mode,
        "candidate_limit": candidate_limit,
        "paper_count": len(selected_candidates),
        "selected_candidate_ids": [row["paper_id"] for row in selected_candidates],
        "selected_candidates": [
            {
                "paper_id": row.get("paper_id", ""),
                "title": row.get("title", ""),
                "venue": row.get("venue", ""),
                "year": row.get("year", ""),
                "source_weight": row.get("source_weight", "unknown"),
                "source_text_status": row.get("source_text_status", ""),
                "candidate_grade": row.get("candidate_grade", ""),
                "candidate_grade_score": row.get("candidate_grade_score", ""),
                "candidate_grade_reasons": row.get("candidate_grade_reasons", ""),
                "rough_positive_signal": row.get("rough_positive_signal", ""),
                "rough_difficulty_signal": row.get("rough_difficulty_signal", ""),
                "roi_unknowns": row.get("roi_unknowns", ""),
            }
            for row in selected_candidates
        ],
        "roi_snapshot": roi_snapshot,
        "research_spec_id": research_spec.get("state_id", ""),
    }
    _write_json(pack_dir / "selected_subdirection.json", payload)
    remove_known_os_metadata(pack_dir)
    return payload


def extract_evidence(
    *,
    macro_dir: Path,
    out_dir: Path,
    source_cache_dir: Path | None = None,
    max_spans_per_paper: int = 3,
    allow_abstract_fallback: bool = False,
    mode: str = DEFAULT_MODE,
) -> dict[str, Any]:
    macro_root = resolve_macro_root(macro_dir)
    pack_dir = resolve_pack_dir(out_dir)
    selected = _load_json(pack_dir / "selected_subdirection.json")
    selected_rows = _candidate_rows_by_id(macro_root, selected["selected_candidate_ids"])
    source_roots = _source_roots(macro_root, _effective_source_cache_dir(macro_root, source_cache_dir))

    spans: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    missing_source: list[dict[str, Any]] = []
    missing_pdf: list[dict[str, Any]] = []
    abstract_fallback_count = 0

    for paper_id in selected["selected_candidate_ids"]:
        row = selected_rows.get(paper_id, {"paper_id": paper_id})
        paper_dir = _find_paper_dir(source_roots, paper_id)
        source_files = _readable_sources(paper_dir) if paper_dir else []
        has_pdf_text = bool(paper_dir and (paper_dir / "paper.pdftxt").exists())
        if not has_pdf_text:
            missing_pdf.append(_missing_pdf_record(row, paper_dir))

        paper_spans: list[dict[str, Any]] = []
        if source_files:
            paper_spans = _extract_spans_for_paper(
                row=row,
                paper_dir=paper_dir,
                source_files=source_files,
                scope=selected["selected_subdirection_id"],
                max_spans=max_spans_per_paper,
            )

        if not paper_spans and allow_abstract_fallback:
            fallback_spans = _extract_abstract_spans_for_paper(
                row=row,
                scope=selected["selected_subdirection_id"],
                max_spans=max_spans_per_paper,
            )
            if fallback_spans:
                abstract_fallback_count += 1
                paper_spans = fallback_spans

        if not source_files:
            missing_source.append(_missing_source_record(row, paper_dir, abstract_fallback=bool(paper_spans)))
        elif not paper_spans:
            missing_source.append(_unextractable_source_record(row, paper_dir))

        if not paper_spans:
            continue

        spans.extend(paper_spans)
        for span in paper_spans:
            if span.get("extraction_status") != "extracted":
                continue
            cards.append(_card_from_span(row, span, selected))

    _write_jsonl(pack_dir / "evidence_spans.jsonl", spans)
    _write_jsonl(pack_dir / "evidence_cards.jsonl", cards)
    _write_json(pack_dir / "missing_source_report.json", {"schema_version": SCHEMA_VERSION, "records": missing_source})
    _write_json(pack_dir / "missing_pdf_report.json", {"schema_version": SCHEMA_VERSION, "records": missing_pdf})
    coverage = {
        "selected_candidate_count": len(selected["selected_candidate_ids"]),
        "papers_with_evidence": len({span["paper_id"] for span in spans if span.get("extraction_status") == "extracted"}),
        "evidence_span_count": len([span for span in spans if span.get("extraction_status") == "extracted"]),
        "evidence_card_count": len(cards),
        "missing_source_count": len(missing_source),
        "missing_pdf_count": len(missing_pdf),
        "abstract_fallback_count": abstract_fallback_count,
        "full_text_evidence_count": len(
            [
                span
                for span in spans
                if span.get("extraction_status") == "extracted" and span.get("source_type") != "accepted_index"
            ]
        ),
    }
    if (
        coverage.get("abstract_fallback_count", 0) or coverage.get("missing_source_count", 0)
    ) and not allow_abstract_fallback:
        _write_pending_gate(
            pack_dir,
            gate_id="G2",
            phase="Phase 3 evidence extraction",
            trigger="full-text evidence is incomplete for one or more selected candidates",
            user_question="Approve degraded weak evidence, provide stronger sources, or choose a different subdirection?",
            allowed_answers=[
                "replenish source cache and rerun",
                "rerun with --allow-abstract-fallback for weak/degraded evidence",
                "switch subdirection",
            ],
            default_action="stop",
            artifacts_to_show=[
                "source_materialization_report.json",
                "missing_source_report.json",
                "missing_pdf_report.json",
            ],
            mode=mode,
            details=coverage,
        )
        raise ValueError(
            "G2 evidence expansion gate required: "
            f"missing_source_count={coverage.get('missing_source_count', 0)} "
            f"abstract_fallback_count={coverage.get('abstract_fallback_count', 0)}. "
            "Pass --allow-abstract-fallback only after explicit approval to continue with degraded evidence."
        )
    return coverage


def materialize_sources(
    *,
    macro_dir: Path,
    out_dir: Path,
    source_cache_dir: Path | None = None,
    disable_oa_api: bool = False,
    enable_sci_hub: bool = False,
    overwrite_sources: bool = False,
    progress: bool = True,
) -> dict[str, Any]:
    macro_root = resolve_macro_root(macro_dir)
    pack_dir = resolve_pack_dir(out_dir)
    selected = _load_json(pack_dir / "selected_subdirection.json")
    selected_rows = _candidate_rows_by_id(macro_root, selected["selected_candidate_ids"])
    cache_dir = _effective_source_cache_dir(macro_root, source_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    total = len(selected["selected_candidate_ids"])
    for index, paper_id in enumerate(selected["selected_candidate_ids"], 1):
        row = selected_rows.get(paper_id, {"paper_id": paper_id})
        if progress:
            print(f"[survey-v2] materialize {index}/{total} paper_id={paper_id}", flush=True)
        pdf_candidates = _pdf_candidates(row)
        enable_oa_api = not disable_oa_api and bool(
            row.get("doi")
            or row.get("arxiv_id")
            or row.get("openreview_forum_id")
            or pdf_candidates
            or row.get("title")
        )
        desc = fetch_and_cache_source(
            paper_id,
            row.get("arxiv_id", ""),
            cache_dir,
            pdf_url_candidates=pdf_candidates,
            doi=row.get("doi", ""),
            title=row.get("title", "") if enable_oa_api else "",
            enable_oa_api=enable_oa_api,
            enable_sci_hub=enable_sci_hub,
            overwrite=overwrite_sources,
        )
        paper_dir_name = desc.get("paper_dir", _safe_id(paper_id))
        paper_dir = cache_dir / paper_dir_name
        disk_sources = _readable_sources(paper_dir) if paper_dir.exists() else []
        reader_tags = _reader_tags_from_disk_sources(disk_sources)
        source_files = dict(desc.get("source_files", {}))
        text_chars = dict(desc.get("text_chars", {}))
        for source in disk_sources:
            tag = _reader_tag(source["source_type"])
            if not tag:
                continue
            source_files.setdefault(tag, source["path"].name)
            text_chars.setdefault(tag, source["path"].stat().st_size)
        record = {
            "paper_id": paper_id,
            "title": row.get("title", ""),
            "paper_dir": paper_dir_name,
            "sources_present": desc.get("sources_present", []),
            "reader_sources_present": reader_tags,
            "source_files": source_files,
            "text_chars": text_chars,
            "pdf_candidates": pdf_candidates,
            "github_urls": desc.get("github_urls", []),
            "project_page_urls": desc.get("project_page_urls", []),
            "errors": desc.get("errors", {}),
            "diagnostics": desc.get("diagnostics", {}),
            "readable_source_ok": bool(reader_tags),
            "pdf_text_ok": "pdf" in desc.get("sources_present", []),
            "sci_hub_enabled": enable_sci_hub,
            "oa_api_enabled": enable_oa_api,
        }
        records.append(record)
        if progress:
            print(
                "[survey-v2] materialize result "
                f"{index}/{total} paper_id={paper_id} "
                f"readable={record['readable_source_ok']} pdf_text={record['pdf_text_ok']} "
                f"sources={','.join(record['reader_sources_present']) or 'none'}",
                flush=True,
            )

    counts = {
        "selected_candidate_count": len(selected["selected_candidate_ids"]),
        "readable_source_count": sum(1 for row in records if row["readable_source_ok"]),
        "missing_readable_source_count": sum(1 for row in records if not row["readable_source_ok"]),
        "pdf_text_count": sum(1 for row in records if row["pdf_text_ok"]),
        "missing_pdf_text_count": sum(1 for row in records if not row["pdf_text_ok"]),
        "tex_count": sum(1 for row in records if "tex" in row["reader_sources_present"]),
        "md_count": sum(1 for row in records if "md" in row["reader_sources_present"]),
    }
    web_search_replenishment = [
        _web_search_replenishment_record(row, cache_dir)
        for row in records
        if not row["readable_source_ok"]
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "selected_subdirection_id": selected["selected_subdirection_id"],
        "cache_dir": str(cache_dir),
        "policy": {
            "targeted_selected_candidates_only": True,
            "full_library_full_text_parsing": False,
            "global_reusable_source_cache": str(GLOBAL_SOURCE_CACHE),
            "sci_hub_enabled": enable_sci_hub,
            "oa_api_enabled_when_identifiers_exist": not disable_oa_api,
            "title_only_oa_search": not disable_oa_api,
            "general_web_search_required_before_degraded_fallback": True,
            "coverage_target": "critical_claim_and_asset_evidence",
            "min_readable_source_coverage_for_production": None,
            "missing_source_degradation": "record missing source and missing evidence instead of treating metadata as verified content",
        },
        "counts": counts,
        "records": records,
        "web_search_replenishment": web_search_replenishment,
    }
    _write_json(pack_dir / "source_materialization_report.json", report)
    return report


def compile_tension(*, out_dir: Path) -> dict[str, Any]:
    pack_dir = resolve_pack_dir(out_dir)
    selected = _load_json(pack_dir / "selected_subdirection.json")
    spans = _read_jsonl(pack_dir / "evidence_spans.jsonl")
    cards = _read_jsonl(pack_dir / "evidence_cards.jsonl")
    missing_source = _load_json(pack_dir / "missing_source_report.json").get("records", [])

    claims = [_claim_from_card(card, selected) for card in cards]
    if not claims:
        claims.append(_missing_claim(selected))
    edges = _claim_edges(claims)
    claim_graph_input = {"claims": claims, "edges": edges, "scope": selected["selected_subdirection_id"]}
    claim_graph = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("claim_graph", claim_graph_input),
        "created_at": utc_now(),
        "input_hash": input_hash(claim_graph_input),
        "parent_state_ids": [card["state_id"] for card in cards],
        "producer": PRODUCER,
        "claims": claims,
        "edges": edges,
    }
    _write_json(pack_dir / "claim_graph.json", claim_graph)

    gaps = _gaps_from_claims(selected, claims, cards, spans, missing_source)
    gap_map_input = {"claim_graph_id": claim_graph["state_id"], "gaps": gaps}
    gap_map = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("gap_map", gap_map_input),
        "created_at": utc_now(),
        "input_hash": input_hash(gap_map_input),
        "parent_state_ids": [claim_graph["state_id"]],
        "producer": PRODUCER,
        "claim_graph_id": claim_graph["state_id"],
        "gaps": gaps,
    }
    _write_json(pack_dir / "gap_map.json", gap_map)
    return {"claim_graph": claim_graph, "gap_map": gap_map}


def build_pack(
    *,
    macro_dir: Path,
    out_dir: Path,
    subdirection_id: str = "",
    source_cache_dir: Path | None = None,
    max_candidates: int | None = None,
    max_spans_per_paper: int = 3,
    skip_source_materialization: bool = False,
    disable_oa_api: bool = False,
    enable_sci_hub: bool = False,
    overwrite_sources: bool = False,
    allow_auto_select: bool = False,
    allow_abstract_fallback: bool = False,
    mode: str = DEFAULT_MODE,
    progress: bool = True,
) -> dict[str, Any]:
    macro_root = resolve_macro_root(macro_dir)
    pack_dir = resolve_pack_dir(out_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)
    remove_known_os_metadata(pack_dir)
    _copy_macro_artifacts(macro_root, pack_dir)
    selected = select_subdirection(
        macro_dir=macro_root,
        out_dir=pack_dir,
        subdirection_id=subdirection_id,
        max_candidates=max_candidates,
        allow_auto_select=allow_auto_select,
        mode=mode,
    )
    _prune_source_replenishment_log(pack_dir, set(selected.get("selected_candidate_ids", [])))
    materialization: dict[str, Any] = {}
    if not skip_source_materialization:
        materialization = materialize_sources(
            macro_dir=macro_root,
            out_dir=pack_dir,
            source_cache_dir=source_cache_dir,
            disable_oa_api=disable_oa_api,
            enable_sci_hub=enable_sci_hub,
            overwrite_sources=overwrite_sources,
            progress=progress,
        )
        if _source_gate_required(materialization) and not allow_abstract_fallback:
            _write_pending_gate(
                pack_dir,
                gate_id="G2",
                phase="Phase 3 source materialization",
                trigger="selected candidates do not have complete readable full-text coverage",
                user_question=(
                    "Choose whether to replenish sources, enable approved source tooling, switch direction, "
                    "or explicitly continue with weak/degraded abstract fallback."
                ),
                allowed_answers=[
                    "perform legal general web search and replenish source cache, then rerun",
                    "replenish source cache and rerun",
                    "rerun with --enable-sci-hub only if explicitly allowed",
                    "provide approved MinerU/manual markdown cache and rerun",
                    "rerun with --allow-abstract-fallback for degraded evidence",
                    "switch subdirection",
                ],
                default_action="stop",
                artifacts_to_show=[
                    "source_materialization_report.json",
                ],
                mode=mode,
                details=materialization.get("counts", {}),
            )
            counts = materialization.get("counts", {})
            raise ValueError(
                "G2 evidence expansion gate required: readable_source_count="
                f"{counts.get('readable_source_count', 0)}/{counts.get('selected_candidate_count', 0)}. "
                "Inspect source_materialization_report.json, run legal general web search for missing "
                "sources, replenish the source cache, or explicitly pass --allow-abstract-fallback "
                "for degraded evidence."
            )
        _clear_pending_gate(pack_dir, "G2")
    coverage = extract_evidence(
        macro_dir=macro_root,
        out_dir=pack_dir,
        source_cache_dir=_effective_source_cache_dir(macro_root, source_cache_dir),
        max_spans_per_paper=max_spans_per_paper,
        allow_abstract_fallback=allow_abstract_fallback,
        mode=mode,
    )
    if (
        coverage.get("abstract_fallback_count", 0) or coverage.get("missing_source_count", 0)
    ) and not allow_abstract_fallback:
        _write_pending_gate(
            pack_dir,
            gate_id="G2",
            phase="Phase 3 evidence extraction",
            trigger="full-text evidence is incomplete for one or more selected candidates",
            user_question="Approve degraded weak evidence, provide stronger sources, or choose a different subdirection?",
            allowed_answers=[
                "replenish source cache and rerun",
                "rerun with --allow-abstract-fallback for weak/degraded evidence",
                "switch subdirection",
            ],
            default_action="stop",
            artifacts_to_show=[
                "source_materialization_report.json",
                "missing_source_report.json",
                "missing_pdf_report.json",
            ],
            mode=mode,
            details=coverage,
        )
        raise ValueError(
            "G2 evidence expansion gate required: "
            f"missing_source_count={coverage.get('missing_source_count', 0)} "
            f"abstract_fallback_count={coverage.get('abstract_fallback_count', 0)}. "
            "Pass --allow-abstract-fallback only after explicit approval to continue with degraded evidence."
        )
    _clear_pending_gate(pack_dir, "G2")
    tension = compile_tension(out_dir=pack_dir)
    _write_coverage_report(pack_dir, selected, coverage)
    _write_field_map(pack_dir)
    manifest = _write_manifest(pack_dir, selected, coverage, tension["gap_map"], materialization)
    remove_known_os_metadata(pack_dir)
    return {"pack_dir": str(pack_dir), "manifest": manifest, "coverage": coverage, "materialization": materialization}


def _copy_macro_artifacts(macro_root: Path, pack_dir: Path) -> None:
    pairs = (
        ("survey_v2/spec/research_spec.json", "research_spec.json"),
        ("survey_v2/spec/source_policy.json", "source_policy.json"),
        ("survey_v2/spec/query_families.jsonl", "query_families.jsonl"),
        ("survey_v2/macro/retrieval_trace.jsonl", "retrieval_trace.jsonl"),
        ("survey_v2/macro/broad_candidates.csv", "broad_candidates.csv"),
    )
    for src_rel, dst_name in pairs:
        src = macro_root / src_rel
        if not src.exists():
            raise FileNotFoundError(f"required macro artifact missing: {src}")
        shutil.copyfile(src, pack_dir / dst_name)


def _source_gate_required(materialization: dict[str, Any]) -> bool:
    counts = materialization.get("counts", {}) if isinstance(materialization, dict) else {}
    selected = int(counts.get("selected_candidate_count") or 0)
    missing = int(counts.get("missing_readable_source_count") or 0)
    if selected <= 0:
        return False
    return missing > 0


def _write_pending_gate(
    pack_dir: Path,
    *,
    gate_id: str,
    phase: str,
    trigger: str,
    user_question: str,
    allowed_answers: list[str],
    default_action: str,
    artifacts_to_show: list[str],
    mode: str,
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "gate_id": gate_id,
        "phase": phase,
        "trigger": trigger,
        "user_question": user_question,
        "allowed_answers": allowed_answers,
        "default_action_if_no_answer": default_action,
        "artifact_to_show_before_asking": artifacts_to_show,
        "artifact_written_after_decision": f"pending_gate_{gate_id.lower()}.json",
        "non_interactive_exception": sorted(NON_INTERACTIVE_MODES),
        "execution_mode": mode,
        "created_at": utc_now(),
        "details": details or {},
    }
    _write_json(pack_dir / f"pending_gate_{gate_id.lower()}.json", payload)


def _clear_pending_gate(pack_dir: Path, gate_id: str) -> None:
    path = pack_dir / f"pending_gate_{gate_id.lower()}.json"
    if path.exists():
        path.unlink()


def _prune_source_replenishment_log(pack_dir: Path, selected_candidate_ids: set[str]) -> None:
    path = pack_dir / "source_replenishment_log.json"
    if not path.exists():
        return
    payload = _load_json(path)
    records = payload.get("records", []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        return
    selected = {str(paper_id) for paper_id in selected_candidate_ids if str(paper_id)}
    filtered = [record for record in records if isinstance(record, dict) and record.get("paper_id") in selected]
    if len(filtered) == len(records):
        return
    if not filtered:
        path.unlink()
        return
    log_input = {"records": filtered}
    payload["records"] = filtered
    payload["record_count"] = len(filtered)
    payload["created_at"] = utc_now()
    payload["input_hash"] = input_hash(log_input)
    payload["state_id"] = make_state_id("source_replenishment_log", log_input)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("producer", PRODUCER)
    _write_json(path, payload)


def _write_manifest(
    pack_dir: Path,
    selected: dict[str, Any],
    coverage: dict[str, Any],
    gap_map: dict[str, Any],
    materialization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    research_spec = _load_json(pack_dir / "research_spec.json")
    artifacts = [
        _artifact(pack_dir, "research_spec", "research_spec.json", "research_spec.schema.json"),
        _artifact(pack_dir, "source_policy", "source_policy.json", "source_policy.schema.json"),
        _artifact(pack_dir, "query_family", "query_families.jsonl", "query_family.schema.json"),
        _artifact(pack_dir, "retrieval_trace", "retrieval_trace.jsonl", "retrieval_trace.schema.json"),
        _artifact(pack_dir, "selected_subdirection", "selected_subdirection.json"),
        _artifact(pack_dir, "broad_candidates", "broad_candidates.csv"),
        _artifact(pack_dir, "evidence_span", "evidence_spans.jsonl", "evidence_span.schema.json"),
        _artifact(pack_dir, "evidence_card", "evidence_cards.jsonl", "evidence_card.schema.json"),
        _artifact(pack_dir, "claim_graph", "claim_graph.json", "claim_graph.schema.json"),
        _artifact(pack_dir, "gap_map", "gap_map.json", "gap_map.schema.json"),
        _artifact(pack_dir, "missing_source_report", "missing_source_report.json"),
        _artifact(pack_dir, "missing_pdf_report", "missing_pdf_report.json"),
        _artifact(pack_dir, "coverage_report", "coverage_report.md"),
        _artifact(pack_dir, "field_map", "field_map.md"),
    ]
    if (pack_dir / "source_materialization_report.json").exists():
        artifacts.append(_artifact(pack_dir, "source_materialization_report", "source_materialization_report.json"))
    if (pack_dir / "source_replenishment_log.json").exists():
        artifacts.append(_artifact(pack_dir, "source_replenishment_log", "source_replenishment_log.json"))
    manifest_input = {
        "research_spec_id": research_spec["state_id"],
        "selected_subdirection_id": selected["selected_subdirection_id"],
        "artifact_hashes": [artifact["sha256"] for artifact in artifacts],
        "gap_map_id": gap_map["state_id"],
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("research_pack", manifest_input),
        "created_at": utc_now(),
        "input_hash": input_hash(manifest_input),
        "parent_state_ids": [research_spec["state_id"], gap_map["state_id"]],
        "producer": PRODUCER,
        "pack_id": f"research_pack/{selected['selected_subdirection_id']}",
        "research_spec_id": research_spec["state_id"],
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "evidence_coverage": coverage,
        "source_materialization": (materialization or {}).get("counts", {}),
        "decision_status": "pending",
    }
    _write_json(pack_dir / "manifest.json", manifest)
    return manifest


def _artifact(pack_dir: Path, kind: str, path: str, schema: str = "") -> dict[str, str]:
    payload = {"kind": kind, "path": path, "sha256": _sha256_file(pack_dir / path)}
    if schema:
        payload["schema"] = schema
    return payload


def _extract_spans_for_paper(
    *,
    row: dict[str, str],
    paper_dir: Path,
    source_files: list[dict[str, Any]],
    scope: str,
    max_spans: int,
) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for source in source_files:
        text = source["path"].read_text(encoding="utf-8", errors="ignore")
        passages = _ranked_passages(text)
        for passage in passages[:max_spans]:
            locator = f"{paper_dir.name}/{source['path'].name}#char={passage['start']}-{passage['end']}"
            span_input = {
                "paper_id": row.get("paper_id", ""),
                "source_type": source["source_type"],
                "locator": locator,
                "quote_hash": stable_hash(passage["text"]),
                "scope": scope,
            }
            spans.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "state_id": make_state_id("evidence_span", span_input),
                    "created_at": utc_now(),
                    "input_hash": input_hash(span_input),
                    "parent_state_ids": [],
                    "producer": PRODUCER,
                    "paper_id": row.get("paper_id", ""),
                    "span_type": _span_type(passage["text"]),
                    "text": passage["text"],
                    "source": {"kind": source["source_kind"], "locator": locator, "status": "supported"},
                    "source_weight": _source_weight(row.get("source_weight", "")),
                    "evidence_status": "supported",
                    "source_type": source["source_type"],
                    "section": _section_name(text, passage["start"]),
                    "locator": locator,
                    "quote_hash": stable_hash(passage["text"]),
                    "parser": source["parser"],
                    "extraction_status": "extracted",
                    "discard_reason": "",
                }
            )
        if spans:
            break
    return spans


def _extract_abstract_spans_for_paper(
    *,
    row: dict[str, str],
    scope: str,
    max_spans: int,
) -> list[dict[str, Any]]:
    abstract = re.sub(r"\s+", " ", (row.get("abstract_raw") or "").strip())
    if len(abstract) < 40:
        return []
    text = abstract[:1200]
    locator = f"{row.get('paper_id', '')}.abstract_raw"
    span_input = {
        "paper_id": row.get("paper_id", ""),
        "source_type": "accepted_index",
        "locator": locator,
        "quote_hash": stable_hash(text),
        "scope": scope,
    }
    return [
        {
            "schema_version": SCHEMA_VERSION,
            "state_id": make_state_id("evidence_span", span_input),
            "created_at": utc_now(),
            "input_hash": input_hash(span_input),
            "parent_state_ids": [],
            "producer": PRODUCER,
            "paper_id": row.get("paper_id", ""),
            "span_type": "abstract",
            "text": text,
            "source": {"kind": "accepted_index", "locator": locator, "status": "supported"},
            "source_weight": "weak",
            "evidence_status": "supported",
            "source_type": "accepted_index",
            "section": "abstract",
            "locator": locator,
            "quote_hash": stable_hash(text),
            "parser": "accepted_index.abstract_raw",
            "extraction_status": "extracted",
            "discard_reason": "abstract_metadata_fallback_full_text_missing",
        }
    ][: max(1, max_spans)]


def _card_from_span(row: dict[str, str], span: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
    relation = _relation(span["text"])
    card_input = {
        "span_id": span["state_id"],
        "paper_id": span["paper_id"],
        "relation": relation,
        "scope": selected["selected_subdirection_id"],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "state_id": make_state_id("evidence_card", card_input),
        "created_at": utc_now(),
        "input_hash": input_hash(card_input),
        "parent_state_ids": [span["state_id"]],
        "producer": PRODUCER,
        "claim_text": _claim_text(row, span),
        "interpretation": _interpretation(relation, selected),
        "evidence_span_ids": [span["state_id"]],
        "evidence_status": "supported",
        "source_weight": span["source_weight"],
        "limitations": _card_limitations(span),
        "relation": relation,
        "scope": selected["selected_subdirection_id"],
        "strength": "context" if span.get("source_type") == "accepted_index" and relation == "context" else "weak",
    }


def _claim_from_card(card: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
    claim_input = {
        "card_id": card["state_id"],
        "scope": selected["selected_subdirection_id"],
        "text": card["claim_text"],
    }
    return {
        "claim_id": make_state_id("claim", claim_input),
        "text": card["claim_text"],
        "scope": selected["selected_subdirection_id"],
        "strength": card.get("strength", "weak"),
        "evidence_status": card.get("evidence_status", "supported"),
        "evidence_card_ids": [card["state_id"]],
    }


def _missing_claim(selected: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": "claim_missing_cached_full_text",
        "text": f"Selected subdirection {selected['selected_subdirection_id']} lacks cached full-text evidence.",
        "scope": selected["selected_subdirection_id"],
        "strength": "context",
        "evidence_status": "insufficient_evidence",
        "evidence_card_ids": [],
    }


def _claim_edges(claims: list[dict[str, Any]]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    positive = [claim for claim in claims if _has_any(claim["text"], ("improve", "outperform", "effective"))]
    limiting = [claim for claim in claims if _has_any(claim["text"], ("limitation", "limited", "lack", "cost", "compute", "baseline"))]
    for left in positive[:2]:
        for right in limiting[:2]:
            if left["claim_id"] != right["claim_id"]:
                edges.append(
                    {
                        "source_claim_id": left["claim_id"],
                        "target_claim_id": right["claim_id"],
                        "relation": "motivates",
                    }
                )
    return edges


def _gaps_from_claims(
    selected: dict[str, Any],
    claims: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    missing_source: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    roi = selected.get("roi_snapshot", {})
    roi_signals = {
        "positive": _split_signal(roi.get("positive_signals", "")),
        "difficulty": _split_signal(roi.get("difficulty_signals", "")),
        "unknowns": _split_signal(roi.get("roi_unknowns", "")),
        "reviewer_blockers": [],
    }
    card_contexts = _card_contexts(cards, spans, claims)
    for profile in GAP_PROFILES:
        selected_cards = _cards_for_gap_profile(card_contexts, profile)
        if len(selected_cards) < int(profile["min_cards"]):
            continue
        card_ids = [item["card"]["state_id"] for item in selected_cards]
        claim_ids = [item["claim_id"] for item in selected_cards if item.get("claim_id")]
        paper_count = len({item.get("paper_id", "") for item in selected_cards if item.get("paper_id")})
        gap_type = str(profile["gap_type"])
        gaps.append(
            {
                "gap_id": make_state_id("gap", {"type": gap_type, "cards": card_ids}),
                "description": _gap_description(gap_type, selected),
                "scope": selected["selected_subdirection_id"],
                "gap_type": gap_type,
                "supporting_claim_ids": _dedupe(claim_ids),
                "evidence_card_ids": card_ids,
                "confidence": "medium" if len(card_ids) >= 4 and paper_count >= 2 else "low",
                "evidence_status": "supported",
                "roi_signals": _roi_signals_for_gap(gap_type, roi_signals),
            }
        )
    if not gaps and len(cards) >= 2:
        selected_cards = _top_distinct_paper_cards(_card_contexts(cards, spans, claims), limit=6)
        card_ids = [item["card"]["state_id"] for item in selected_cards]
        claim_ids = [item["claim_id"] for item in selected_cards if item.get("claim_id")]
        gaps.append(
            {
                "gap_id": make_state_id("gap", {"type": "benchmark_protocol_gap", "cards": card_ids}),
                "description": _gap_description("benchmark_protocol_gap", selected),
                "scope": selected["selected_subdirection_id"],
                "gap_type": "benchmark_protocol_gap",
                "supporting_claim_ids": _dedupe(claim_ids),
                "evidence_card_ids": card_ids,
                "confidence": "low",
                "evidence_status": "supported",
                "roi_signals": _roi_signals_for_gap("benchmark_protocol_gap", roi_signals),
            }
        )
    if missing_source or len(cards) < 2:
        gaps.append(
            {
                "gap_id": make_state_id("gap", {"type": "missing_evidence", "scope": selected["selected_subdirection_id"], "missing": len(missing_source)}),
                "description": f"Full-text coverage is incomplete for {selected['label']}; missing papers must be resolved before stronger claims.",
                "scope": selected["selected_subdirection_id"],
                "gap_type": "missing_evidence",
                "supporting_claim_ids": [claims[0]["claim_id"]] if claims else [],
                "evidence_card_ids": [],
                "confidence": "low",
                "evidence_status": "insufficient_evidence",
                "roi_signals": {
                    "positive": roi_signals["positive"],
                    "difficulty": _dedupe([*roi_signals["difficulty"], "source_coverage_incomplete"]),
                    "unknowns": _dedupe([*roi_signals["unknowns"], "full_text_availability"]),
                    "reviewer_blockers": ["evidence_coverage"],
                },
            }
        )
    return gaps


def _card_contexts(
    cards: list[dict[str, Any]],
    spans: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    spans_by_id = {span.get("state_id", ""): span for span in spans}
    claim_by_card = {
        card_id: claim.get("claim_id", "")
        for claim in claims
        for card_id in claim.get("evidence_card_ids", [])
        if isinstance(card_id, str)
    }
    contexts: list[dict[str, Any]] = []
    for card in cards:
        card_spans = [spans_by_id.get(span_id, {}) for span_id in card.get("evidence_span_ids", [])]
        text = " ".join(
            [
                card.get("claim_text", ""),
                card.get("interpretation", ""),
                " ".join(span.get("text", "") for span in card_spans),
            ]
        ).lower()
        contexts.append(
            {
                "card": card,
                "claim_id": claim_by_card.get(card.get("state_id", ""), ""),
                "paper_id": next((span.get("paper_id", "") for span in card_spans if span.get("paper_id")), ""),
                "text": text,
                "relation": card.get("relation", ""),
            }
        )
    return contexts


def _cards_for_gap_profile(contexts: list[dict[str, Any]], profile: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    terms = tuple(str(term).lower() for term in profile["terms"])
    scored = []
    for item in contexts:
        text = item["text"]
        hits = sum(1 for term in terms if term in text)
        if hits <= 0:
            continue
        relation_bonus = 1 if item.get("relation") in {"motivates", "supports"} else 0
        scored.append((hits + relation_bonus, item))
    scored.sort(key=lambda pair: (-pair[0], item_sort_key(pair[1])))
    return _top_distinct_paper_cards([item for _, item in scored], limit=limit)


def _top_distinct_paper_cards(contexts: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_papers: set[str] = set()
    for item in contexts:
        paper_id = item.get("paper_id", "")
        if paper_id and paper_id in seen_papers:
            continue
        out.append(item)
        if paper_id:
            seen_papers.add(paper_id)
        if len(out) >= limit:
            break
    if len(out) < min(limit, len(contexts)):
        seen_cards = {item["card"].get("state_id", "") for item in out}
        for item in contexts:
            card_id = item["card"].get("state_id", "")
            if card_id in seen_cards:
                continue
            out.append(item)
            seen_cards.add(card_id)
            if len(out) >= limit:
                break
    return out


def item_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (item.get("paper_id", ""), item.get("card", {}).get("state_id", ""))


def _roi_signals_for_gap(gap_type: str, base: dict[str, list[str]]) -> dict[str, list[str]]:
    signals = {
        "positive": list(base["positive"]),
        "difficulty": list(base["difficulty"]),
        "unknowns": list(base["unknowns"]),
        "reviewer_blockers": list(base["reviewer_blockers"]),
    }
    if gap_type == "evidence_tension":
        signals["positive"] = _dedupe([*signals["positive"], "novelty_headroom"])
        signals["difficulty"] = _dedupe([*signals["difficulty"], "failure_mode_burden"])
        signals["unknowns"] = _dedupe([*signals["unknowns"], "failure_case_evidence"])
    elif gap_type == "method_transfer":
        signals["positive"] = _dedupe([*signals["positive"], "implementation_reuse"])
        signals["difficulty"] = _dedupe([*signals["difficulty"], "reproducibility_burden"])
        signals["unknowns"] = _dedupe([*signals["unknowns"], "code_availability"])
    elif gap_type == "benchmark_protocol_gap":
        signals["positive"] = _dedupe([*signals["positive"], "reviewer_risk_visibility"])
        signals["difficulty"] = _dedupe([*signals["difficulty"], "baseline_burden"])
        signals["unknowns"] = _dedupe([*signals["unknowns"], "benchmark_protocol"])
    elif gap_type == "resource_arbitrage":
        signals["positive"] = _dedupe([*signals["positive"], "low_compute_cost"])
        signals["difficulty"] = _dedupe([*signals["difficulty"], "compute_burden"])
    return signals


def _write_coverage_report(pack_dir: Path, selected: dict[str, Any], coverage: dict[str, Any]) -> None:
    lines = [
        "# Phase 3 Research Pack Coverage",
        "",
        "This Markdown file is display-only. JSON and JSONL artifacts are the source of truth.",
        "",
        f"- Selected subdirection: `{selected['selected_subdirection_id']}` ({selected['label']})",
        f"- Selection method: `{selected['selection_method']}`",
        f"- Auto-selected: `{str(selected['auto_selected']).lower()}`",
        f"- Selected candidates: {coverage['selected_candidate_count']}",
        f"- Papers with extracted evidence: {coverage['papers_with_evidence']}",
        f"- Evidence spans: {coverage['evidence_span_count']}",
        f"- Evidence cards: {coverage['evidence_card_count']}",
        f"- Full-text evidence spans: {coverage.get('full_text_evidence_count', 0)}",
        f"- Abstract fallback spans: {coverage.get('abstract_fallback_count', 0)}",
        f"- Missing source records: {coverage['missing_source_count']}",
        f"- Missing PDF records: {coverage['missing_pdf_count']}",
        "",
        "## Boundary",
        "",
        "- No full-library full-text parsing was performed.",
        "- Sci-Hub and MinerU fallback are disabled unless pre-existing cache files are present.",
        "- This pack contains gap evidence and constraints only; it does not contain ideas or final recommendations.",
        "",
    ]
    (pack_dir / "coverage_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_field_map(pack_dir: Path) -> None:
    lines = [
        "# Phase 3 Research Pack Field Map",
        "",
        "- `selected_subdirection.json`: selected Phase 2 subdirection and candidate budget.",
        "- `evidence_spans.jsonl`: quoted source spans with source type, locator, parser, quote hash, and extraction status.",
        "- `evidence_cards.jsonl`: reasoning units that cite span ids and declare relation, scope, strength, and evidence status.",
        "- `claim_graph.json`: single-writer canonical claims and claim relations.",
        "- `gap_map.json`: gaps that cite claims/evidence or explicitly use `missing_evidence`.",
        "- `missing_source_report.json`: selected candidates without readable cached source.",
        "- `missing_pdf_report.json`: selected candidates without cached PDF text layer.",
        "- `source_materialization_report.json`: targeted source/PDF/TeX materialization attempts and outcomes.",
        "- `manifest.json`: artifact list and sha256 hashes verified by `validate_research_pack.py`.",
        "",
    ]
    (pack_dir / "field_map.md").write_text("\n".join(lines), encoding="utf-8")


def _candidate_limit(research_spec: dict[str, Any], max_candidates: int | None) -> int:
    spec_limit = (
        research_spec.get("budget_policy", {}).get("max_targeted_evidence_candidates")
        if isinstance(research_spec.get("budget_policy"), dict)
        else None
    )
    limit = max_candidates if max_candidates is not None else spec_limit
    if not isinstance(limit, int) or limit <= 0:
        limit = MAX_DEFAULT_EVIDENCE_CANDIDATES
    return min(limit, MAX_DEFAULT_EVIDENCE_CANDIDATES)


def _candidate_rows_by_id(macro_root: Path, paper_ids: list[str]) -> dict[str, dict[str, str]]:
    rows = _read_csv(macro_root / "survey_v2" / "macro" / "broad_candidates.csv")
    wanted = set(paper_ids)
    return {row.get("paper_id", ""): row for row in rows if row.get("paper_id", "") in wanted}


def _effective_source_cache_dir(macro_root: Path, explicit: Path | None) -> Path:
    if explicit:
        return explicit.resolve()
    resolved = macro_root.resolve()
    if resolved.is_relative_to(REPO_ROOT):
        return GLOBAL_SOURCE_CACHE.resolve()
    return (macro_root / "survey_v2" / "paper_sources").resolve()


def _source_roots(macro_root: Path, explicit: Path | None) -> list[Path]:
    roots = []
    if explicit:
        roots.append(explicit.resolve())
    roots.extend(
        [
            macro_root / "survey_v2" / "paper_sources",
            macro_root / "paper_sources",
            GLOBAL_SOURCE_CACHE,
        ]
    )
    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved.exists() and resolved not in seen:
            seen.add(resolved)
            deduped.append(resolved)
    return deduped


def _pdf_candidates(row: dict[str, str]) -> list[str]:
    candidates = derive_pdf_candidates(
        pdf_url=row.get("pdf_url", ""),
        arxiv_id=row.get("arxiv_id", ""),
        openreview_forum_id=row.get("openreview_forum_id", ""),
        doi=row.get("doi", ""),
        paper_link=row.get("paper_link", ""),
    )
    source_text_url = (row.get("source_text_url") or "").strip()
    if source_text_url and _looks_like_pdf_url(source_text_url) and source_text_url not in candidates:
        candidates.append(source_text_url)
    return _dedupe(candidates)


def _looks_like_pdf_url(url: str) -> bool:
    lowered = url.lower()
    return lowered.endswith(".pdf") or "/pdf/" in lowered or "arxiv.org/pdf/" in lowered or "openreview.net/pdf" in lowered


def _grade_sort_key(row: dict[str, Any]) -> int:
    return {"S": 0, "A": 1, "B": 2, "C": 3}.get(str(row.get("candidate_grade", "")).upper(), 4)


def _source_availability_score(row: dict[str, Any]) -> float:
    score = 0.0
    if row.get("source_text_status") in {"pdf_available", "preprint_available"}:
        score += 2.0
    if row.get("pdf_url"):
        score += 1.0
    if row.get("arxiv_id"):
        score += 1.0
    if row.get("openreview_forum_id"):
        score += 0.5
    if row.get("doi"):
        score += 0.25
    return score


def _auto_select_subdirection(
    roi_rows: list[dict[str, str]],
    candidates: list[dict[str, str]],
    research_spec: dict[str, Any],
) -> str:
    terms = _intent_terms(research_spec)
    rows_by_subdir: dict[str, list[dict[str, str]]] = {}
    for row in candidates:
        rows_by_subdir.setdefault(row.get("subdirection_id", ""), []).append(row)

    def score(row: dict[str, str]) -> tuple[float, float, float, int, str]:
        sid = row.get("subdirection_id", "")
        subdir_candidates = rows_by_subdir.get(sid, [])
        text = " ".join(
            [
                sid,
                row.get("label", ""),
                row.get("representative_papers", ""),
                " ".join(
                    " ".join(
                        [
                            candidate.get("title", ""),
                            candidate.get("abstract_raw", ""),
                            candidate.get("query_roles", ""),
                            candidate.get("rough_positive_signal", ""),
                        ]
                    )
                    for candidate in subdir_candidates
                ),
            ]
        ).lower()
        intent_score = sum(weight for term, weight in terms.items() if term in text)
        grade_score = sum(_to_float(candidate.get("candidate_grade_score", "0")) for candidate in subdir_candidates[:10])
        embedding_score = sum(_to_float(candidate.get("best_embedding_score", "0")) for candidate in subdir_candidates[:10])
        return (intent_score, grade_score, embedding_score, len(subdir_candidates), sid)

    return max(roi_rows, key=score).get("subdirection_id", roi_rows[0].get("subdirection_id", ""))


def _intent_terms(research_spec: dict[str, Any]) -> dict[str, float]:
    raw = " ".join(
        str(research_spec.get(key, ""))
        for key in ("raw_intent", "problem_anchor", "research_question", "target_venue")
    ).lower()
    weighted = {"benchmark": 2.0, "dataset": 2.0, "baseline": 2.0, "metric": 2.0, "efficient": 1.5, "runtime": 1.5}
    terms = {term: weight for term, weight in weighted.items() if term in raw}
    for token in re.split(r"[^a-z0-9+-]+", raw):
        if len(token) >= 4 and token not in {"target", "venue", "compute", "budget", "timeline", "weeks"}:
            terms.setdefault(token, 0.5)
    return terms or {"general": 0.5}


def _reader_tags_from_disk_sources(sources: list[dict[str, Any]]) -> list[str]:
    return _dedupe([tag for source in sources if (tag := _reader_tag(source["source_type"]))])


def _reader_tag(source_type: str) -> str:
    return {
        "arxiv_tex": "tex",
        "official_pdf_text": "pdf",
        "mineru_markdown": "md",
        "manual_source": "md",
    }.get(source_type, "")


def _find_paper_dir(source_roots: list[Path], paper_id: str) -> Path | None:
    safe = _safe_id(paper_id)
    for root in source_roots:
        for name in (safe, paper_id):
            candidate = root / name
            if candidate.exists() and candidate.is_dir():
                return candidate
    return None


def _readable_sources(paper_dir: Path) -> list[dict[str, Any]]:
    specs = (
        ("paper.tex", "arxiv_tex", "paper_source", "arxiv-to-prompt cache"),
        ("paper.pdftxt", "official_pdf_text", "pdf_text", "pymupdf text layer cache"),
        ("paper.md", "mineru_markdown", "mineru_markdown", "mineru markdown cache"),
        ("manual.md", "manual_source", "manual", "manual supplied source"),
    )
    out = []
    for filename, source_type, source_kind, parser in specs:
        path = paper_dir / filename
        if path.exists() and path.stat().st_size > 0:
            out.append({"path": path, "source_type": source_type, "source_kind": source_kind, "parser": parser})
    return out


def _ranked_passages(text: str) -> list[dict[str, Any]]:
    passages: list[dict[str, Any]] = []
    for match in re.finditer(r"[^.\n][^.\n]{40,500}(?:[.\n]|$)", text):
        raw = re.sub(r"\s+", " ", match.group(0)).strip()
        if len(raw) < 40:
            continue
        score = sum(1 for term in EVIDENCE_TERMS if term in raw.lower())
        if score <= 0:
            continue
        passages.append({"text": raw[:900], "start": match.start(), "end": match.end(), "score": score})
    passages.sort(key=lambda item: (-item["score"], item["start"]))
    return passages


def _missing_source_record(row: dict[str, str], paper_dir: Path | None, *, abstract_fallback: bool = False) -> dict[str, Any]:
    return {
        "paper_id": row.get("paper_id", ""),
        "title": row.get("title", ""),
        "category": "no_cached_readable_source",
        "abstract_fallback_used": abstract_fallback,
        "paper_dir": str(paper_dir) if paper_dir else "",
        "source_text_status": row.get("source_text_status", ""),
        "source_text_url": row.get("source_text_url", ""),
        "hint": "Run legal general web search, Stage 5.5 source fetch, or provide an approved cached source before stronger evidence extraction.",
    }


def _web_search_replenishment_record(record: dict[str, Any], cache_dir: Path) -> dict[str, Any]:
    title = str(record.get("title", "")).strip()
    paper_id = str(record.get("paper_id", "")).strip()
    doi = _diagnostic_recovered_doi(record)
    quoted_title = f'"{title}"' if title else f'"{paper_id}"'
    base_terms = [quoted_title, "paper", "pdf"]
    if doi:
        base_terms.append(doi)
    queries = [
        " ".join(base_terms),
        f"{quoted_title} project page",
        f"{quoted_title} arXiv OR OpenReview OR GitHub",
        f"{quoted_title} author PDF",
    ]
    if doi:
        queries.append(f"{doi} PDF")
    return {
        "paper_id": paper_id,
        "title": title,
        "paper_dir": record.get("paper_dir", ""),
        "cache_dir": str(cache_dir / str(record.get("paper_dir", ""))),
        "recovered_doi": doi,
        "search_queries": _dedup_strings([query for query in queries if query.strip()]),
        "acceptable_sources": [
            "official project page",
            "publisher landing page with open PDF",
            "arXiv or OpenReview page",
            "author/institutional PDF or preprint",
            "GitHub/release page containing paper text or official PDF link",
        ],
        "cache_instructions": [
            "If a legal public PDF is found, place it at paper.pdf and extract text to paper.pdftxt.",
            "If only legal public HTML/markdown text is found, convert it to paper.md.",
            "Record source URL provenance in the executor report before rerunning build-pack.",
        ],
        "disallowed_sources": [
            "Sci-Hub unless explicitly approved by the user",
            "paywalled PDFs without public access rights",
            "abstract-only snippets as strong evidence",
        ],
    }


def _diagnostic_recovered_doi(record: dict[str, Any]) -> str:
    errors = record.get("errors", {})
    if not isinstance(errors, dict):
        return ""
    fallback = errors.get("pdf_fallback", {})
    if not isinstance(fallback, dict):
        return ""
    oa_api = fallback.get("oa_api", {})
    if not isinstance(oa_api, dict):
        return ""
    return str(oa_api.get("recovered_doi", "") or "").strip()


def _dedup_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _unextractable_source_record(row: dict[str, str], paper_dir: Path | None) -> dict[str, Any]:
    return {
        "paper_id": row.get("paper_id", ""),
        "title": row.get("title", ""),
        "category": "no_extractable_cached_source_span",
        "abstract_fallback_used": False,
        "paper_dir": str(paper_dir) if paper_dir else "",
        "source_text_status": row.get("source_text_status", ""),
        "source_text_url": row.get("source_text_url", ""),
        "hint": "Cached source existed, but deterministic Phase 3 extraction found no evidence-bearing passage.",
    }


def _missing_pdf_record(row: dict[str, str], paper_dir: Path | None) -> dict[str, Any]:
    return {
        "paper_id": row.get("paper_id", ""),
        "title": row.get("title", ""),
        "category": "no_cached_pdf_text_layer",
        "paper_dir": str(paper_dir) if paper_dir else "",
        "source_text_status": row.get("source_text_status", ""),
        "hint": "PDF text is absent from cache; existing TeX or MinerU cache may still support weak evidence if present.",
    }


def _claim_text(row: dict[str, str], span: dict[str, Any]) -> str:
    title = row.get("title", row.get("paper_id", "paper"))
    text = span.get("text", "")
    relation = _relation(text)
    if span.get("source_type") == "accepted_index":
        if relation == "motivates":
            return f"{title} abstract reports a limitation or cost signal relevant to targeted gap analysis."
        if relation == "supports":
            return f"{title} abstract reports a benchmark or evaluation signal relevant to this subdirection."
        return f"{title} abstract provides contextual metadata evidence for this subdirection."
    if relation == "motivates":
        return f"{title} reports a limitation or cost signal relevant to targeted gap analysis."
    if relation == "supports":
        return f"{title} reports a benchmark or evaluation signal relevant to this subdirection."
    return f"{title} contains contextual full-text evidence for this subdirection."


def _interpretation(relation: str, selected: dict[str, Any]) -> str:
    if relation == "motivates":
        return f"The span can motivate a gap candidate within {selected['label']}, but it is not an idea."
    if relation == "supports":
        return f"The span supports field mapping for {selected['label']} under Phase 3 evidence limits."
    return f"The span provides context for {selected['label']} and should not be promoted directly."


def _card_limitations(span: dict[str, Any]) -> list[str]:
    limitations = [
        "Deterministic Phase 3 extraction; no LLM semantic adjudication was applied.",
        "Card supports gap mapping only, not final idea generation.",
    ]
    if span.get("source_type") == "accepted_index":
        limitations.append(
            "This card uses accepted_index abstract metadata because cached readable full text was unavailable."
        )
    return limitations


def _relation(text: str) -> str:
    lowered = text.lower()
    if _has_any(lowered, ("limitation", "limited", "lack", "missing", "cost", "compute", "fails")):
        return "motivates"
    if _has_any(lowered, ("benchmark", "evaluation", "dataset", "baseline", "improve", "outperform")):
        return "supports"
    return "context"


def _span_type(text: str) -> str:
    if _has_any(text.lower(), ("benchmark", "evaluation", "dataset", "baseline")):
        return "benchmark"
    return "full_text"


def _section_name(text: str, start: int) -> str:
    prefix = text[:start]
    headings = re.findall(r"(?im)^\s*(?:#+\s*)?([A-Z][A-Za-z0-9 ,:/-]{2,80})\s*$", prefix[-4000:])
    if headings:
        return headings[-1].strip()
    return "full_text"


def _source_weight(value: str) -> str:
    value = (value or "").strip()
    if value in {"unknown", "not_applicable", "primary", "secondary", "tertiary", "weak"}:
        return value
    return "unknown"


def _gap_description(gap_type: str, selected: dict[str, Any]) -> str:
    if gap_type == "evidence_tension":
        return f"Evidence suggests unresolved limitations or failure cases inside {selected['label']} that need source-backed characterization."
    if gap_type == "method_transfer":
        return f"Evidence suggests an implementation or reproducibility gap inside {selected['label']} that may affect reuse."
    if gap_type == "benchmark_protocol_gap":
        return (
            f"Evidence suggests a benchmark/protocol gap inside {selected['label']}: baselines, datasets, metrics, and "
            "ablation contracts must be explicit before a strong research claim is credible."
        )
    if gap_type == "resource_arbitrage":
        return f"Evidence suggests a resource or compute-cost constraint inside {selected['label']}."
    return f"Evidence suggests benchmark leverage or blind-spot structure inside {selected['label']}."


def _safe_id(paper_id: str) -> str:
    return paper_id.replace("/", "__").replace(":", "_")


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _split_signal(value: str) -> list[str]:
    return _dedupe([part for part in re.split(r"[|,]+", value or "") if part and part != "unknown"])


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                rows.append(json.loads(raw))
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _to_int(value: str) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def _to_float(value: str) -> float:
    try:
        return float(value or 0.0)
    except ValueError:
        return 0.0
