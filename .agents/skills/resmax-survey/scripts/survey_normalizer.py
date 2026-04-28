from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "0.1.0"
PRODUCER = {"name": "resmax-survey.normalizer", "version": SCHEMA_VERSION}
DEFAULT_TOP_K = 5
MAX_TOP_K = 10
DIRS = ("inputs", "normalized", "audit", "retrieval", "sources", "assets", "downstream", "validation")
JSONL_INPUTS = ("seed_claims.jsonl", "seed_gaps.jsonl", "seed_ideas.jsonl")
PAPER_INPUT_NAMES = ("seed_papers.csv", "seed_papers.jsonl", "seed_papers.md")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "paper",
    "papers",
    "study",
    "that",
    "the",
    "this",
    "to",
    "using",
    "with",
}
METRIC_TERMS = (
    "accuracy",
    "auroc",
    "auc",
    "bleu",
    "cer",
    "dice",
    "f1",
    "fid",
    "latency",
    "mae",
    "map",
    "miou",
    "mse",
    "precision",
    "psnr",
    "recall",
    "rmse",
    "rouge",
    "runtime",
    "ssim",
    "throughput",
    "wer",
)
ASSET_TYPES = (
    "dataset",
    "benchmark",
    "baseline",
    "metric",
    "base_model",
    "backbone",
    "codebase",
    "task",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Normalize external survey inputs into Resmax survey artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run-all", help="Run the normalizer-first survey path.")
    run.add_argument("--topic", required=True, help="Topic slug or short topic label.")
    run.add_argument("--out-dir", type=Path, default=None, help="Output directory. Defaults to literature_research/<topic>.")
    run.add_argument("--input-dir", type=Path, default=None, help="Directory containing canonical seed files.")
    run.add_argument("--external-report", type=Path, default=None, help="Path to external_report.md.")
    run.add_argument("--seed-papers", type=Path, action="append", default=[], help="Path to seed_papers.csv/jsonl/md. May repeat.")
    run.add_argument("--seed-claims", type=Path, default=None, help="Path to seed_claims.jsonl.")
    run.add_argument("--seed-gaps", type=Path, default=None, help="Path to seed_gaps.jsonl.")
    run.add_argument("--seed-ideas", type=Path, default=None, help="Path to seed_ideas.jsonl.")
    run.add_argument("--accepted", type=Path, default=Path("paper_database/accepted_index.csv"), help="accepted_index.csv.")
    run.add_argument("--embedding-cache", type=Path, default=None, help="Optional embedding cache path for status recording.")
    run.add_argument("--reviews-dir", type=Path, default=Path("paper_database/reviews"), help="Optional review cache directory.")
    run.add_argument("--source-cache", type=Path, default=Path("paper_database/source_cache"), help="Optional source cache directory.")
    run.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="Per-target retrieval cap.")
    run.add_argument("--max-local-omissions", type=int, default=10, help="Bounded local omission cap.")
    run.add_argument("--mode", choices=["production", "smoke", "test", "dev"], default="production")

    validate = subparsers.add_parser("validate", help="Validate an already normalized survey directory.")
    validate.add_argument("--dir", required=True, type=Path, help="literature_research/<topic> directory.")

    args = parser.parse_args(argv)
    if args.command == "run-all":
        result = run_all(args)
        print(f"[survey-normalizer] wrote {result['out_dir']}")
        print(f"[survey-normalizer] validation_status={result['validation_status']}")
        return 0 if result["validation_status"] == "PASS" else 1
    if args.command == "validate":
        from validate_normalized_survey import validate_survey

        report = validate_survey(args.dir, write_reports=True)
        print(f"[survey-normalizer] validation_status={report['status']}")
        return 0 if report["status"] == "PASS" else 1
    return 2


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    topic = _safe_slug(args.topic)
    out_dir = (args.out_dir or Path("literature_research") / topic).resolve()
    top_k = max(1, min(int(args.top_k), MAX_TOP_K))
    _prepare_layout(out_dir)

    input_manifest, copied_inputs = _materialize_inputs(args, out_dir)
    accepted = _load_accepted_index(args.accepted)
    normalized = _normalize_inputs(out_dir, copied_inputs)
    audit = _audit_papers(out_dir, normalized["papers"], accepted)
    retrieval = _run_retrieval(out_dir, args.topic, normalized, accepted, audit, top_k, int(args.max_local_omissions))
    sources = _write_sources(out_dir, accepted, audit, retrieval, args.source_cache)
    assets = _write_assets(out_dir, normalized, accepted, audit, retrieval, sources)
    downstream = _write_downstream(out_dir, args.topic, assets, audit, retrieval)
    hashes = _artifact_hashes(out_dir)
    manifest = _write_manifest(
        out_dir=out_dir,
        topic=args.topic,
        input_manifest=input_manifest,
        accepted=accepted,
        args=args,
        assets=assets,
        retrieval=retrieval,
        sources=sources,
        downstream=downstream,
        hashes=hashes,
        validation_status="NOT_RUN",
    )
    report_path = _write_survey_report(out_dir, args.topic, manifest, audit, retrieval, assets, downstream)
    manifest["artifacts"]["survey_report"] = _rel(out_dir, report_path)
    manifest["hashes"] = _artifact_hashes(out_dir)
    _write_json(out_dir / "manifest.json", manifest)

    from validate_normalized_survey import validate_survey

    validation = validate_survey(out_dir, write_reports=True)
    manifest["validation_status"] = validation["status"]
    manifest["artifacts"]["validation_report_json"] = "validation/validation_report.json"
    manifest["artifacts"]["validation_report_md"] = "validation/validation_report.md"
    manifest["hashes"] = _artifact_hashes(out_dir)
    _write_json(out_dir / "manifest.json", manifest)
    return {"out_dir": str(out_dir), "validation_status": validation["status"]}


def _prepare_layout(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for dirname in DIRS:
        (out_dir / dirname).mkdir(parents=True, exist_ok=True)
    (out_dir / "downstream" / "research_pack_compat").mkdir(parents=True, exist_ok=True)


def _materialize_inputs(args: argparse.Namespace, out_dir: Path) -> tuple[dict[str, Any], dict[str, list[Path]]]:
    inputs_dir = out_dir / "inputs"
    copied: dict[str, list[Path]] = defaultdict(list)

    external = args.external_report or _input_dir_path(args.input_dir, "external_report.md")
    if external and external.exists():
        copied["external_report"].append(_copy_input(external, inputs_dir / "external_report.md"))
    else:
        _write_text(inputs_dir / "external_report.md", "")

    paper_sources = list(args.seed_papers)
    if args.input_dir:
        paper_sources.extend(path for name in PAPER_INPUT_NAMES if (path := args.input_dir / name).exists())
    seen_paper_names: set[str] = set()
    for source in paper_sources:
        if not source.exists():
            continue
        dst_name = source.name if source.name in PAPER_INPUT_NAMES else f"seed_papers{source.suffix.lower()}"
        if dst_name in seen_paper_names:
            dst_name = f"seed_papers_{stable_id('input', str(source))}{source.suffix.lower()}"
        seen_paper_names.add(dst_name)
        copied["seed_papers"].append(_copy_input(source, inputs_dir / dst_name))
    for name in PAPER_INPUT_NAMES:
        path = inputs_dir / name
        if not path.exists():
            _write_text(path, "" if name != "seed_papers.csv" else "title,authors,venue,year,url,doi,arxiv_id,openreview_forum_id,notes\n")

    for key, arg_name, filename in (
        ("seed_claims", "seed_claims", "seed_claims.jsonl"),
        ("seed_gaps", "seed_gaps", "seed_gaps.jsonl"),
        ("seed_ideas", "seed_ideas", "seed_ideas.jsonl"),
    ):
        src = getattr(args, arg_name) or _input_dir_path(args.input_dir, filename)
        dst = inputs_dir / filename
        if src and src.exists():
            copied[key].append(_copy_input(src, dst))
        else:
            _write_text(dst, "")
        copied.setdefault(key, []).append(dst)

    records = []
    for path in sorted(inputs_dir.iterdir()):
        if path.is_file():
            records.append(
                {
                    "name": path.name,
                    "path": _rel(out_dir, path),
                    "provided": bool(path.read_text(encoding="utf-8", errors="ignore").strip()),
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
            )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "inputs": records,
        "trust_boundary": "external inputs are candidate material, not verified facts",
    }
    _write_json(inputs_dir / "input_manifest.json", manifest)
    return manifest, copied


def _normalize_inputs(out_dir: Path, copied_inputs: dict[str, list[Path]]) -> dict[str, Any]:
    normalized_dir = out_dir / "normalized"
    provenance: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []

    papers = _parse_seed_papers(out_dir, provenance, parse_errors)
    claims = _parse_seed_jsonl(out_dir, "seed_claims", "claim", provenance, parse_errors)
    gaps = _parse_seed_jsonl(out_dir, "seed_gaps", "gap", provenance, parse_errors)
    ideas = _parse_seed_jsonl(out_dir, "seed_ideas", "idea", provenance, parse_errors)
    external = _parse_external_report(out_dir, provenance)
    claims.extend(external["claims"])
    gaps.extend(external["gaps"])
    ideas.extend(external["ideas"])

    _write_jsonl(normalized_dir / "seed_papers.normalized.jsonl", papers)
    _write_jsonl(normalized_dir / "seed_claims.normalized.jsonl", claims)
    _write_jsonl(normalized_dir / "seed_gaps.normalized.jsonl", gaps)
    _write_jsonl(normalized_dir / "seed_ideas.normalized.jsonl", ideas)
    _write_jsonl(normalized_dir / "provenance_spans.jsonl", provenance)
    _write_jsonl(normalized_dir / "parse_errors.jsonl", parse_errors)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "paper_count": len(papers),
        "claim_count": len(claims),
        "gap_count": len(gaps),
        "idea_count": len(ideas),
        "parse_error_count": len(parse_errors),
        "trust_boundary": {
            "external_report": "candidate claims only",
            "seed_files": "candidate records only",
            "verified_fact_source": "accepted_index metadata or materialized source evidence",
        },
    }
    _write_json(normalized_dir / "normalized_inputs.json", summary)
    return {"papers": papers, "claims": claims, "gaps": gaps, "ideas": ideas, "summary": summary, "provenance": provenance}


