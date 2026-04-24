from __future__ import annotations

import re
import urllib.parse
import json
from dataclasses import dataclass
from typing import Mapping


TRAILING_URL_PUNCT = " \t\r\n.,;!?)]}>'\""

SOURCE_TEXT_STATUS_VALUES = {
    "pdf_available",
    "preprint_available",
    "publisher_landing_only",
    "official_landing_only",
    "source_listing_only",
    "paywalled_landing",
    "not_yet_public",
    "unresolved_after_search",
    "missing_anchor_needs_search",
    "",
}


def clean_url_token(raw: str) -> str:
    """Strip punctuation that commonly follows URLs in prose.

    Keep URL path characters intact. This only removes punctuation at the
    token boundary, so `MetaGPT` never becomes `MetaGP`.
    """
    return (raw or "").strip().rstrip(TRAILING_URL_PUNCT)


def normalize_http_url(raw: str) -> str:
    url = clean_url_token(raw)
    if not url:
        return ""
    if url.startswith("www."):
        url = "https://" + url
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        if url.lower().startswith(("github.com/", "gitlab.com/")):
            url = "https://" + url
    return url


def normalize_repo_url(raw: str) -> str:
    """Return canonical GitHub/GitLab repo URL, preserving owner/repo case."""
    url = normalize_http_url(raw)
    if not url:
        return ""

    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in {"github.com", "gitlab.com"}:
        return url

    parts = [urllib.parse.unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return f"https://{host}/" + "/".join(parts)

    owner = parts[0].strip()
    repo = clean_url_token(parts[1]).strip()
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return ""
    return f"https://{host}/{owner}/{repo}"


def repo_cache_key(raw: str) -> str:
    url = normalize_repo_url(raw)
    parsed = urllib.parse.urlsplit(url)
    if parsed.netloc.lower().lstrip("www.") not in {"github.com", "gitlab.com"}:
        return ""
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return ""
    return f"{parts[0]}/{parts[1]}".lower()


def normalize_yes_no(raw: str) -> str:
    val = (raw or "").strip().lower()
    if val in {"1", "true", "yes", "y"}:
        return "yes"
    if val in {"0", "false", "no", "n"}:
        return "no"
    return ""


def is_valid_abstract(raw: str) -> bool:
    text = (raw or "").strip()
    if not text:
        return False
    if text.lower() in {"none", "null", "nan", "n/a", "international audience"}:
        return False
    return len(text) >= 10


def is_pdf_like_url(raw: str) -> bool:
    url = (raw or "").lower()
    return (
        url.endswith(".pdf")
        or "/pdf/" in url
        or "/pdf?id=" in url
        or "arxiv.org/pdf/" in url
        or bool(re.search(r"/article/view/\d+/\d+$", url))
    )


def cvf_html_to_pdf(raw: str) -> str:
    url = normalize_http_url(raw)
    if "openaccess.thecvf.com" not in url or "/html/" not in url:
        return ""
    return url.replace("/html/", "/papers/").replace("_paper.html", "_paper.pdf")


def acl_anthology_to_pdf(raw: str) -> str:
    url = normalize_http_url(raw)
    if "aclanthology.org" not in url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host != "aclanthology.org":
        return ""
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 1:
        return ""
    paper_id = clean_url_token(parts[0])
    if not paper_id or paper_id.lower().endswith(".pdf"):
        return ""
    return f"https://aclanthology.org/{paper_id}.pdf"


@dataclass(frozen=True)
class PdfContract:
    landing_url: str
    pdf_url: str
    pdf_status: str
    pdf_source: str


@dataclass(frozen=True)
class SourceTextContract:
    source_text_status: str
    source_text_url: str
    source_text_source: str
    source_text_evidence: str
    source_text_search_query: str


def doi_to_url(raw: str) -> str:
    doi = (raw or "").strip()
    if not doi:
        return ""
    if doi.lower().startswith("http"):
        return normalize_http_url(doi)
    if doi.lower().startswith("doi:"):
        doi = doi[4:].strip()
    return f"https://doi.org/{doi}"


def _source_text_query(row: Mapping[str, str]) -> str:
    title = (row.get("title", "") or "").strip()
    if title:
        return f"\"{title}\" PDF"
    paper_id = (row.get("paper_id", "") or "").strip()
    return f"\"{paper_id}\" PDF" if paper_id else ""


def _evidence(**kwargs: str) -> str:
    clean = {k: v for k, v in kwargs.items() if v not in (None, "")}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True)


