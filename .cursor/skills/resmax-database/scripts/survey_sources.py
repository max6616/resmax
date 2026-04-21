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


OPENREVIEW_API = "https://api2.openreview.net"

REVIEW_POLICY: dict[str, dict] = {
    "ICLR": {
        "reviews_public": True,
        "platform": "openreview_v2",
        "group_pattern": "ICLR.cc/{year}/Conference",
        "review_invitation": "ICLR.cc/{year}/Conference/Submission{number}/-/Official_Review",
        "default_score_scale": "1-10",
        "default_num_reviewers": 4,
        "notes": "All reviews public (accepted + rejected).",
    },
    "NEURIPS": {
        "reviews_public": True,
        "platform": "openreview_v2",
        "group_pattern": "NeurIPS.cc/{year}/Conference",
        "review_invitation": "NeurIPS.cc/{year}/Conference/Submission{number}/-/Official_Review",
        "default_score_scale": "1-10",
        "score_scale_overrides": {2025: "1-6"},
        "default_num_reviewers": 4,
        "notes": "Accepted paper reviews public. Score scale changed to 1-6 in 2025.",
    },
    "ICML": {
        "reviews_public": True,
        "platform": "openreview_v2",
        "group_pattern": "ICML.cc/{year}/Conference",
        "review_invitation": "ICML.cc/{year}/Conference/Submission{number}/-/Official_Review",
        "default_score_scale": "1-10",
        "default_num_reviewers": 4,
        "notes": "Accepted paper reviews public. Rejected opt-in only.",
    },
    "ACL": {
        "reviews_public": "partial",
        "platform": "openreview_v2_arr",
        "group_pattern": "aclweb.org/ACL/ARR/{year}/{month}",
        "default_score_scale": "1-5",
        "default_num_reviewers": 3,
        "notes": "Via ACL Rolling Review. Delayed release; structured datasets from TU Darmstadt.",
    },
    "EMNLP": {
        "reviews_public": "partial",
        "platform": "openreview_v2_arr",
        "group_pattern": "aclweb.org/ACL/ARR/{year}/{month}",
        "default_score_scale": "1-5",
        "default_num_reviewers": 3,
        "notes": "Via ACL Rolling Review. Same policy as ACL.",
    },
    "NAACL": {
        "reviews_public": "partial",
        "platform": "openreview_v2_arr",
        "group_pattern": "aclweb.org/ACL/ARR/{year}/{month}",
        "default_score_scale": "1-5",
        "default_num_reviewers": 3,
        "notes": "Via ACL Rolling Review. Same policy as ACL.",
    },
}

VENUES_NO_REVIEWS = {"CVPR", "ECCV", "ICCV", "AAAI", "KDD", "SIGGRAPH", "SIGGRAPH_ASIA", "ACMMM"}