def _parse_seed_papers(out_dir: Path, provenance: list[dict[str, Any]], parse_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    inputs_dir = out_dir / "inputs"
    records: list[dict[str, Any]] = []
    for path in (inputs_dir / name for name in PAPER_INPUT_NAMES):
        if not path.exists() or not path.read_text(encoding="utf-8", errors="ignore").strip():
            continue
        if path.suffix.lower() == ".csv":
            records.extend(_parse_seed_paper_csv(out_dir, path, provenance, parse_errors))
        elif path.suffix.lower() == ".jsonl":
            records.extend(_parse_seed_paper_jsonl(out_dir, path, provenance, parse_errors))
        elif path.suffix.lower() == ".md":
            records.extend(_parse_seed_paper_md(out_dir, path, provenance, parse_errors))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = record.get("doi") or record.get("arxiv_id") or normalize_title(record.get("canonical_title", ""))
        if key in seen:
            record["normalization_status"] = "duplicate_seed"
            record["drop_reason"] = "duplicate normalized title or identifier"
            deduped.append(record)
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _parse_seed_paper_csv(
    out_dir: Path,
    path: Path,
    provenance: list[dict[str, Any]],
    parse_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for line_no, row in enumerate(reader, start=2):
            title = _first(row, "canonical_title", "title", "paper_title")
            if not title:
                parse_errors.append(_parse_error(path, line_no, "seed_paper_missing_title", row))
                continue
            records.append(_paper_record(out_dir, path, line_no, row, title, provenance))
    return records


def _parse_seed_paper_jsonl(
    out_dir: Path,
    path: Path,
    provenance: list[dict[str, Any]],
    parse_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for line_no, payload, error in _iter_jsonl(path):
        if error:
            parse_errors.append(_parse_error(path, line_no, error, {}))
            continue
        row = payload if isinstance(payload, dict) else {"title": str(payload)}
        title = _first(row, "canonical_title", "title", "paper_title")
        if not title:
            parse_errors.append(_parse_error(path, line_no, "seed_paper_missing_title", row))
            continue
        records.append(_paper_record(out_dir, path, line_no, row, title, provenance))
    return records


def _parse_seed_paper_md(
    out_dir: Path,
    path: Path,
    provenance: list[dict[str, Any]],
    parse_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        clean = line.strip()
        if not clean or not clean.startswith(("-", "*")):
            continue
        body = clean.lstrip("-* ").strip()
        year = _extract_year(body)
        title = re.sub(r"\s*\(?20\d{2}\)?.*$", "", body).strip(" -:;")
        title = re.sub(r"\[[^\]]+\]\(([^)]+)\)", "", title).strip() or body
        if not title:
            parse_errors.append(_parse_error(path, line_no, "seed_paper_missing_title", {"line": line}))
            continue
        records.append(_paper_record(out_dir, path, line_no, {"title": title, "year": year, "notes": body}, title, provenance))
    return records


def _paper_record(
    out_dir: Path,
    path: Path,
    line_no: int,
    row: dict[str, Any],
    title: str,
    provenance: list[dict[str, Any]],
) -> dict[str, Any]:
    span_id = _provenance_span(out_dir, path, line_no, line_no, json.dumps(row, ensure_ascii=False), "paper", provenance)
    seed_id = stable_id("seed_paper", {"title": title, "line": line_no, "path": path.name})
    return {
        "schema_version": SCHEMA_VERSION,
        "seed_id": seed_id,
        "paper_id": row.get("paper_id", ""),
        "canonical_title": title.strip(),
        "authors": _split_authors(str(_first(row, "authors", "author") or "")),
        "venue": str(_first(row, "venue", "conf", "conference") or "").strip(),
        "year": str(_first(row, "year", "publication_year") or _extract_year(json.dumps(row, ensure_ascii=False))).strip(),
        "url": str(_first(row, "url", "paper_url", "paper_link", "landing_url", "pdf_url") or "").strip(),
        "doi": str(_first(row, "doi") or "").strip(),
        "arxiv_id": str(_first(row, "arxiv_id", "arxiv") or "").strip(),
        "openreview_forum_id": str(_first(row, "openreview_forum_id", "forum_id") or "").strip(),
        "notes": str(_first(row, "notes", "summary", "abstract", "abstract_raw") or "").strip(),
        "origin": "seed_papers",
        "status": "external_candidate",
        "normalization_status": "normalized",
        "provenance_span_ids": [span_id],
    }


def _parse_seed_jsonl(
    out_dir: Path,
    basename: str,
    target_type: str,
    provenance: list[dict[str, Any]],
    parse_errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    path = out_dir / "inputs" / f"{basename}.jsonl"
    records: list[dict[str, Any]] = []
    if not path.exists() or not path.read_text(encoding="utf-8", errors="ignore").strip():
        return records
    for line_no, payload, error in _iter_jsonl(path):
        if error:
            parse_errors.append(_parse_error(path, line_no, error, {}))
            continue
        row = payload if isinstance(payload, dict) else {"text": str(payload)}
        text = str(_first(row, "text", "claim", "gap", "idea", "description", "summary") or "").strip()
        if not text:
            parse_errors.append(_parse_error(path, line_no, f"{target_type}_missing_text", row))
            continue
        target_id = str(_first(row, f"{target_type}_id", "id") or stable_id(target_type, {"text": text, "path": path.name, "line": line_no}))
        span_id = _provenance_span(out_dir, path, line_no, line_no, text, target_type, provenance, target_id=target_id)
        records.append(
            {
                "schema_version": SCHEMA_VERSION,
                f"{target_type}_id": target_id,
                "text": text,
                "origin": basename,
                "status": "external_claim" if target_type == "claim" else "external_candidate",
                "paper_ids": _as_list(row.get("paper_ids") or row.get("papers") or []),
                "evidence_ids": [],
                "confidence": _to_float_or_default(row.get("confidence"), 0.4),
                "provenance_span_ids": [span_id],
                "raw": row,
            }
        )
    return records


def _parse_external_report(out_dir: Path, provenance: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    path = out_dir / "inputs" / "external_report.md"
    text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    claims: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    ideas: list[dict[str, Any]] = []
    if not text.strip():
        return {"claims": claims, "gaps": gaps, "ideas": ideas}
    lines = text.splitlines()
    for line_no, line in enumerate(lines, start=1):
        clean = line.strip().lstrip("-* ").strip()
        if not clean:
            continue
        kind = ""
        body = clean
        match = re.match(r"(?i)^(claim|finding|gap|limitation|idea|opportunity)\s*[:：]\s*(.+)$", clean)
        if match:
            label = match.group(1).lower()
            body = match.group(2).strip()
            if label in {"claim", "finding"}:
                kind = "claim"
            elif label in {"gap", "limitation"}:
                kind = "gap"
            elif label in {"idea", "opportunity"}:
                kind = "idea"
        if not kind:
            continue
        target_id = stable_id(kind, {"text": body, "path": path.name, "line": line_no})
        span_id = _provenance_span(out_dir, path, line_no, line_no, body, kind, provenance, target_id=target_id)
        record = {
            "schema_version": SCHEMA_VERSION,
            f"{kind}_id": target_id,
            "text": body,
            "origin": "external_report_extracted",
            "status": "external_claim" if kind == "claim" else "external_candidate",
            "paper_ids": [],
            "evidence_ids": [],
            "confidence": 0.35,
            "provenance_span_ids": [span_id],
            "raw": {"line": clean},
        }
        if kind == "claim":
            claims.append(record)
        elif kind == "gap":
            gaps.append(record)
        else:
            ideas.append(record)
    _provenance_span(out_dir, path, 1, max(1, len(lines)), _snippet(text), "external_report", provenance)
    return {"claims": claims, "gaps": gaps, "ideas": ideas}


def _audit_papers(out_dir: Path, seed_papers: list[dict[str, Any]], accepted: dict[str, Any]) -> dict[str, Any]:
    audit_dir = out_dir / "audit"
    rows: list[dict[str, Any]] = []
    identity_records: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    external_only: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen_local: set[str] = set()
    seen_seed_keys: set[str] = set()
    for seed in seed_papers:
        seed_key = seed.get("doi") or seed.get("arxiv_id") or normalize_title(seed.get("canonical_title", ""))
        if seed_key and seed_key in seen_seed_keys:
            record = _audit_row(seed, {}, "dropped", "duplicate_seed_record", "drop", 0.0)
            rows.append(record)
            dropped.append({"seed_id": seed["seed_id"], "reason": "duplicate_seed_record", "canonical_title": seed["canonical_title"]})
            continue
        if seed_key:
            seen_seed_keys.add(seed_key)
        match, method, confidence = _match_seed_to_accepted(seed, accepted)
        if match and match.get("paper_id") not in seen_local:
            seen_local.add(match.get("paper_id", ""))
            record = _audit_row(seed, match, "verified_local", f"matched accepted_index by {method}", "keep", confidence)
            rows.append(record)
            verified.append(_paper_summary(match, seed))
            identity_records.append(_identity_record(seed, match, method, confidence, record["audit_status"]))
        elif match:
            record = _audit_row(seed, match, "dropped", "duplicate_local_match", "drop", confidence)
            rows.append(record)
            dropped.append({"seed_id": seed["seed_id"], "reason": "duplicate_local_match", "canonical_title": seed["canonical_title"]})
            identity_records.append(_identity_record(seed, match, method, confidence, record["audit_status"]))
        elif len(tokenize(seed.get("canonical_title", ""))) < 3:
            record = _audit_row(seed, {}, "uncertain", "insufficient_title_for_identity_check", "uncertain", 0.1)
            rows.append(record)
            uncertain.append({"seed_id": seed["seed_id"], "reason": record["reason"], "canonical_title": seed["canonical_title"]})
        else:
            record = _audit_row(seed, {}, "external_only", "not_found_in_accepted_index", "add", 0.3)
            rows.append(record)
            external_only.append(seed)
    fieldnames = [
        "seed_id",
        "canonical_title",
        "audit_status",
        "action",
        "reason",
        "local_paper_id",
        "match_method",
        "confidence",
        "venue",
        "year",
        "source_status",
    ]
    _write_csv(audit_dir / "paper_audit.csv", rows, fieldnames)
    _write_jsonl(audit_dir / "paper_identity_map.jsonl", identity_records)
    _write_jsonl(audit_dir / "verified_paper_set.jsonl", verified)
    _write_jsonl(audit_dir / "external_only_papers.jsonl", external_only)
    _write_jsonl(audit_dir / "uncertain_papers.jsonl", uncertain)
    _write_jsonl(audit_dir / "dropped_papers.jsonl", dropped)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "seed_paper_count": len(seed_papers),
        "verified_local_count": len(verified),
        "external_only_count": len(external_only),
        "uncertain_count": len(uncertain),
        "dropped_count": len(dropped),
        "accepted_index_count": accepted["count"],
        "accepted_index_path": str(accepted["path"]) if accepted.get("path") else "",
    }
    _write_json(audit_dir / "audit_summary.json", summary)
    return {
        "rows": rows,
        "verified": verified,
        "external_only": external_only,
        "uncertain": uncertain,
        "dropped": dropped,
        "identity": identity_records,
        "summary": summary,
    }


def _run_retrieval(
    out_dir: Path,
    topic: str,
    normalized: dict[str, Any],
    accepted: dict[str, Any],
    audit: dict[str, Any],
    top_k: int,
    max_local_omissions: int,
) -> dict[str, Any]:
    retrieval_dir = out_dir / "retrieval"
    requests: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    closest: list[dict[str, Any]] = []
    falsification: list[dict[str, Any]] = []
    infra_results: list[dict[str, Any]] = []
    followups: list[dict[str, Any]] = []
    verified_ids = {row.get("paper_id", "") for row in audit["verified"]}
    rows = accepted["rows"]

    for seed in normalized["papers"]:
        request, trace, candidates = _retrieval_request(
            rows=rows,
            target_type="paper",
            target_id=seed["seed_id"],
            purpose="seed-list verifier",
            query=seed.get("canonical_title", ""),
            retrieval_mode="seed-list verifier",
            top_k=min(top_k, 5),
        )
        requests.append(request)
        traces.append(trace)
        closest.extend(_candidate_records(candidates, request, target_kind="paper_identity", evidence_ids=[]))

    omission_text = _combined_target_text(topic, normalized)
    request, trace, candidates = _retrieval_request(
        rows=rows,
        target_type="topic",
        target_id=_safe_slug(topic),
        purpose="local omission checker",
        query=omission_text,
        retrieval_mode="local omission checker",
        top_k=min(max_local_omissions, MAX_TOP_K),
        drop_ids=verified_ids,
    )
    requests.append(request)
    traces.append(trace)
    omission_records = _candidate_records(candidates, request, target_kind="local_omission", evidence_ids=[])
    closest.extend(omission_records)
    for record in omission_records:
        falsification.append(
            _falsification_record(
                target_type="topic",
                target_id=_safe_slug(topic),
                check_type="local_omission_checker",
                status="possible_omission",
                closest_work_ids=[record["paper_id"]],
                trace_id=record["trace_id"],
                reason="Accepted-index candidate overlaps external survey terms but was not in the verified seed list.",
            )
        )

    for target_type, items in (("claim", normalized["claims"]), ("gap", normalized["gaps"]), ("idea", normalized["ideas"])):
        for item in items:
            target_id = item[f"{target_type}_id"]
            request, trace, candidates = _retrieval_request(
                rows=rows,
                target_type=target_type,
                target_id=target_id,
                purpose="closest-work search",
                query=item["text"],
                retrieval_mode="closest-work search",
                top_k=top_k,
            )
            requests.append(request)
            traces.append(trace)
            candidate_records = _candidate_records(candidates, request, target_kind=target_type, evidence_ids=[])
            closest.extend(candidate_records)
            mode = "claim falsifier" if target_type == "claim" else "gap falsifier" if target_type == "gap" else "closest-work search"
            status = _falsification_status(candidate_records, target_type)
            falsification.append(
                _falsification_record(
                    target_type=target_type,
                    target_id=target_id,
                    check_type=mode,
                    status=status,
                    closest_work_ids=[row["paper_id"] for row in candidate_records[:3]],
                    trace_id=request["trace_id"],
                    reason=_falsification_reason(status, target_type),
                )
            )

    asset_queries = _asset_queries(normalized)
    for asset_type, names in asset_queries.items():
        for name in sorted(names)[:20]:
            request, trace, candidates = _retrieval_request(
                rows=rows,
                target_type="asset",
                target_id=stable_id("asset", {"type": asset_type, "name": name}),
                purpose="infra search",
                query=name,
                retrieval_mode="infra search",
                top_k=min(top_k, 5),
            )
            requests.append(request)
            traces.append(trace)
            infra_results.append(
                {
                    "query_id": request["request_id"],
                    "target_type": "asset",
                    "target_id": request["target_id"],
                    "asset_type": asset_type,
                    "normalized_name": name,
                    "retrieval_mode": "infra search",
                    "candidate_paper_ids": [row["paper_id"] for row in candidates],
                    "trace_id": request["trace_id"],
                }
            )

    for row in audit["external_only"] + audit["uncertain"]:
        followups.append(
            {
                "query_id": stable_id("followup_query", row),
                "target_type": "paper",
                "target_id": row.get("seed_id", ""),
                "purpose": "follow-up query suggester",
                "query": f'"{row.get("canonical_title", "")}" accepted paper official source',
                "reason": "paper identity was not verified against accepted_index",
                "status": "suggested",
            }
        )
    for check in falsification:
        if check["status"] in {"not_falsified_locally", "insufficient_local_evidence"}:
            followups.append(
                {
                    "query_id": stable_id("followup_query", check),
                    "target_type": check["target_type"],
                    "target_id": check["target_id"],
                    "purpose": "follow-up query suggester",
                    "query": f"{check['target_type']} {check['target_id']} closest accepted work verification",
                    "reason": check["reason"],
                    "status": "suggested",
                }
            )

    _write_jsonl(retrieval_dir / "retrieval_requests.jsonl", requests)
    _write_jsonl(retrieval_dir / "retrieval_trace.jsonl", traces)
    _write_jsonl(retrieval_dir / "closest_work_candidates.jsonl", closest)
    _write_jsonl(retrieval_dir / "falsification_checks.jsonl", falsification)
    _write_jsonl(retrieval_dir / "infra_search_results.jsonl", infra_results)
    _write_jsonl(retrieval_dir / "followup_queries.jsonl", followups)
    return {
        "requests": requests,
        "traces": traces,
        "closest": closest,
        "falsification": falsification,
        "infra": infra_results,
        "followups": followups,
        "modes": sorted({request["retrieval_mode"] for request in requests}),
        "top_k": top_k,
    }


def _write_sources(
    out_dir: Path,
    accepted: dict[str, Any],
    audit: dict[str, Any],
    retrieval: dict[str, Any],
    source_cache: Path | None,
) -> dict[str, Any]:
    source_dir = out_dir / "sources"
    paper_ids = {row.get("paper_id", "") for row in audit["verified"]}
    paper_ids.update(row.get("paper_id", "") for row in retrieval["closest"][:50])
    rows_by_id = accepted["by_paper_id"]
    manifest: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for paper_id in sorted(pid for pid in paper_ids if pid):
        row = rows_by_id.get(paper_id, {})
        status = _source_status(row)
        record = {
            "source_id": stable_id("source", {"paper_id": paper_id, "status": status}),
            "paper_id": paper_id,
            "canonical_title": row.get("title", ""),
            "source_status": status,
            "metadata_path": str(accepted.get("path") or ""),
            "source_type": row.get("source_type", "") or "accepted_index",
            "pdf_url": row.get("pdf_url", ""),
            "source_text_status": row.get("source_text_status", ""),
            "source_cache_hint": str((source_cache or Path("paper_database/source_cache")) / _safe_slug(paper_id)),
            "materialized": False,
            "policy": "metadata verifies identity only; content-level claims require materialized source evidence",
        }
        manifest.append(record)
        if status not in {"readable_source_available", "pdf_available", "metadata_with_source_anchor"}:
            missing.append(
                {
                    "missing_id": stable_id("missing_source", {"paper_id": paper_id}),
                    "paper_id": paper_id,
                    "scope": "source_materialization",
                    "reason": "no cached readable source evidence was confirmed by the normalizer",
                    "required_for": ["method", "limitation", "dataset", "benchmark", "metric", "baseline", "protocol", "cost", "failure_case"],
                    "allowed_degradation": "metadata-only identity verification",
                    "status": "open",
                }
            )
    report = {
        "schema_version": SCHEMA_VERSION,
        "policy": {
            "coverage_target": "critical_claim_and_asset_evidence",
            "metadata_only_allowed_for": ["paper existence", "title", "authors", "venue", "year", "accepted status"],
            "source_required_for": [
                "method contribution",
                "limitation",
                "dataset",
                "benchmark",
                "metric",
                "baseline comparison",
                "experimental protocol",
                "ablation",
                "compute or cost",
                "failure case",
                "reviewer concern",
            ],
        },
        "source_manifest_count": len(manifest),
        "missing_source_count": len(missing),
        "degraded_mode": bool(missing),
    }
    _write_jsonl(source_dir / "source_manifest.jsonl", manifest)
    _write_json(source_dir / "source_materialization_report.json", report)
    _write_jsonl(source_dir / "missing_sources.jsonl", missing)
    return {"manifest": manifest, "missing": missing, "report": report}


def _write_assets(
    out_dir: Path,
    normalized: dict[str, Any],
    accepted: dict[str, Any],
    audit: dict[str, Any],
    retrieval: dict[str, Any],
    sources: dict[str, Any],
) -> dict[str, Any]:
    assets_dir = out_dir / "assets"
    evidence_cards: list[dict[str, Any]] = []
    evidence_by_target: dict[tuple[str, str], list[str]] = defaultdict(list)

    for paper in audit["verified"]:
        row = accepted["by_paper_id"].get(paper.get("paper_id", ""), {})
        evidence = _evidence_card(
            paper_id=paper.get("paper_id", ""),
            source_id=stable_id("source", {"paper_id": paper.get("paper_id", ""), "status": _source_status(row)}),
            source_type="accepted_index",
            locator=f"accepted_index:{paper.get('paper_id', '')}",
            target_id=paper.get("paper_id", ""),
            target_type="paper",
            evidence_kind="metadata_identity",
            support_relation="verifies_metadata",
            content_summary=f"accepted_index contains accepted paper metadata for {paper.get('title', '')}",
            confidence=0.9,
            extraction_method="deterministic_metadata_match",
            provenance={"accepted_index": str(accepted.get("path") or "")},
        )
        evidence_cards.append(evidence)
        evidence_by_target[("paper", paper.get("paper_id", ""))].append(evidence["evidence_id"])

    for target_type, items in (("claim", normalized["claims"]), ("gap", normalized["gaps"]), ("idea", normalized["ideas"])):
        for item in items:
            target_id = item[f"{target_type}_id"]
            evidence = _evidence_card(
                paper_id="",
                source_id=item.get("provenance_span_ids", [""])[0],
                source_type=item.get("origin", "seed_input"),
                locator=";".join(item.get("provenance_span_ids", [])),
                target_id=target_id,
                target_type=target_type,
                evidence_kind="external_assertion",
                support_relation="asserts_external",
                content_summary=_snippet(item.get("text", ""), 240),
                confidence=float(item.get("confidence") or 0.35),
                extraction_method="deterministic_seed_parse",
                provenance={"provenance_span_ids": item.get("provenance_span_ids", [])},
            )
            evidence_cards.append(evidence)
            evidence_by_target[(target_type, target_id)].append(evidence["evidence_id"])

    paper_assets, asset_mentions = _paper_assets(out_dir, accepted, audit, retrieval, sources, evidence_by_target)
    missing_evidence = _missing_evidence(normalized, audit, retrieval, sources, paper_assets, evidence_by_target)
    claim_graph = _claim_graph(normalized["claims"], retrieval, evidence_by_target)
    gap_map = _gap_map(normalized["gaps"], retrieval, evidence_by_target, missing_evidence)
    asset_stats = _asset_stats(asset_mentions, paper_assets)
    falsification_summary = _falsification_summary(retrieval["falsification"])

    _write_jsonl(assets_dir / "paper_assets.jsonl", paper_assets)
    _write_jsonl(assets_dir / "asset_mentions.jsonl", asset_mentions)
    _write_jsonl(assets_dir / "evidence_cards.jsonl", evidence_cards)
    _write_json(assets_dir / "claim_graph.json", claim_graph)
    _write_jsonl(assets_dir / "gap_map.jsonl", gap_map)
    _write_csv(assets_dir / "asset_stats.csv", asset_stats, _asset_stats_fields())
    _write_csv(assets_dir / "falsification_summary.csv", falsification_summary, ["target_type", "target_id", "check_type", "status", "closest_work_ids", "trace_id", "reason"])
    _write_jsonl(assets_dir / "missing_evidence.jsonl", missing_evidence)
    return {
        "paper_assets": paper_assets,
        "asset_mentions": asset_mentions,
        "evidence_cards": evidence_cards,
        "claim_graph": claim_graph,
        "gap_map": gap_map,
        "asset_stats": asset_stats,
        "missing_evidence": missing_evidence,
        "falsification_summary": falsification_summary,
    }


def _paper_assets(
    out_dir: Path,
    accepted: dict[str, Any],
    audit: dict[str, Any],
    retrieval: dict[str, Any],
    sources: dict[str, Any],
    evidence_by_target: dict[tuple[str, str], list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows_by_id = accepted["by_paper_id"]
    source_by_paper = {row["paper_id"]: row for row in sources["manifest"]}
    paper_ids: list[str] = []
    verified_by_id = {row.get("paper_id", ""): row for row in audit["verified"]}
    for row in audit["verified"]:
        paper_ids.append(row.get("paper_id", ""))
    for row in retrieval["closest"]:
        paper_ids.append(row.get("paper_id", ""))
    paper_ids = _dedupe([pid for pid in paper_ids if pid])
    assets: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []
    for paper_id in paper_ids:
        row = rows_by_id.get(paper_id, {})
        verified_seed = verified_by_id.get(paper_id, {})
        text = " ".join(
            [
                row.get("title", ""),
                row.get("abstract_raw", ""),
                row.get("keywords_raw", ""),
                verified_seed.get("seed_notes", ""),
            ]
        )
        extracted = _extract_assets_from_text(text)
        source_status = source_by_paper.get(paper_id, {}).get("source_status", "metadata_only")
        missing_fields = [
            field
            for field in (
                "tasks",
                "method_types",
                "datasets",
                "benchmarks",
                "metrics",
                "baselines",
                "experimental_protocols",
                "compute_cost",
                "limitations",
                "failure_cases",
                "reviewer_signals",
            )
            if not extracted.get(field) and field not in {"compute_cost", "limitations", "failure_cases", "reviewer_signals"}
        ]
        if source_status in {"metadata_only", "missing"}:
            missing_fields.extend(["limitations", "failure_cases", "experimental_protocols", "compute_cost", "reviewer_signals"])
        evidence_ids = evidence_by_target.get(("paper", paper_id), [])
        asset = {
            "paper_id": paper_id,
            "canonical_title": row.get("title", ""),
            "audit_status": "verified_local" if paper_id in {item.get("paper_id", "") for item in audit["verified"]} else "closest_work_candidate",
            "venue": row.get("venue", ""),
            "year": row.get("year", ""),
            "source_status": source_status,
            "tasks": extracted["tasks"],
            "problem_settings": extracted["problem_settings"],
            "method_types": extracted["method_types"],
            "base_models": extracted["base_models"],
            "backbones": extracted["backbones"],
            "datasets": extracted["datasets"],
            "benchmarks": extracted["benchmarks"],
            "metrics": extracted["metrics"],
            "baselines": extracted["baselines"],
            "experimental_protocols": extracted["experimental_protocols"],
            "ablations": extracted["ablations"],
            "compute_cost": extracted["compute_cost"],
            "data_cost": extracted["data_cost"],
            "annotation_cost": extracted["annotation_cost"],
            "code_availability": _code_availability(row),
            "data_availability": _data_availability(row),
            "claimed_contributions": extracted["claimed_contributions"],
            "limitations": extracted["limitations"],
            "failure_cases": extracted["failure_cases"],
            "reviewer_signals": [],
            "reuse_opportunities": _reuse_opportunities(row, extracted),
            "implementation_barriers": _implementation_barriers(row, extracted, source_status),
            "missing_fields": _dedupe(missing_fields),
            "evidence_card_ids": evidence_ids,
            "confidence": 0.65 if source_status != "metadata_only" else 0.45,
            "provenance": {"source": "accepted_index_metadata", "content_fields_require_source_evidence": True},
        }
        assets.append(asset)
        for asset_type in ASSET_TYPES:
            field = _asset_field(asset_type)
            for name in asset.get(field, []):
                mention = {
                    "mention_id": stable_id("asset_mention", {"paper_id": paper_id, "type": asset_type, "name": name}),
                    "paper_id": paper_id,
                    "asset_type": asset_type,
                    "normalized_name": normalize_asset_name(name),
                    "surface_form": name,
                    "role": _asset_role(asset_type),
                    "evidence_card_id": evidence_ids[0] if evidence_ids else "",
                    "confidence": asset["confidence"],
                    "source_span": "",
                    "provenance": {"source": "accepted_index_title_abstract_keywords"},
                }
                mentions.append(mention)
    return assets, mentions


def _missing_evidence(
    normalized: dict[str, Any],
    audit: dict[str, Any],
    retrieval: dict[str, Any],
    sources: dict[str, Any],
    paper_assets: list[dict[str, Any]],
    evidence_by_target: dict[tuple[str, str], list[str]],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for source in sources["missing"]:
        missing.append(
            {
                "missing_id": source["missing_id"],
                "scope": "paper_source",
                "target_id": source["paper_id"],
                "field": "readable_source",
                "reason": source["reason"],
                "required_for": source["required_for"],
                "severity": "blocking_for_content_claims",
                "allowed_degradation": source["allowed_degradation"],
                "suggested_action": "materialize legal public PDF, TeX, OpenReview, or official full text",
                "status": source["status"],
            }
        )
    for row in audit["external_only"]:
        missing.append(
            {
                "missing_id": stable_id("missing", {"paper": row.get("seed_id", "")}),
                "scope": "paper_identity",
                "target_id": row.get("seed_id", ""),
                "field": "accepted_index_match",
                "reason": "seed paper was not verified in accepted_index",
                "required_for": ["verified_paper_set", "downstream_ready"],
                "severity": "blocking_for_verified_fact",
                "allowed_degradation": "external_only paper may remain as unverified context",
                "suggested_action": "provide DOI/OpenReview/arXiv or add accepted whitelist evidence",
                "status": "open",
            }
        )
    closest_by_target: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in retrieval["closest"]:
        closest_by_target[(row["target_type"], row["target_id"])].append(row)
    for target_type, items in (("claim", normalized["claims"]), ("gap", normalized["gaps"]), ("idea", normalized["ideas"])):
        for item in items:
            target_id = item[f"{target_type}_id"]
            if not closest_by_target.get((target_type, target_id)):
                missing.append(
                    {
                        "missing_id": stable_id("missing", {"target_type": target_type, "target_id": target_id, "field": "closest_work"}),
                        "scope": f"{target_type}_falsification",
                        "target_id": target_id,
                        "field": "closest_work_trace",
                        "reason": "no accepted-index candidate overlapped the target strongly enough",
                        "required_for": ["novelty_risk", "downstream_ready"],
                        "severity": "blocking" if target_type in {"gap", "idea"} else "warning",
                        "allowed_degradation": "generate follow-up query and keep target out of review-ready downstream generation",
                        "suggested_action": "run external search or provide additional seed papers",
                        "status": "open",
                    }
                )
            if target_type == "claim" and not evidence_by_target.get((target_type, target_id)):
                missing.append(
                    {
                        "missing_id": stable_id("missing", {"target_type": target_type, "target_id": target_id, "field": "source_evidence"}),
                        "scope": "critical_claim",
                        "target_id": target_id,
                        "field": "source_evidence",
                        "reason": "claim has no materialized paper/source evidence",
                        "required_for": ["verified_fact"],
                        "severity": "blocking_for_verified_fact",
                        "allowed_degradation": "external claim only",
                        "suggested_action": "attach source locator or readable paper evidence",
                        "status": "open",
                    }
                )
    for asset in paper_assets:
        for field in asset.get("missing_fields", []):
            missing.append(
                {
                    "missing_id": stable_id("missing", {"paper_id": asset["paper_id"], "field": field}),
                    "scope": "paper_asset",
                    "target_id": asset["paper_id"],
                    "field": field,
                    "reason": "field was not extractable from deterministic metadata or available source evidence",
                    "required_for": ["asset_completeness"],
                    "severity": "warning",
                    "allowed_degradation": "leave field empty and lower confidence",
                    "suggested_action": "materialize source and run content extraction",
                    "status": "open",
                }
            )
    return _dedupe_by_key(missing, "missing_id")


def _claim_graph(
    claims: list[dict[str, Any]],
    retrieval: dict[str, Any],
    evidence_by_target: dict[tuple[str, str], list[str]],
) -> dict[str, Any]:
    counter_by_target: dict[str, list[str]] = defaultdict(list)
    for check in retrieval["falsification"]:
        if check["target_type"] == "claim" and check["status"] in {"potentially_overstrong", "needs_human_review"}:
            counter_by_target[check["target_id"]].extend(check["closest_work_ids"])
    claim_rows = []
    for claim in claims:
        claim_id = claim["claim_id"]
        evidence_ids = evidence_by_target.get(("claim", claim_id), [])
        claim_rows.append(
            {
                "claim_id": claim_id,
                "text": claim["text"],
                "claim_type": _claim_type(claim["text"]),
                "origin": claim.get("origin", ""),
                "status": "external_claim_needs_verification",
                "paper_ids": claim.get("paper_ids", []),
                "evidence_ids": evidence_ids,
                "counter_evidence_ids": [],
                "counter_work_ids": _dedupe(counter_by_target.get(claim_id, [])),
                "confidence": min(float(claim.get("confidence") or 0.35), 0.5),
            }
        )
    edges = []
    for claim in claim_rows:
        if claim["counter_work_ids"]:
            edges.append({"source": claim["claim_id"], "target": claim["counter_work_ids"][0], "relation": "falsification_candidate"})
    return {"schema_version": SCHEMA_VERSION, "claims": claim_rows, "edges": edges}


def _gap_map(
    gaps: list[dict[str, Any]],
    retrieval: dict[str, Any],
    evidence_by_target: dict[tuple[str, str], list[str]],
    missing_evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    closest_by_gap: dict[str, list[dict[str, Any]]] = defaultdict(list)
    status_by_gap: dict[str, str] = {}
    for row in retrieval["closest"]:
        if row["target_type"] == "gap":
            closest_by_gap[row["target_id"]].append(row)
    for check in retrieval["falsification"]:
        if check["target_type"] == "gap":
            status_by_gap[check["target_id"]] = check["status"]
    blocking_missing = {row["target_id"] for row in missing_evidence if row["severity"] == "blocking" and row["field"] == "closest_work_trace"}
    gap_rows = []
    for gap in gaps:
        gap_id = gap["gap_id"]
        closest = closest_by_gap.get(gap_id, [])
        missing_ids = [row["missing_id"] for row in missing_evidence if row["target_id"] == gap_id]
        gap_rows.append(
            {
                "gap_id": gap_id,
                "text": gap["text"],
                "origin": gap.get("origin", ""),
                "related_claim_ids": _as_list(gap.get("related_claim_ids", [])),
                "supporting_evidence_ids": evidence_by_target.get(("gap", gap_id), []),
                "falsification_status": status_by_gap.get(gap_id, "not_checked"),
                "closest_work_ids": [row["paper_id"] for row in closest[:5]],
                "infra_dependencies": _asset_names_from_text(gap["text"]),
                "implementation_constraints": _implementation_constraints(gap["text"]),
                "reviewer_blockers": _reviewer_blockers(gap["text"], bool(closest)),
                "confidence": min(float(gap.get("confidence") or 0.35), 0.5),
                "missing_evidence_ids": missing_ids,
                "downstream_ready": bool(closest) and gap_id not in blocking_missing,
            }
        )
    return gap_rows


def _asset_stats(asset_mentions: list[dict[str, Any]], paper_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_asset: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    papers_by_id = {asset["paper_id"]: asset for asset in paper_assets}
    for mention in asset_mentions:
        by_asset[(mention["asset_type"], mention["normalized_name"])].append(mention)
    rows = []
    for (asset_type, name), mentions in sorted(by_asset.items()):
        paper_ids = sorted({mention["paper_id"] for mention in mentions})
        papers = [papers_by_id.get(pid, {}) for pid in paper_ids]
        rows.append(
            {
                "asset_type": asset_type,
                "normalized_name": name,
                "count_papers": str(len(paper_ids)),
                "verified_count": str(sum(1 for paper in papers if paper.get("audit_status") == "verified_local")),
                "venues": "|".join(_dedupe([paper.get("venue", "") for paper in papers if paper.get("venue")])),
                "years": "|".join(_dedupe([paper.get("year", "") for paper in papers if paper.get("year")])),
                "representative_papers": "|".join(paper_ids[:5]),
                "evidence_count": str(sum(1 for mention in mentions if mention.get("evidence_card_id"))),
                "confidence": f"{sum(float(m.get('confidence') or 0.0) for m in mentions) / max(1, len(mentions)):.2f}",
                "notes": "metadata-derived; source evidence required before verified use",
            }
        )
    if not rows:
        rows.append({field: "" for field in _asset_stats_fields()})
    return rows


def _write_downstream(
    out_dir: Path,
    topic: str,
    assets: dict[str, Any],
    audit: dict[str, Any],
    retrieval: dict[str, Any],
) -> dict[str, Any]:
    downstream_dir = out_dir / "downstream"
    blocking_missing = [
        row
        for row in assets["missing_evidence"]
        if row["severity"] in {"blocking", "blocking_for_verified_fact", "blocking_for_content_claims"}
    ]
    seed_opportunities = [
        {
            "gap_id": gap["gap_id"],
            "text": gap["text"],
            "downstream_ready": gap["downstream_ready"],
            "closest_work_ids": gap["closest_work_ids"],
            "missing_evidence_ids": gap["missing_evidence_ids"],
        }
        for gap in assets["gap_map"]
    ]
    contract = {
        "schema_version": SCHEMA_VERSION,
        "topic": topic,
        "verified_paper_set_path": "audit/verified_paper_set.jsonl",
        "claim_graph_path": "assets/claim_graph.json",
        "gap_map_path": "assets/gap_map.jsonl",
        "closest_work_candidates_path": "retrieval/closest_work_candidates.jsonl",
        "paper_assets_path": "assets/paper_assets.jsonl",
        "asset_stats_path": "assets/asset_stats.csv",
        "evidence_cards_path": "assets/evidence_cards.jsonl",
        "missing_evidence_path": "assets/missing_evidence.jsonl",
        "implementation_constraints": _contract_constraints(assets["gap_map"], assets["paper_assets"]),
        "reviewer_blocker_hints": _contract_blockers(assets["gap_map"], blocking_missing),
        "seed_opportunities": seed_opportunities,
        "warnings": [
            "external claims are not verified facts",
            "blocking missing evidence prevents downstream_ready",
            "gaps without closest-work candidates must not enter review-ready idea generation",
        ],
        "provenance_summary": {
            "verified_local_papers": len(audit["verified"]),
            "external_only_papers": len(audit["external_only"]),
            "retrieval_trace_count": len(retrieval["traces"]),
        },
        "validation_status": "pending",
    }
    _write_json(downstream_dir / "survey_contract.json", contract)

    compat = downstream_dir / "research_pack_compat"
    _write_json(
        compat / "manifest.json",
        {
            "schema_version": SCHEMA_VERSION,
            "producer": "resmax-survey.normalizer.compat",
            "source_contract": "../survey_contract.json",
            "artifacts": [
                "evidence_cards.jsonl",
                "claim_graph.json",
                "gap_map.json",
                "closest_work_candidates.jsonl",
                "missing_evidence.jsonl",
            ],
        },
    )
    shutil.copyfile(out_dir / "assets" / "evidence_cards.jsonl", compat / "evidence_cards.jsonl")
    shutil.copyfile(out_dir / "assets" / "claim_graph.json", compat / "claim_graph.json")
    _write_json(compat / "gap_map.json", {"schema_version": SCHEMA_VERSION, "gaps": assets["gap_map"]})
    shutil.copyfile(out_dir / "retrieval" / "closest_work_candidates.jsonl", compat / "closest_work_candidates.jsonl")
    shutil.copyfile(out_dir / "assets" / "missing_evidence.jsonl", compat / "missing_evidence.jsonl")
    return {"contract": contract, "blocking_missing_count": len(blocking_missing)}


def _write_manifest(
    *,
    out_dir: Path,
    topic: str,
    input_manifest: dict[str, Any],
    accepted: dict[str, Any],
    args: argparse.Namespace,
    assets: dict[str, Any],
    retrieval: dict[str, Any],
    sources: dict[str, Any],
    downstream: dict[str, Any],
    hashes: dict[str, str],
    validation_status: str,
) -> dict[str, Any]:
    artifacts = {
        "survey_report": "survey_report.md",
        "input_manifest": "inputs/input_manifest.json",
        "normalized_inputs": "normalized/normalized_inputs.json",
        "paper_audit": "audit/paper_audit.csv",
        "retrieval_requests": "retrieval/retrieval_requests.jsonl",
        "retrieval_trace": "retrieval/retrieval_trace.jsonl",
        "closest_work_candidates": "retrieval/closest_work_candidates.jsonl",
        "falsification_checks": "retrieval/falsification_checks.jsonl",
        "source_manifest": "sources/source_manifest.jsonl",
        "paper_assets": "assets/paper_assets.jsonl",
        "asset_mentions": "assets/asset_mentions.jsonl",
        "evidence_cards": "assets/evidence_cards.jsonl",
        "claim_graph": "assets/claim_graph.json",
        "gap_map": "assets/gap_map.jsonl",
        "missing_evidence": "assets/missing_evidence.jsonl",
        "survey_contract": "downstream/survey_contract.json",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": stable_id("survey_normalizer_run", {"topic": topic, "created_at": utc_now()}),
        "created_at": utc_now(),
        "topic": topic,
        "producer": PRODUCER,
        "inputs": input_manifest["inputs"],
        "artifacts": artifacts,
        "hashes": hashes,
        "database_snapshot": {
            "accepted_index_path": str(accepted.get("path") or ""),
            "accepted_index_sha256": accepted.get("sha256", ""),
            "paper_count": accepted.get("count", 0),
            "role": "accepted-paper whitelist and falsification base",
        },
        "embedding_cache_status": _path_status(args.embedding_cache, role="optional closest-work acceleration"),
        "review_cache_status": _path_status(args.reviews_dir, role="optional reviewer blocker evidence"),
        "source_cache_status": _path_status(args.source_cache, role="optional critical evidence materialization"),
        "coverage_summary": {
            "paper_assets": len(assets["paper_assets"]),
            "evidence_cards": len(assets["evidence_cards"]),
            "missing_evidence": len(assets["missing_evidence"]),
            "claim_count": len(assets["claim_graph"]["claims"]),
            "gap_count": len(assets["gap_map"]),
        },
        "retrieval_modes_run": retrieval["modes"],
        "source_coverage": sources["report"],
        "provenance_summary": {
            "input_count": len(input_manifest["inputs"]),
            "external_inputs_are_verified_facts": False,
        },
        "degradation_summary": {
            "accepted_index_available": bool(accepted.get("path")),
            "embedding_degraded_to_keyword": args.embedding_cache is None or not Path(args.embedding_cache).exists(),
            "source_missing_count": sources["report"]["missing_source_count"],
            "blocking_missing_count": downstream["blocking_missing_count"],
        },
        "validation_status": validation_status,
        "downstream_contract_path": "downstream/survey_contract.json",
    }


def _write_survey_report(
    out_dir: Path,
    topic: str,
    manifest: dict[str, Any],
    audit: dict[str, Any],
    retrieval: dict[str, Any],
    assets: dict[str, Any],
    downstream: dict[str, Any],
) -> Path:
    path = out_dir / "survey_report.md"
    top_assets = [row for row in assets["asset_stats"] if row.get("normalized_name")]
    top_closest = retrieval["closest"][:10]
    ready_gaps = [gap for gap in assets["gap_map"] if gap["downstream_ready"]]
    blocked_gaps = [gap for gap in assets["gap_map"] if not gap["downstream_ready"]]
    hashes = manifest.get("hashes", {})
    lines = [
        f"# Survey Normalization Report: {topic}",
        "",
        "This is the only human-facing main report for this run. JSON, JSONL, and CSV files are the source of truth.",
        "",
        "## 1. Executive summary",
        "",
        f"- Verified local papers: {audit['summary']['verified_local_count']}",
        f"- External-only papers: {audit['summary']['external_only_count']}",
        f"- Uncertain papers: {audit['summary']['uncertain_count']}",
        f"- Dropped papers: {audit['summary']['dropped_count']}",
        f"- Claims normalized: {len(assets['claim_graph']['claims'])}",
        f"- Gaps normalized: {len(assets['gap_map'])}",
        f"- Blocking or content-critical missing evidence records: {downstream['blocking_missing_count']}",
        "",
        "## 2. Input sources and trust boundary",
        "",
        "- External reports and seed files are treated as candidate material.",
        "- accepted_index metadata can verify paper identity, venue, year, and local whitelist status.",
        "- Method, limitation, dataset, benchmark, metric, baseline, protocol, cost, failure case, and reviewer concern statements require source evidence before they become verified facts.",
        "",
        "## 3. Paper audit summary",
        "",
        "- Audit table: [audit/paper_audit.csv](audit/paper_audit.csv)",
        "- Identity map: [audit/paper_identity_map.jsonl](audit/paper_identity_map.jsonl)",
        "- Verified set: [audit/verified_paper_set.jsonl](audit/verified_paper_set.jsonl)",
        "- External-only set: [audit/external_only_papers.jsonl](audit/external_only_papers.jsonl)",
        "- Uncertain set: [audit/uncertain_papers.jsonl](audit/uncertain_papers.jsonl)",
        "- Dropped set: [audit/dropped_papers.jsonl](audit/dropped_papers.jsonl)",
        "",
        "## 4. Verified / external-only / uncertain / dropped papers",
        "",
    ]
    lines.extend(_paper_audit_lines(audit))
    lines.extend(
        [
            "",
            "## 5. Key paper layers",
            "",
            "Paper-level assets are normalized in [assets/paper_assets.jsonl](assets/paper_assets.jsonl). Content fields remain low-confidence when no readable source is available.",
            "",
            "## 6. Infrastructure profile",
            "",
            "Mention-level assets are in [assets/asset_mentions.jsonl](assets/asset_mentions.jsonl); aggregate counts are in [assets/asset_stats.csv](assets/asset_stats.csv).",
            "",
            "## 7. High-frequency datasets / benchmarks / baselines / metrics / base models",
            "",
        ]
    )
    if top_assets:
        for row in top_assets[:12]:
            lines.append(
                f"- {row['asset_type']}: `{row['normalized_name']}` in {row['count_papers']} paper(s), evidence_count={row['evidence_count']}, confidence={row['confidence']}"
            )
    else:
        lines.append("- No reusable infrastructure asset reached the deterministic extraction threshold.")
    lines.extend(
        [
            "",
            "## 8. Claim graph summary",
            "",
            f"- Claim graph: [assets/claim_graph.json](assets/claim_graph.json)",
            "- All normalized claims remain `external_claim_needs_verification` unless backed by accepted metadata or materialized source evidence.",
            "",
            "## 9. Gap map summary",
            "",
            f"- Gap map: [assets/gap_map.jsonl](assets/gap_map.jsonl)",
            f"- Downstream-ready gaps: {len(ready_gaps)}",
            f"- Blocked gaps: {len(blocked_gaps)}",
            "",
            "## 10. Closest-work / novelty-risk summary",
            "",
            "- Retrieval is bounded falsification, not open-domain discovery.",
            "- Closest-work candidates: [retrieval/closest_work_candidates.jsonl](retrieval/closest_work_candidates.jsonl)",
            "- Falsification checks: [retrieval/falsification_checks.jsonl](retrieval/falsification_checks.jsonl)",
            "",
        ]
    )
    for row in top_closest:
        lines.append(
            f"- {row['target_type']} `{row['target_id']}` -> `{row['paper_id']}` rank={row['rank']} score={row['score']:.3f} risk={row['novelty_risk']}"
        )
    lines.extend(
        [
            "",
            "## 11. Missing evidence",
            "",
            f"- Missing evidence records: [assets/missing_evidence.jsonl](assets/missing_evidence.jsonl)",
            f"- Missing source records: [sources/missing_sources.jsonl](sources/missing_sources.jsonl)",
            "",
            "## 12. Low-cost opportunities",
            "",
        ]
    )
    for opportunity in downstream["contract"]["seed_opportunities"][:8]:
        lines.append(
            f"- `{opportunity['gap_id']}` downstream_ready={opportunity['downstream_ready']} closest={','.join(opportunity['closest_work_ids']) or 'none'}"
        )
    if not downstream["contract"]["seed_opportunities"]:
        lines.append("- No gap is downstream-ready; resolve missing evidence or provide more seeds.")
    lines.extend(
        [
            "",
            "## 13. Reviewer blocker hints",
            "",
        ]
    )
    for blocker in downstream["contract"]["reviewer_blocker_hints"][:12]:
        lines.append(f"- {blocker}")
    lines.extend(
        [
            "",
            "## 14. Downstream handoff boundary for resmax-idea",
            "",
            "- `resmax-idea` should read [downstream/survey_contract.json](downstream/survey_contract.json).",
            "- Blocking missing evidence prevents review-ready idea generation.",
            "- The handoff distinguishes verified local metadata, external claims, model/deterministic inference, and missing evidence.",
            "",
            "## 15. Artifact index with paths and hashes",
            "",
        ]
    )
    for rel_path in sorted(hashes):
        lines.append(f"- `{rel_path}` sha256={hashes[rel_path]}")
    _write_text(path, "\n".join(lines) + "\n")
    return path


def _load_accepted_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": None, "sha256": "", "count": 0, "rows": [], "by_paper_id": {}, "by_title": {}, "by_doi": {}, "by_arxiv": {}, "by_openreview": {}}
    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    by_paper_id = {row.get("paper_id", ""): row for row in rows if row.get("paper_id")}
    by_title = defaultdict(list)
    by_doi = {}
    by_arxiv = {}
    by_openreview = {}
    for row in rows:
        title_key = normalize_title(row.get("title", ""))
        if title_key:
            by_title[title_key].append(row)
        if row.get("doi"):
            by_doi[normalize_identifier(row["doi"])] = row
        if row.get("arxiv_id"):
            by_arxiv[normalize_identifier(row["arxiv_id"])] = row
        if row.get("openreview_forum_id"):
            by_openreview[normalize_identifier(row["openreview_forum_id"])] = row
    return {
        "path": path,
        "sha256": sha256_file(path),
        "count": len(rows),
        "rows": rows,
        "by_paper_id": by_paper_id,
        "by_title": dict(by_title),
        "by_doi": by_doi,
        "by_arxiv": by_arxiv,
        "by_openreview": by_openreview,
    }


def _match_seed_to_accepted(seed: dict[str, Any], accepted: dict[str, Any]) -> tuple[dict[str, str] | None, str, float]:
    if not accepted["rows"]:
        return None, "accepted_index_unavailable", 0.0
    if seed.get("paper_id") and seed["paper_id"] in accepted["by_paper_id"]:
        return accepted["by_paper_id"][seed["paper_id"]], "paper_id", 1.0
    for field, index_name in (("doi", "by_doi"), ("arxiv_id", "by_arxiv"), ("openreview_forum_id", "by_openreview")):
        value = normalize_identifier(seed.get(field, ""))
        if value and value in accepted[index_name]:
            return accepted[index_name][value], field, 0.98
    title_key = normalize_title(seed.get("canonical_title", ""))
    if title_key and title_key in accepted["by_title"]:
        return accepted["by_title"][title_key][0], "exact_title", 0.95
    best = _best_title_match(seed.get("canonical_title", ""), accepted["rows"])
    if best and best[1] >= 0.9:
        return best[0], "high_confidence_title_overlap", best[1]
    return None, "no_match", 0.0


def _retrieval_request(
    *,
    rows: list[dict[str, str]],
    target_type: str,
    target_id: str,
    purpose: str,
    query: str,
    retrieval_mode: str,
    top_k: int,
    drop_ids: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    trace_id = stable_id("retrieval_trace", {"target_type": target_type, "target_id": target_id, "purpose": purpose, "query": query})
    request_id = stable_id("retrieval_request", {"trace_id": trace_id})
    candidates = _search_rows(rows, query, top_k=top_k, drop_ids=drop_ids or set())
    request = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "trace_id": trace_id,
        "target_type": target_type,
        "target_id": target_id,
        "purpose": purpose,
        "query": query,
        "retrieval_mode": retrieval_mode,
        "top_k": top_k,
        "candidate_list": [row["paper_id"] for row in candidates],
        "created_at": utc_now(),
    }
    trace = {
        "schema_version": SCHEMA_VERSION,
        "trace_id": trace_id,
        "request_id": request_id,
        "target_type": target_type,
        "target_id": target_id,
        "purpose": purpose,
        "query": query,
        "retrieval_mode": retrieval_mode,
        "candidate_list": [
            {
                "paper_id": row["paper_id"],
                "rank": row["rank"],
                "score": row["score"],
                "ranking_reason": row["ranking_reason"],
                "drop_reason": row["drop_reason"],
            }
            for row in candidates
        ],
        "bounded": True,
    }
    return request, trace, candidates


def _search_rows(rows: list[dict[str, str]], query: str, *, top_k: int, drop_ids: set[str]) -> list[dict[str, Any]]:
    query_tokens = tokenize(query)
    scored = []
    for row in rows:
        paper_id = row.get("paper_id", "")
        if paper_id in drop_ids:
            continue
        text = " ".join([row.get("title", ""), row.get("abstract_raw", ""), row.get("keywords_raw", "")])
        score, reasons, dimensions = _score_text(query_tokens, query, text, row)
        if score <= 0:
            continue
        scored.append((score, row.get("year", ""), row.get("title", ""), row, reasons, dimensions))
    scored.sort(key=lambda item: (-item[0], -_int(item[1]), item[2], item[3].get("paper_id", "")))
    candidates = []
    for rank, (score, _year, _title, row, reasons, dimensions) in enumerate(scored[:top_k], start=1):
        candidates.append(
            {
                "paper_id": row.get("paper_id", ""),
                "title": row.get("title", ""),
                "venue": row.get("venue", ""),
                "year": row.get("year", ""),
                "score": round(score, 6),
                "rank": rank,
                "match_reasons": reasons,
                "overlap_dimensions": dimensions,
                "ranking_reason": "; ".join(reasons) or "token overlap",
                "drop_reason": "",
            }
        )
    return candidates


def _candidate_records(candidates: list[dict[str, Any]], request: dict[str, Any], *, target_kind: str, evidence_ids: list[str]) -> list[dict[str, Any]]:
    records = []
    for row in candidates:
        risk = "high" if row["score"] >= 0.45 else "medium" if row["score"] >= 0.2 else "low"
        records.append(
            {
                "candidate_id": stable_id("closest_work_candidate", {"request_id": request["request_id"], "paper_id": row["paper_id"]}),
                "query_id": request["request_id"],
                "target_type": request["target_type"],
                "target_id": request["target_id"],
                "paper_id": row["paper_id"],
                "rank": row["rank"],
                "retrieval_mode": request["retrieval_mode"],
                "score": row["score"],
                "match_reasons": row["match_reasons"],
                "overlap_dimensions": row["overlap_dimensions"],
                "novelty_risk": risk,
                "relation_to_target": target_kind,
                "drop_reason": row.get("drop_reason", ""),
                "evidence_ids": evidence_ids,
                "trace_id": request["trace_id"],
                "confidence": min(0.85, 0.35 + row["score"]),
            }
        )
    return records


def _score_text(query_tokens: list[str], query: str, text: str, row: dict[str, str]) -> tuple[float, list[str], list[str]]:
    text_tokens = set(tokenize(text))
    q_tokens = set(query_tokens)
    overlap = q_tokens & text_tokens
    if not q_tokens:
        return 0.0, [], []
    title_tokens = set(tokenize(row.get("title", "")))
    title_overlap = q_tokens & title_tokens
    score = len(overlap) / math.sqrt(max(1, len(q_tokens)))
    score += 0.25 * len(title_overlap)
    if normalize_title(query) and normalize_title(query) == normalize_title(row.get("title", "")):
        score += 5.0
    reasons = []
    if title_overlap:
        reasons.append("title_overlap:" + ",".join(sorted(title_overlap)[:6]))
    if overlap:
        reasons.append("text_overlap:" + ",".join(sorted(overlap)[:8]))
    if row.get("venue"):
        reasons.append(f"accepted_venue:{row['venue']}")
    dimensions = []
    lowered = text.lower()
    for term, dimension in (
        ("dataset", "dataset"),
        ("benchmark", "benchmark"),
        ("baseline", "baseline"),
        ("metric", "metric"),
        ("code", "implementation"),
        ("cost", "cost"),
        ("limitation", "limitation"),
    ):
        if term in lowered:
            dimensions.append(dimension)
    return score, reasons, _dedupe(dimensions)


def _candidate_file_target_map(retrieval: dict[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    out: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in retrieval["closest"]:
        out[(row["target_type"], row["target_id"])].append(row)
    return out


def _falsification_record(
    *,
    target_type: str,
    target_id: str,
    check_type: str,
    status: str,
    closest_work_ids: list[str],
    trace_id: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "check_id": stable_id("falsification_check", {"target_type": target_type, "target_id": target_id, "type": check_type}),
        "target_type": target_type,
        "target_id": target_id,
        "check_type": check_type,
        "status": status,
        "closest_work_ids": closest_work_ids,
        "trace_id": trace_id,
        "reason": reason,
        "confidence": 0.65 if closest_work_ids else 0.35,
    }


def _falsification_status(candidate_records: list[dict[str, Any]], target_type: str) -> str:
    if not candidate_records:
        return "not_falsified_locally" if target_type in {"claim", "gap"} else "insufficient_local_evidence"
    best = float(candidate_records[0]["score"])
    if target_type == "claim" and best >= 0.45:
        return "potentially_overstrong"
    if target_type == "gap" and best >= 0.35:
        return "potentially_covered"
    return "needs_human_review"


def _falsification_reason(status: str, target_type: str) -> str:
    return {
        "potentially_overstrong": "accepted-index closest work overlaps the external claim enough to require source-level verification",
        "potentially_covered": "accepted-index closest work may already cover the stated gap",
        "needs_human_review": "bounded local retrieval found related accepted work but did not establish coverage",
        "not_falsified_locally": "bounded local retrieval found no strong accepted-index counterexample",
        "insufficient_local_evidence": "bounded local retrieval found no usable closest-work candidate",
    }.get(status, f"{target_type} requires follow-up")


def _falsification_summary(falsification: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for row in falsification:
        rows.append(
            {
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "check_type": row["check_type"],
                "status": row["status"],
                "closest_work_ids": "|".join(row["closest_work_ids"]),
                "trace_id": row["trace_id"],
                "reason": row["reason"],
            }
        )
    return rows


def _extract_assets_from_text(text: str) -> dict[str, list[str] | str]:
    datasets = _named_assets(text, ("dataset", "datasets"))
    benchmarks = _named_assets(text, ("benchmark", "benchmarks", "evaluation"))
    baselines = ["reported_baselines_unspecified"] if re.search(r"(?i)\bbaselines?\b", text) else []
    metrics = sorted({term for term in METRIC_TERMS if re.search(rf"(?i)\b{re.escape(term)}\b", text)})
    base_models = _nearby_terms(text, ("base model", "model"))
    backbones = _nearby_terms(text, ("backbone", "encoder", "decoder"))
    tasks = _task_phrases(text)
    methods = _method_phrases(text)
    return {
        "tasks": tasks,
        "problem_settings": _problem_settings(text),
        "method_types": methods,
        "base_models": base_models,
        "backbones": backbones,
        "datasets": datasets,
        "benchmarks": benchmarks,
        "metrics": metrics,
        "baselines": baselines,
        "experimental_protocols": ["evaluation_protocol_mentioned"] if re.search(r"(?i)\b(protocol|evaluation|benchmark)\b", text) else [],
        "ablations": ["ablation_mentioned"] if re.search(r"(?i)\bablation\b", text) else [],
        "compute_cost": "mentioned" if re.search(r"(?i)\b(compute|runtime|latency|throughput|cost|gpu|hardware)\b", text) else "",
        "data_cost": "mentioned" if re.search(r"(?i)\b(data cost|collection|curation)\b", text) else "",
        "annotation_cost": "mentioned" if re.search(r"(?i)\b(annotation|labeling|labelling)\b", text) else "",
        "claimed_contributions": _contribution_phrases(text),
        "limitations": _limitation_phrases(text),
        "failure_cases": _failure_phrases(text),
    }


def _named_assets(text: str, labels: tuple[str, ...]) -> list[str]:
    assets: list[str] = []
    for label in labels:
        pattern = rf"(?i)\b([A-Z][A-Za-z0-9_+-]{{1,30}}(?:\s+[A-Z][A-Za-z0-9_+-]{{1,30}}){{0,3}})\s+{label}\b"
        assets.extend(match.group(1).strip() for match in re.finditer(pattern, text))
    return _dedupe(assets)


def _nearby_terms(text: str, labels: tuple[str, ...]) -> list[str]:
    out = []
    for label in labels:
        pattern = rf"(?i)\b([A-Za-z0-9_+-]{{3,40}})\s+{re.escape(label)}\b"
        out.extend(match.group(1).strip() for match in re.finditer(pattern, text))
    return _dedupe(out[:8])


def _task_phrases(text: str) -> list[str]:
    keywords = []
    for match in re.finditer(r"(?i)\b([A-Za-z][A-Za-z0-9_-]{2,30})\s+(classification|detection|segmentation|reasoning|planning|generation|prediction|retrieval|alignment)\b", text):
        keywords.append(" ".join(match.groups()))
    return _dedupe(keywords[:8])


def _method_phrases(text: str) -> list[str]:
    out = []
    for term in ("transformer", "diffusion", "retrieval", "optimization", "contrastive", "graph", "agent", "adapter", "prompting"):
        if re.search(rf"(?i)\b{term}\b", text):
            out.append(term)
    return out


def _problem_settings(text: str) -> list[str]:
    out = []
    for term in ("few-shot", "zero-shot", "supervised", "semi-supervised", "self-supervised", "online", "offline", "multimodal"):
        if re.search(rf"(?i)\b{re.escape(term)}\b", text):
            out.append(term)
    return out


def _contribution_phrases(text: str) -> list[str]:
    if re.search(r"(?i)\b(improve|outperform|propose|introduce|contribution)\b", text):
        return ["contribution_mentioned_metadata_or_seed"]
    return []


def _limitation_phrases(text: str) -> list[str]:
    if re.search(r"(?i)\b(limitation|limited|fails?|weakness|cannot|challenge)\b", text):
        return ["limitation_mentioned_metadata_or_seed"]
    return []


def _failure_phrases(text: str) -> list[str]:
    if re.search(r"(?i)\b(failure|fails?|error|breaks|degrades)\b", text):
        return ["failure_case_mentioned_metadata_or_seed"]
    return []


def _asset_queries(normalized: dict[str, Any]) -> dict[str, set[str]]:
    queries: dict[str, set[str]] = defaultdict(set)
    for item in normalized["claims"] + normalized["gaps"] + normalized["ideas"]:
        extracted = _extract_assets_from_text(item.get("text", ""))
        for field, values in extracted.items():
            asset_type = _field_asset_type(field)
            if not asset_type:
                continue
            if isinstance(values, list):
                for value in values:
                    queries[asset_type].add(value)
            elif values:
                queries[asset_type].add(str(values))
    return queries


def _asset_names_from_text(text: str) -> list[str]:
    extracted = _extract_assets_from_text(text)
    names = []
    for field in ("datasets", "benchmarks", "metrics", "baselines", "base_models", "backbones", "tasks"):
        value = extracted.get(field)
        if isinstance(value, list):
            names.extend(value)
    return _dedupe(names)


def _implementation_constraints(text: str) -> list[str]:
    constraints = []
    if re.search(r"(?i)\b(compute|runtime|latency|throughput|memory|hardware|cost)\b", text):
        constraints.append("compute_or_runtime_constraint_needs_evidence")
    if re.search(r"(?i)\b(data|dataset|annotation|label)\b", text):
        constraints.append("data_or_annotation_constraint_needs_evidence")
    if re.search(r"(?i)\b(code|implementation|reproduce|reproducibility)\b", text):
        constraints.append("implementation_reproducibility_needs_evidence")
    return constraints


def _reviewer_blockers(text: str, has_closest: bool) -> list[str]:
    blockers = []
    if not has_closest:
        blockers.append("closest_work_missing")
    if re.search(r"(?i)\b(baseline|metric|benchmark|dataset)\b", text):
        blockers.append("evaluation_contract_needs_source_evidence")
    return blockers


def _contract_constraints(gaps: list[dict[str, Any]], paper_assets: list[dict[str, Any]]) -> list[str]:
    out = []
    for gap in gaps:
        out.extend(gap.get("implementation_constraints", []))
    for asset in paper_assets:
        out.extend(asset.get("implementation_barriers", []))
    return _dedupe(out)


def _contract_blockers(gaps: list[dict[str, Any]], blocking_missing: list[dict[str, Any]]) -> list[str]:
    blockers = []
    for gap in gaps:
        blockers.extend(gap.get("reviewer_blockers", []))
    for row in blocking_missing:
        blockers.append(f"{row['scope']}:{row['field']}:{row['target_id']}")
    return _dedupe(blockers)


def _evidence_card(
    *,
    paper_id: str,
    source_id: str,
    source_type: str,
    locator: str,
    target_id: str,
    target_type: str,
    evidence_kind: str,
    support_relation: str,
    content_summary: str,
    confidence: float,
    extraction_method: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "paper_id": paper_id,
        "source_id": source_id,
        "target_id": target_id,
        "target_type": target_type,
        "evidence_kind": evidence_kind,
        "content_summary": content_summary,
    }
    return {
        "evidence_id": stable_id("evidence", payload),
        "paper_id": paper_id,
        "source_id": source_id,
        "source_type": source_type,
        "locator": locator,
        "quote_hash": sha256_text(content_summary),
        "target_id": target_id,
        "target_type": target_type,
        "evidence_kind": evidence_kind,
        "support_relation": support_relation,
        "content_summary": content_summary,
        "confidence": round(float(confidence), 3),
        "extraction_method": extraction_method,
        "provenance": provenance,
    }


def _audit_row(seed: dict[str, Any], match: dict[str, str], status: str, reason: str, action: str, confidence: float) -> dict[str, str]:
    return {
        "seed_id": seed.get("seed_id", ""),
        "canonical_title": seed.get("canonical_title", ""),
        "audit_status": status,
        "action": action,
        "reason": reason,
        "local_paper_id": match.get("paper_id", ""),
        "match_method": reason.replace("matched accepted_index by ", "") if "matched accepted_index" in reason else "",
        "confidence": f"{confidence:.2f}",
        "venue": match.get("venue", seed.get("venue", "")),
        "year": match.get("year", seed.get("year", "")),
        "source_status": _source_status(match) if match else "external_metadata_only",
    }


def _identity_record(seed: dict[str, Any], match: dict[str, str], method: str, confidence: float, status: str) -> dict[str, Any]:
    return {
        "seed_id": seed.get("seed_id", ""),
        "seed_title": seed.get("canonical_title", ""),
        "local_paper_id": match.get("paper_id", ""),
        "canonical_title": match.get("title", ""),
        "match_method": method,
        "audit_status": status,
        "confidence": confidence,
        "provenance_span_ids": seed.get("provenance_span_ids", []),
    }


def _paper_summary(match: dict[str, str], seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": match.get("paper_id", ""),
        "canonical_title": match.get("title", seed.get("canonical_title", "")),
        "title": match.get("title", seed.get("canonical_title", "")),
        "venue": match.get("venue", seed.get("venue", "")),
        "year": match.get("year", seed.get("year", "")),
        "audit_status": "verified_local",
        "source_status": _source_status(match),
        "seed_id": seed.get("seed_id", ""),
        "seed_notes": seed.get("notes", ""),
    }


def _source_status(row: dict[str, str]) -> str:
    if not row:
        return "missing"
    text_status = row.get("source_text_status", "")
    if text_status in {"pdf_available", "preprint_available", "tex_available", "readable"}:
        return "readable_source_available"
    if row.get("pdf_url") or row.get("paper_link") or row.get("landing_url") or row.get("openreview_forum_id") or row.get("doi"):
        return "metadata_with_source_anchor"
    return "metadata_only"


def _path_status(path: Path | None, *, role: str) -> dict[str, Any]:
    return {"path": str(path or ""), "exists": bool(path and Path(path).exists()), "role": role}


def _field_asset_type(field: str) -> str:
    return {
        "datasets": "dataset",
        "benchmarks": "benchmark",
        "baselines": "baseline",
        "metrics": "metric",
        "base_models": "base_model",
        "backbones": "backbone",
        "tasks": "task",
    }.get(field, "")


def _asset_field(asset_type: str) -> str:
    return {
        "dataset": "datasets",
        "benchmark": "benchmarks",
        "baseline": "baselines",
        "metric": "metrics",
        "base_model": "base_models",
        "backbone": "backbones",
        "codebase": "reuse_opportunities",
        "task": "tasks",
    }[asset_type]


def _asset_role(asset_type: str) -> str:
    return {
        "dataset": "evaluation_data",
        "benchmark": "evaluation_protocol",
        "baseline": "comparison_target",
        "metric": "measurement",
        "base_model": "model_dependency",
        "backbone": "architecture_dependency",
        "codebase": "implementation_reuse",
        "task": "problem_scope",
    }[asset_type]


def _asset_stats_fields() -> list[str]:
    return [
        "asset_type",
        "normalized_name",
        "count_papers",
        "verified_count",
        "venues",
        "years",
        "representative_papers",
        "evidence_count",
        "confidence",
        "notes",
    ]


def _code_availability(row: dict[str, str]) -> str:
    if row.get("code_url"):
        return "code_url_present"
    if row.get("code_is_real") in {"true", "yes", "1"}:
        return "code_signal_present"
    return "unknown"


def _data_availability(row: dict[str, str]) -> str:
    if row.get("has_dataset") in {"yes", "true", "1"}:
        return "dataset_signal_present"
    return "unknown"


def _reuse_opportunities(row: dict[str, str], extracted: dict[str, Any]) -> list[str]:
    out = []
    if _code_availability(row) != "unknown":
        out.append("code_reuse_candidate")
    if row.get("has_pretrained_weights") in {"yes", "true", "1"}:
        out.append("pretrained_weight_reuse_candidate")
    if extracted.get("datasets") or extracted.get("benchmarks"):
        out.append("evaluation_reuse_candidate")
    return out


def _implementation_barriers(row: dict[str, str], extracted: dict[str, Any], source_status: str) -> list[str]:
    barriers = []
    if _code_availability(row) == "unknown":
        barriers.append("code_availability_unknown")
    if not extracted.get("baselines"):
        barriers.append("baseline_contract_unknown")
    if not extracted.get("compute_cost"):
        barriers.append("compute_cost_unknown")
    if source_status == "metadata_only":
        barriers.append("source_materialization_required_for_content_claims")
    return barriers


def _claim_type(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("outperform", "improve", "better", "state of the art")):
        return "performance_claim"
    if any(term in lowered for term in ("limitation", "fails", "cannot", "lack")):
        return "limitation_claim"
    if any(term in lowered for term in ("cost", "compute", "runtime", "latency")):
        return "cost_claim"
    return "external_observation"


def _combined_target_text(topic: str, normalized: dict[str, Any]) -> str:
    parts = [topic]
    parts.extend(item.get("text", "") for item in normalized["claims"][:20])
    parts.extend(item.get("text", "") for item in normalized["gaps"][:20])
    parts.extend(item.get("text", "") for item in normalized["ideas"][:20])
    parts.extend(item.get("canonical_title", "") for item in normalized["papers"][:50])
    return " ".join(parts)


def _paper_audit_lines(audit: dict[str, Any]) -> list[str]:
    lines = []
    for label, rows in (
        ("Verified local", audit["verified"]),
        ("External-only", audit["external_only"]),
        ("Uncertain", audit["uncertain"]),
        ("Dropped", audit["dropped"]),
    ):
        lines.append(f"### {label}")
        if not rows:
            lines.append("- None")
            continue
        for row in rows[:12]:
            title = row.get("title") or row.get("canonical_title", "")
            pid = row.get("paper_id") or row.get("seed_id", "")
            reason = row.get("reason", "")
            lines.append(f"- `{pid}` {title}" + (f" reason={reason}" if reason else ""))
    return lines


def _artifact_hashes(out_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = _rel(out_dir, path)
        if rel == "manifest.json" or rel.startswith("validation/"):
            continue
        hashes[rel] = sha256_file(path)
    return hashes


def _copy_input(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)
    return dst


def _input_dir_path(input_dir: Path | None, name: str) -> Path | None:
    if not input_dir:
        return None
    path = input_dir / name
    return path if path.exists() else None


def _provenance_span(
    out_dir: Path,
    path: Path,
    line_start: int,
    line_end: int,
    text: str,
    target_type: str,
    provenance: list[dict[str, Any]],
    *,
    target_id: str = "",
) -> str:
    span = {
        "span_id": stable_id("span", {"path": path.name, "line_start": line_start, "line_end": line_end, "text": text}),
        "source_file": _rel(out_dir, path) if out_dir in path.resolve().parents or path.resolve() == out_dir.resolve() else str(path),
        "line_start": line_start,
        "line_end": line_end,
        "target_type": target_type,
        "target_id": target_id,
        "text_hash": sha256_text(text),
        "excerpt": _snippet(text, 300),
    }
    provenance.append(span)
    return span["span_id"]


def _parse_error(path: Path, line_no: int, reason: str, payload: Any) -> dict[str, Any]:
    return {
        "source_file": path.name,
        "line": line_no,
        "reason": reason,
        "payload_hash": sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)),
    }


def _best_title_match(title: str, rows: list[dict[str, str]]) -> tuple[dict[str, str], float] | None:
    tokens = set(tokenize(title))
    if not tokens:
        return None
    best_row: dict[str, str] | None = None
    best_score = 0.0
    for row in rows:
        row_tokens = set(tokenize(row.get("title", "")))
        if not row_tokens:
            continue
        score = len(tokens & row_tokens) / max(1, len(tokens | row_tokens))
        if score > best_score:
            best_score = score
            best_row = row
    if best_row is None:
        return None
    return best_row, best_score


def _iter_jsonl(path: Path) -> Iterable[tuple[int, Any, str]]:
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            yield line_no, json.loads(line), ""
        except json.JSONDecodeError as exc:
            yield line_no, None, f"json_decode_error:{exc.msg}"


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] not in {None, ""}:
            return row[key]
    return ""


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[|,;]+", value) if part.strip()]
    return []


def _split_authors(value: str) -> list[str]:
    return [part.strip() for part in re.split(r";|\band\b|,", value) if part.strip()]


def _extract_year(text: str) -> str:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", text or "")
    return match.group(1) if match else ""


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9./_-]+", "", (value or "").lower()).strip()


def normalize_asset_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def tokenize(text: str) -> list[str]:
    out = []
    for token in re.split(r"[^A-Za-z0-9_+-]+", text.lower()):
        if len(token) < 3 or token in STOPWORDS:
            continue
        out.append(token)
    return out


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    return slug or "survey_topic"


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def stable_id(prefix: str, payload: Any) -> str:
    return f"{prefix}:{hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]}"


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    _write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field, "")) for field in fieldnames})


def _csv_value(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    return str(value)


def _snippet(text: str, limit: int = 500) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean if len(clean) <= limit else clean[: limit - 3] + "..."


def _to_float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        clean = str(value).strip()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def _dedupe_by_key(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        value = str(row.get(key, ""))
        if value in seen:
            continue
        seen.add(value)
        out.append(row)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