def derive_pdf_contract(row: Mapping[str, str]) -> PdfContract:
    """Derive the normalized landing/PDF fields from accepted_index columns."""
    existing_pdf = normalize_http_url(row.get("pdf_url", ""))
    paper_link = normalize_http_url(row.get("paper_link", ""))
    paper_url = normalize_http_url(row.get("paper_url", ""))
    full_paper_url = normalize_http_url(row.get("full_paper_url", ""))
    arxiv_id = (row.get("arxiv_id", "") or "").strip()
    arxiv_url = normalize_http_url(row.get("arxiv_url", ""))
    forum_id = (row.get("openreview_forum_id", "") or "").strip()

    landing = paper_link or paper_url or full_paper_url or arxiv_url

    if existing_pdf:
        return PdfContract(landing, existing_pdf, "available", "pdf_url")
    if arxiv_id:
        return PdfContract(landing or f"https://arxiv.org/abs/{arxiv_id}", f"https://arxiv.org/pdf/{arxiv_id}.pdf", "available", "arxiv_id")
    if forum_id:
        landing = landing or f"https://openreview.net/forum?id={forum_id}"
        return PdfContract(landing, f"https://openreview.net/pdf?id={forum_id}", "available", "openreview_forum_id")
    cvf_pdf = cvf_html_to_pdf(paper_link)
    if cvf_pdf:
        return PdfContract(landing, cvf_pdf, "available", "cvf_html")
    acl_pdf = acl_anthology_to_pdf(paper_link)
    if acl_pdf:
        return PdfContract(landing, acl_pdf, "available", "acl_anthology")
    if paper_link and is_pdf_like_url(paper_link):
        return PdfContract(landing, paper_link, "available", "paper_link")

    return PdfContract(landing, "", "missing_unresolved", "none")


def derive_source_text_contract(row: Mapping[str, str]) -> SourceTextContract:
    """Return the best current original-text anchor and audit evidence.

    `pdf_url` remains the direct-readable ideal. Rows without a direct PDF still
    get a status and evidence so downstream validation can distinguish
    publisher landing pages, venue listings, and rows that need web search.
    """
    pdf = derive_pdf_contract(row)
    query = _source_text_query(row)
    doi = (row.get("doi", "") or "").strip()
    doi_url = doi_to_url(doi)
    source_type = (row.get("source_type", "") or "").strip()
    source_url = normalize_http_url(row.get("source_url", ""))
    paper_link = normalize_http_url(row.get("paper_link", ""))
    landing_url = normalize_http_url(row.get("landing_url", "")) or pdf.landing_url
    paper_url = normalize_http_url(row.get("paper_url", ""))
    full_paper_url = normalize_http_url(row.get("full_paper_url", ""))
    arxiv_url = normalize_http_url(row.get("arxiv_url", ""))
    virtualsite_url = normalize_http_url(row.get("virtualsite_url", ""))

    if pdf.pdf_url:
        status = "preprint_available" if pdf.pdf_source == "arxiv_id" else "pdf_available"
        return SourceTextContract(
            source_text_status=status,
            source_text_url=pdf.pdf_url,
            source_text_source=pdf.pdf_source,
            source_text_evidence=_evidence(
                kind="direct_pdf",
                pdf_source=pdf.pdf_source,
                pdf_url=pdf.pdf_url,
                landing_url=pdf.landing_url,
                source_type=source_type,
            ),
            source_text_search_query="",
        )

    if doi_url:
        return SourceTextContract(
            source_text_status="publisher_landing_only",
            source_text_url=doi_url,
            source_text_source="doi",
            source_text_evidence=_evidence(
                kind="doi_landing",
                doi=doi,
                doi_url=doi_url,
                landing_url=landing_url,
                source_type=source_type,
            ),
            source_text_search_query=query,
        )

    for field, url in (
        ("landing_url", landing_url),
        ("paper_link", paper_link),
        ("paper_url", paper_url),
        ("full_paper_url", full_paper_url),
        ("arxiv_url", arxiv_url),
        ("virtualsite_url", virtualsite_url),
    ):
        if url:
            return SourceTextContract(
                source_text_status="official_landing_only",
                source_text_url=url,
                source_text_source=field,
                source_text_evidence=_evidence(
                    kind="official_landing",
                    field=field,
                    url=url,
                    source_type=source_type,
                ),
                source_text_search_query=query,
            )

    if source_url:
        return SourceTextContract(
            source_text_status="source_listing_only",
            source_text_url=source_url,
            source_text_source="source_url",
            source_text_evidence=_evidence(
                kind="source_listing",
                source_url=source_url,
                source_type=source_type,
            ),
            source_text_search_query=query,
        )

    return SourceTextContract(
        source_text_status="missing_anchor_needs_search",
        source_text_url="",
        source_text_source="none",
        source_text_evidence=_evidence(
            kind="missing_anchor",
            paper_id=row.get("paper_id", "") or "",
            title=row.get("title", "") or "",
            venue=row.get("venue", "") or "",
            year=row.get("year", "") or "",
            source_type=source_type,
        ),
        source_text_search_query=query,
    )


def review_score_status(row: Mapping[str, str]) -> str:
    available = (row.get("review_available", "") or "").strip().lower()
    if available == "no":
        return "unavailable"
    if available == "partial":
        return "partial"
    if available != "yes":
        return "unknown"
    scores = (row.get("review_scores", "") or "").strip()
    mean = (row.get("review_score_mean", "") or "").strip()
    reviewers = (row.get("review_num_reviewers", "") or "").strip()
    if scores or mean:
        return "complete"
    if reviewers and reviewers != "0":
        return "no_scores"
    return "no_reviews"
