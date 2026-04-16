#!/usr/bin/env python3
"""Survey accepted list sources for given venues and years.

Generic implementation: probes known official patterns (virtual conference JSON,
proceedings pages, OpenAccess, OpenReview) and GitHub community datasets.
No hardcoded per-conference logic.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


VENUE_DOMAINS: dict[str, dict] = {
    "ICLR": {
        "virtual_base": "https://iclr.cc",
        "proceedings_base": "https://proceedings.iclr.cc/paper_files/paper",
        "virtual_json_pattern": "https://iclr.cc/static/virtual/data/iclr-{year}-orals-posters.json",
        "virtual_html_pattern": "https://iclr.cc/virtual/{year}/papers.html",
        "openreview_group": "ICLR.cc/{year}/Conference",
    },
    "NEURIPS": {
        "virtual_base": "https://neurips.cc",
        "proceedings_base": "https://papers.nips.cc/paper_files/paper",
        "virtual_json_pattern": "https://neurips.cc/static/virtual/data/neurips-{year}-orals-posters.json",
        "virtual_html_pattern": "https://neurips.cc/virtual/{year}/papers.html",
        "openreview_group": "NeurIPS.cc/{year}/Conference",
    },
    "ICML": {
        "virtual_base": "https://icml.cc",
        "proceedings_base": None,
        "virtual_json_pattern": "https://icml.cc/static/virtual/data/icml-{year}-orals-posters.json",
        "virtual_html_pattern": "https://icml.cc/virtual/{year}/papers.html",
        "openreview_group": "ICML.cc/{year}/Conference",
    },
    "CVPR": {
        "virtual_base": None,
        "proceedings_base": None,
        "openaccess_pattern": "https://openaccess.thecvf.com/CVPR{year}?day=all",
        "openreview_group": None,
    },
    "ECCV": {
        "virtual_base": None,
        "proceedings_base": None,
        "openaccess_pattern": "https://openaccess.thecvf.com/ECCV{year}?day=all",
        "openreview_group": None,
    },
    "ICCV": {
        "virtual_base": None,
        "proceedings_base": None,
        "openaccess_pattern": "https://openaccess.thecvf.com/ICCV{year}?day=all",
        "openreview_group": None,
    },
}


@dataclass
class SourceCandidate:
    name: str
    url: str
    status: int
    fields: list[str] = field(default_factory=list)
    notes: str = ""
    recommended_kind: str = ""
    recommended_parser: str = ""


@dataclass
class SourceProbeResult:
    venue: str
    year: int
    candidates: list[SourceCandidate] = field(default_factory=list)
    github_repos: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _http_status(url: str, timeout: int = 10) -> int:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def _http_get_json(url: str, timeout: int = 15) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "resmax-survey/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return proc.stdout or ""


def probe_virtual_json(venue: str, year: int, domain: dict) -> SourceCandidate | None:
    pattern = domain.get("virtual_json_pattern")
    if not pattern:
        return None
    url = pattern.format(year=year)
    status = _http_status(url)
    if status != 200:
        return SourceCandidate(
            name=f"{venue} {year} Virtual Conference JSON",
            url=url, status=status,
            notes=f"HTTP {status}" if status else "unreachable",
        )
    data = _http_get_json(url)
    count = data.get("count", len(data.get("results", []))) if data else 0
    has_abstract = False
    has_authors = False
    if data and data.get("results"):
        sample = data["results"][0]
        has_abstract = bool(sample.get("abstract"))
        has_authors = bool(sample.get("authors"))
    fields = ["title"]
    if has_authors:
        fields.append("authors")
    if has_abstract:
        fields.append("abstract")
    fields.extend(["decision", "topic", "poster_url"])
    return SourceCandidate(
        name=f"{venue} {year} Virtual Conference JSON",
        url=url, status=200,
        fields=fields,
        notes=f"{count} entries",
        recommended_kind="virtual_conference_json",
        recommended_parser="virtual_conference_json",
    )


def probe_proceedings(venue: str, year: int, domain: dict) -> SourceCandidate | None:
    base = domain.get("proceedings_base")
    if not base:
        return None
    url = f"{base}/{year}"
    status = _http_status(url)
    if status != 200:
        return SourceCandidate(
            name=f"{venue} {year} Proceedings",
            url=url, status=status,
            notes=f"HTTP {status}" if status else "unreachable",
        )
    return SourceCandidate(
        name=f"{venue} {year} Proceedings",
        url=url, status=200,
        fields=["title", "authors", "paper_link"],
        notes="official proceedings page",
        recommended_kind="iclr_proceedings_html",
        recommended_parser="iclr_proceedings_html",
    )


def probe_openaccess(venue: str, year: int, domain: dict) -> SourceCandidate | None:
    pattern = domain.get("openaccess_pattern")
    if not pattern:
        return None
    url = pattern.format(year=year)
    status = _http_status(url)
    parser = "cvpr_openaccess_html"
    if status != 200:
        return SourceCandidate(
            name=f"{venue} {year} CVF OpenAccess",
            url=url, status=status,
            notes=f"HTTP {status}" if status else "unreachable",
        )
    return SourceCandidate(
        name=f"{venue} {year} CVF OpenAccess",
        url=url, status=200,
        fields=["title", "authors", "pdf_link", "arxiv_id"],
        notes="CVF OpenAccess page",
        recommended_kind="cvpr_openaccess_html",
        recommended_parser=parser,
    )


def probe_virtual_html(venue: str, year: int, domain: dict) -> SourceCandidate | None:
    pattern = domain.get("virtual_html_pattern")
    if not pattern:
        return None
    url = pattern.format(year=year)
    status = _http_status(url)
    if status not in (200, 302):
        return SourceCandidate(
            name=f"{venue} {year} Virtual HTML",
            url=url, status=status,
            notes=f"HTTP {status}" if status else "unreachable",
        )
    return SourceCandidate(
        name=f"{venue} {year} Virtual HTML",
        url=url, status=200,
        fields=["title", "poster_url"],
        notes="virtual conference HTML (JS-rendered, title only)",
        recommended_kind=f"{venue.lower()}_virtual_html",
        recommended_parser=f"{venue.lower()}_virtual_html" if venue.upper() == "ICLR" else "neurips_virtual_html",
    )


def probe_github(venue: str, year: int) -> list[str]:
    queries = [
        f"{venue}{year} accepted",
        f"{venue} {year} papers list",
    ]
    repos: list[str] = []
    for q in queries:
        out = _run([
            "gh", "search", "repos", q,
            "--sort", "stars", "--limit", "5",
            "--json", "fullName,description,stargazersCount",
        ])
        if out.strip():
            try:
                items = json.loads(out)
                for item in items:
                    name = item.get("fullName", "")
                    stars = item.get("stargazersCount", 0)
                    desc = (item.get("description") or "")[:80]
                    repos.append(f"{name} ({stars} stars): {desc}")
            except json.JSONDecodeError:
                repos.append(f"gh search '{q}' returned non-JSON output")
    return repos


def probe_venue_year(venue: str, year: int) -> SourceProbeResult:
    result = SourceProbeResult(venue=venue, year=year)
    venue_upper = venue.upper()
    domain = VENUE_DOMAINS.get(venue_upper, {})

    if not domain:
        result.notes.append(f"No known domain patterns for {venue}. Manual investigation needed.")
        result.github_repos = probe_github(venue, year)
        return result

    for probe_fn in [probe_virtual_json, probe_proceedings, probe_openaccess, probe_virtual_html]:
        candidate = probe_fn(venue_upper, year, domain)
        if candidate:
            result.candidates.append(candidate)

    result.github_repos = probe_github(venue, year)

    available = [c for c in result.candidates if c.status == 200]
    if not available:
        result.notes.append(f"No accessible official source found for {venue} {year}.")
    else:
        best = max(available, key=lambda c: len(c.fields))
        result.notes.append(f"Recommended primary: {best.name} ({', '.join(best.fields)})")

    return result


def render_report(result: SourceProbeResult) -> str:
    lines: list[str] = []
    lines.append(f"# {result.venue} {result.year} accepted source survey")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    for n in result.notes:
        lines.append(f"- {n}")
    lines.append("")

    lines.append("## Official Sources Probed")
    lines.append("")
    if result.candidates:
        lines.append("| source | status | fields | notes | recommended parser |")
        lines.append("|--------|--------|--------|-------|--------------------|")
        for c in result.candidates:
            status_str = f"OK ({c.status})" if c.status == 200 else f"FAIL ({c.status})"
            fields_str = ", ".join(c.fields) if c.fields else "-"
            parser_str = c.recommended_parser if c.status == 200 else "-"
            lines.append(f"| {c.name} | {status_str} | {fields_str} | {c.notes} | {parser_str} |")
    else:
        lines.append("- No official sources probed (unknown venue pattern).")
    lines.append("")

    lines.append("## GitHub / Community Datasets")
    lines.append("")
    if result.github_repos:
        for r in result.github_repos:
            lines.append(f"- {r}")
    else:
        lines.append("- No community datasets found.")
    lines.append("")

    available = [c for c in result.candidates if c.status == 200]
    if available:
        best = max(available, key=lambda c: len(c.fields))
        lines.append("## Recommended Registry Entry")
        lines.append("")
        lines.append("```json")
        entry = {
            "venue": result.venue.upper(),
            "year": result.year,
            "conf_year": f"{result.venue.upper()}_{result.year}",
            "status": "active",
            "skip_reason": "",
            "primary_source": {
                "kind": best.recommended_kind,
                "url": best.url,
                "parser": best.recommended_parser,
                "expected_count": None,
            },
            "auxiliary_sources": [],
            "notes": f"Auto-surveyed. Source: {best.name}",
        }
        lines.append(json.dumps(entry, indent=2, ensure_ascii=False))
        lines.append("```")
        lines.append("")

    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Survey accepted list sources for given venues and years.")
    p.add_argument("--venues", required=True, help="Comma-separated venues, e.g., ICLR,CVPR")
    p.add_argument("--years", required=True, help="Comma-separated years, e.g., 2025,2026")
    p.add_argument("--out", required=True, help="Output directory for survey reports")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    venues = {v.strip().upper() for v in args.venues.split(",") if v.strip()}
    years = {int(y) for y in args.years.split(",") if y.strip()}

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for venue in sorted(venues):
        for year in sorted(years):
            print(f"[SURVEY] probing {venue} {year}...")
            result = probe_venue_year(venue, year)
            report_path = out_dir / f"{venue}_{year}_source_survey.md"
            report_path.write_text(render_report(result), encoding="utf-8")
            print(f"[OK] wrote survey report: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())