VENUE_DOMAINS: dict[str, dict] = {
    "ICLR": {
        "virtual_json_pattern": "https://iclr.cc/static/virtual/data/iclr-{year}-orals-posters.json",
        "virtual_html_pattern": "https://iclr.cc/virtual/{year}/papers.html",
        "proceedings_base": "https://proceedings.iclr.cc/paper_files/paper",
        "openreview_group": "ICLR.cc/{year}/Conference",
    },
    "NEURIPS": {
        "virtual_json_pattern": "https://neurips.cc/static/virtual/data/neurips-{year}-orals-posters.json",
        "virtual_html_pattern": "https://neurips.cc/virtual/{year}/papers.html",
        "proceedings_base": "https://papers.nips.cc/paper_files/paper",
        "openreview_group": "NeurIPS.cc/{year}/Conference",
    },
    "ICML": {
        "virtual_json_pattern": "https://icml.cc/static/virtual/data/icml-{year}-orals-posters.json",
        "virtual_html_pattern": "https://icml.cc/virtual/{year}/papers.html",
        "openreview_group": "ICML.cc/{year}/Conference",
    },
    "CVPR": {
        "openaccess_pattern": "https://openaccess.thecvf.com/CVPR{year}?day=all",
    },
    "ECCV": {
        "virtual_json_pattern": "https://eccv.ecva.net/static/virtual/data/eccv-{year}-orals-posters.json",
        "openaccess_pattern": "https://openaccess.thecvf.com/ECCV{year}?day=all",
    },
    "ICCV": {
        "openaccess_pattern": "https://openaccess.thecvf.com/ICCV{year}?day=all",
    },
    "ACL": {
        "anthology_pattern": "https://aclanthology.org/events/acl-{year}/",
    },
    "EMNLP": {
        "anthology_pattern": "https://aclanthology.org/events/emnlp-{year}/",
    },
    "NAACL": {
        "anthology_pattern": "https://aclanthology.org/events/naacl-{year}/",
    },
    "AAAI": {
        "ojs_archive_url": "https://ojs.aaai.org/index.php/AAAI/issue/archive",
    },
    "KDD": {
        "kdd_official_pattern": "https://kdd{year}.kdd.org/research-track-papers/",
    },
    "SIGGRAPH": {
        "kesen_pattern": "https://kesen.realtimerendering.com/sig{year}.html",
    },
    "SIGGRAPH_ASIA": {
        "kesen_pattern": "https://kesen.realtimerendering.com/siga{year}.html",
    },
    "ACMMM": {
        "acmmm_official_pattern": "https://{year}.acmmm.org/accepted-papers",
        "acmmm_alt_pattern": "https://acmmm{year}.org/accepted-papers",
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
class ReviewProbeInfo:
    available: str = "unknown"  # "yes" | "no" | "partial" | "unknown"
    platform: str = ""
    score_scale: str = ""
    num_reviewers: int = 0
    api_group: str = ""
    invitation_pattern: str = ""
    sample_verified: bool = False
    notes: str = ""


@dataclass
class SourceProbeResult:
    venue: str
    year: int
    candidates: list[SourceCandidate] = field(default_factory=list)
    github_repos: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    review_info: ReviewProbeInfo | None = None


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


def probe_acl_anthology(venue: str, year: int, domain: dict) -> SourceCandidate | None:
    pattern = domain.get("anthology_pattern")
    if not pattern:
        return None
    url = pattern.format(year=year)
    status = _http_status(url)
    if status != 200:
        return SourceCandidate(
            name=f"{venue} {year} ACL Anthology",
            url=url, status=status,
            notes=f"HTTP {status}" if status else "unreachable",
        )
    return SourceCandidate(
        name=f"{venue} {year} ACL Anthology",
        url=url, status=200,
        fields=["title", "authors", "abstract", "pdf_link"],
        notes="ACL Anthology event page",
        recommended_kind="acl_anthology_html",
        recommended_parser="acl_anthology_html",
    )


def probe_aaai_ojs(venue: str, year: int, domain: dict) -> SourceCandidate | None:
    url = domain.get("ojs_archive_url")
    if not url:
        return None
    status = _http_status(url)
    if status != 200:
        return SourceCandidate(
            name=f"AAAI {year} OJS Archive",
            url=url, status=status,
            notes=f"HTTP {status}" if status else "unreachable",
        )
    yy = str(year)[-2:]
    return SourceCandidate(
        name=f"AAAI {year} OJS Archive",
        url=url, status=200,
        fields=["title", "authors", "abstract", "pdf_link"],
        notes=f"AAAI OJS multi-issue (parser_args: AAAI-{yy})",
        recommended_kind="aaai_ojs_multi_issue",
        recommended_parser="aaai_ojs_html",
    )


def probe_kdd_official(venue: str, year: int, domain: dict) -> SourceCandidate | None:
    pattern = domain.get("kdd_official_pattern")
    if not pattern:
        return None
    url = pattern.format(year=year)
    status = _http_status(url)
    if status != 200:
        return SourceCandidate(
            name=f"KDD {year} Official",
            url=url, status=status,
            notes=f"HTTP {status}" if status else "unreachable",
        )
    return SourceCandidate(
        name=f"KDD {year} Official",
        url=url, status=200,
        fields=["title", "authors"],
        notes="KDD official research track page",
        recommended_kind="kdd_html",
        recommended_parser="kdd_html",
    )


def probe_kesen_siggraph(venue: str, year: int, domain: dict) -> SourceCandidate | None:
    pattern = domain.get("kesen_pattern")
    if not pattern:
        return None
    url = pattern.format(year=year)
    status = _http_status(url)
    if status != 200:
        return SourceCandidate(
            name=f"{venue} {year} Ke-Sen Huang",
            url=url, status=status,
            notes=f"HTTP {status}" if status else "unreachable",
        )
    return SourceCandidate(
        name=f"{venue} {year} Ke-Sen Huang",
        url=url, status=200,
        fields=["title", "authors", "paper_link", "arxiv_id"],
        notes="Ke-Sen Huang paper list",
        recommended_kind="kesen_siggraph_html",
        recommended_parser="kesen_siggraph_html",
    )


def probe_acmmm_official(venue: str, year: int, domain: dict) -> SourceCandidate | None:
    keys = ("acmmm_official_pattern", "acmmm_alt_pattern")
    if not any(domain.get(k) for k in keys):
        return None
    for key in keys:
        pattern = domain.get(key)
        if not pattern:
            continue
        url = pattern.format(year=year)
        status = _http_status(url)
        if status == 200:
            return SourceCandidate(
                name=f"ACM MM {year} Official",
                url=url, status=200,
                fields=["title", "authors"],
                notes="ACM MM official accepted papers page",
                recommended_kind="acmmm_html",
                recommended_parser="acmmm_html",
            )
    return SourceCandidate(
        name=f"ACM MM {year} Official",
        url=domain.get("acmmm_official_pattern", "").format(year=year),
        status=0,
        notes="all known URL patterns unreachable",
    )


def probe_openreview_reviews(venue: str, year: int) -> ReviewProbeInfo:
    venue_upper = venue.upper()
    if venue_upper in VENUES_NO_REVIEWS:
        return ReviewProbeInfo(
            available="no",
            notes=f"{venue_upper} does not publicly release reviews.",
        )

    policy = REVIEW_POLICY.get(venue_upper)
    if not policy:
        return ReviewProbeInfo(
            available="unknown",
            notes=f"No review policy data for {venue_upper}. Manual check needed.",
        )

    if not policy.get("reviews_public"):
        return ReviewProbeInfo(available="no", notes=policy.get("notes", ""))

    overrides = policy.get("score_scale_overrides", {})
    score_scale = overrides.get(year, policy.get("default_score_scale", ""))
    group = policy["group_pattern"].format(year=year, month="*")
    avail = "yes" if policy["reviews_public"] is True else str(policy["reviews_public"])

    info = ReviewProbeInfo(
        available=avail,
        platform=policy.get("platform", ""),
        score_scale=score_scale,
        num_reviewers=policy.get("default_num_reviewers", 0),
        api_group=group,
        invitation_pattern=policy.get("review_invitation", ""),
        notes=policy.get("notes", ""),
    )

    if policy.get("platform") == "openreview_v2":
        info = _verify_openreview_reviews(info, venue_upper, year, policy)

    return info


def _verify_openreview_reviews(
    info: ReviewProbeInfo, venue: str, year: int, policy: dict,
) -> ReviewProbeInfo:
    group = policy["group_pattern"].format(year=year)
    url = (
        f"{OPENREVIEW_API}/notes?"
        f"invitation={group}/-/Submission&limit=1&details=replies"
    )
    data = _http_get_json(url, timeout=20)
    if not data or not data.get("notes"):
        info.notes += " API probe: no submissions found or API error."
        return info

    sample = data["notes"][0]
    forum_id = sample.get("id", "")
    replies = sample.get("details", {}).get("replies", [])
    review_count = sum(
        1 for r in replies
        if "Official_Review" in r.get("invitation", "")
    )
    if review_count > 0:
        info.sample_verified = True
        info.notes += f" API probe OK: sampled forum {forum_id}, found {review_count} reviews."
    else:
        info.notes += f" API probe: sampled forum {forum_id}, no reviews visible."

    return info


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

    for probe_fn in [
        probe_virtual_json, probe_proceedings, probe_openaccess,
        probe_virtual_html, probe_acl_anthology, probe_aaai_ojs,
        probe_kdd_official, probe_kesen_siggraph, probe_acmmm_official,
    ]:
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

    result.review_info = probe_openreview_reviews(venue, year)
    if result.review_info.available == "yes":
        result.notes.append(
            f"Reviews: publicly available via {result.review_info.platform} "
            f"(scale {result.review_info.score_scale}, ~{result.review_info.num_reviewers} reviewers)"
        )
    elif result.review_info.available == "partial":
        result.notes.append(f"Reviews: partially available — {result.review_info.notes}")
    else:
        result.notes.append("Reviews: not publicly available.")

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

    ri = result.review_info
    lines.append("## Review Data Availability")
    lines.append("")
    if ri:
        lines.append(f"- **Available**: {ri.available}")
        if ri.platform:
            lines.append(f"- **Platform**: {ri.platform}")
        if ri.score_scale:
            lines.append(f"- **Score scale**: {ri.score_scale}")
        if ri.num_reviewers:
            lines.append(f"- **Typical reviewers/paper**: {ri.num_reviewers}")
        if ri.api_group:
            lines.append(f"- **API group**: `{ri.api_group}`")
        if ri.invitation_pattern:
            lines.append(f"- **Review invitation**: `{ri.invitation_pattern}`")
        lines.append(f"- **Sample verified**: {ri.sample_verified}")
        if ri.notes:
            lines.append(f"- **Notes**: {ri.notes}")
    else:
        lines.append("- No review probe performed.")
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