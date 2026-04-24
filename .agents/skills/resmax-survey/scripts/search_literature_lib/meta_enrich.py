"""Enrich candidate papers with abstract and PDF link from multiple sources.

Multi-source enrichment strategy (in priority order):

  1. Existing fields from accepted_index (already populated)
  2. Derive PDF URL from arxiv_id / arxiv_url / paper_link / openreview_forum_id
  3. arXiv API — by arxiv_id (exact match)
  4. arXiv search — fuzzy title search (handles title variations between arXiv and venue)
  5. Semantic Scholar API — fuzzy title search (broad coverage, includes PDF links)

Fuzzy title search strategy:
  - Normalize title: lowercase, strip accents, collapse whitespace, remove special chars
  - Query arXiv/S2 with cleaned title
  - Verify match by comparing normalized titles (Jaccard similarity > 0.85)
  - This handles: minor title edits between submission and camera-ready,
    special characters (e.g. "3D-GS" vs "3D GS"), and Unicode issues
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional

from .models import CandidatePaper
from .filter_logger import FilterLog
from data_contracts import derive_source_text_contract


# ---------------------------------------------------------------------------
# Title normalization and fuzzy matching
# ---------------------------------------------------------------------------

def _normalize_title(title: str) -> str:
    """Normalize a title for fuzzy comparison.

    Strips accents, lowercases, removes non-alphanumeric chars, collapses spaces.
    """
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _title_similarity(a: str, b: str) -> float:
    """Jaccard similarity on word sets of normalized titles."""
    wa = set(_normalize_title(a).split())
    wb = set(_normalize_title(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _is_title_match(query_title: str, candidate_title: str, threshold: float = 0.80) -> bool:
    """Check if two titles refer to the same paper, tolerating minor edits."""
    sim = _title_similarity(query_title, candidate_title)
    if sim >= threshold:
        return True
    # Also check containment for cases like "Title" vs "Title: Extended Version"
    nq = _normalize_title(query_title)
    nc = _normalize_title(candidate_title)
    if nq in nc or nc in nq:
        return True
    return False


# ---------------------------------------------------------------------------
# URL derivation (no network, fast)
# ---------------------------------------------------------------------------

def _arxiv_id_from_url(url: str) -> str:
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)', url)
    return m.group(1) if m else ""


def _derive_pdf_url(paper: CandidatePaper) -> str:
    """Try to derive a PDF URL from existing fields without network calls."""
    if paper.pdf_url:
        return paper.pdf_url

    if paper.arxiv_id:
        return f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf"

    if paper.arxiv_url:
        aid = _arxiv_id_from_url(paper.arxiv_url)
        if aid:
            return f"https://arxiv.org/pdf/{aid}.pdf"

    if paper.openreview_forum_id:
        return f"https://openreview.net/pdf?id={paper.openreview_forum_id}"

    if paper.paper_link:
        link = paper.paper_link
        if "openreview.net/forum" in link:
            forum_id = re.search(r'id=([^&]+)', link)
            if forum_id:
                return f"https://openreview.net/pdf?id={forum_id.group(1)}"
        if link.endswith(".pdf"):
            return link
        # CVF open access
        if "openaccess.thecvf.com" in link and "/html/" in link:
            return link.replace("/html/", "/papers/").replace("_paper.html", "_paper.pdf")
        # AAAI OJS: /article/view/XXXXX/XXXXX is already a PDF
        if "ojs.aaai.org" in link and "/article/view/" in link:
            m = re.search(r'/article/view/\d+/\d+', link)
            if m:
                return link  # This URL directly serves PDF

    return ""


# ---------------------------------------------------------------------------
# arXiv API: by ID and by title search
# ---------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "resmax/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _parse_arxiv_entry(xml_body: str) -> dict:
    """Parse first <entry> from arXiv API XML response."""
    abstract = ""
    m = re.search(r'<summary>(.*?)</summary>', xml_body, re.S)
    if m:
        abstract = re.sub(r'\s+', ' ', m.group(1)).strip()

    title = ""
    m = re.search(r'<entry>.*?<title>(.*?)</title>', xml_body, re.S)
    if m:
        title = re.sub(r'\s+', ' ', m.group(1)).strip()

    arxiv_id = ""
    m = re.search(r'<id>http://arxiv\.org/abs/(\d{4}\.\d{4,5}(?:v\d+)?)</id>', xml_body)
    if m:
        arxiv_id = m.group(1)

    pdf_url = ""
    m = re.search(r'<link[^>]*title="pdf"[^>]*href="([^"]+)"', xml_body)
    if m:
        pdf_url = m.group(1)
    elif arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    return {"title": title, "abstract": abstract, "arxiv_id": arxiv_id, "pdf_url": pdf_url}


def _fetch_arxiv_by_id(arxiv_id: str, timeout: int = 15) -> dict:
    """Fetch metadata from arXiv API by exact ID."""
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}&max_results=1"
    try:
        body = _http_get(url, timeout)
        return _parse_arxiv_entry(body)
    except Exception:
        return {}


def _search_arxiv_by_title(title: str, timeout: int = 15) -> dict:
    """Search arXiv by title, return best match if title similarity is high enough."""
    # Stopwords to exclude from query — these hurt precision on arXiv search
    _STOPWORDS = {
        "a", "an", "the", "and", "or", "for", "of", "in", "on", "to", "at",
        "by", "is", "it", "its", "as", "be", "do", "if", "no", "not", "so",
        "up", "we", "our", "via", "with", "from", "into", "that", "this",
        "than", "your", "how", "what", "when", "where", "which", "who",
        "can", "are", "was", "were", "been", "has", "have", "had",
        "but", "yet", "also", "more", "most", "very", "each", "every",
        "based", "using", "towards", "toward", "through", "between",
    }
    clean = _normalize_title(title)
    words = [w for w in clean.split() if len(w) > 2 and w not in _STOPWORDS]
    # Use at most 6 keywords — too many AND terms causes false negatives
    words = words[:6]
    if len(words) < 2:
        return {}
    query = "+AND+".join(f"ti:{w}" for w in words)
    url = f"http://export.arxiv.org/api/query?search_query={query}&max_results=5&sortBy=relevance"
    try:
        body = _http_get(url, timeout)
    except Exception:
        return {}

    # Parse all entries and find best title match
    entries = re.findall(r'<entry>(.*?)</entry>', body, re.S)
    best = {}
    best_sim = 0.0
    for entry_xml in entries:
        parsed = _parse_arxiv_entry(f"<entry>{entry_xml}</entry>")
        if parsed.get("title"):
            sim = _title_similarity(title, parsed["title"])
            if sim > best_sim:
                best_sim = sim
                best = parsed

    if best_sim >= 0.80 and best:
        return best
    return {}


# ---------------------------------------------------------------------------
# Semantic Scholar API: title search
# ---------------------------------------------------------------------------

def _search_semantic_scholar(title: str, timeout: int = 15) -> dict:
    """Search Semantic Scholar by title, return best match."""
    clean_title = re.sub(r'[^\w\s]', ' ', title)
    clean_title = re.sub(r'\s+', ' ', clean_title).strip()
    encoded = urllib.parse.quote(clean_title[:200])
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={encoded}&limit=3&fields=title,abstract,externalIds,openAccessPdf"
    )
    try:
        body = _http_get(url, timeout)
        data = json.loads(body)
    except Exception:
        return {}

    papers = data.get("data", [])
    best = {}
    best_sim = 0.0
    for p in papers:
        s2_title = p.get("title", "")
        sim = _title_similarity(title, s2_title)
        if sim > best_sim:
            best_sim = sim
            result = {"title": s2_title}
            if p.get("abstract"):
                result["abstract"] = p["abstract"]
            ext = p.get("externalIds", {})
            if ext.get("ArXiv"):
                result["arxiv_id"] = ext["ArXiv"]
                result["pdf_url"] = f"https://arxiv.org/pdf/{ext['ArXiv']}.pdf"
            elif p.get("openAccessPdf", {}).get("url"):
                result["pdf_url"] = p["openAccessPdf"]["url"]
            best = result
            best_sim = sim

    if best_sim >= 0.80 and best:
        return best
    return {}


# ---------------------------------------------------------------------------
# Main enrichment pipeline
# ---------------------------------------------------------------------------

def enrich_candidates(
    candidates: list[CandidatePaper],
    log: FilterLog | None = None,
    arxiv_delay: float = 0.5,
    s2_delay: float = 0.3,
) -> list[CandidatePaper]:
    """Enrich candidates with abstract and PDF link from multiple sources.

    Strategy per paper:
      1. Check existing fields
      2. Derive PDF URL from known IDs
      3. If missing abstract and has arxiv_id → arXiv API by ID
      4. If still missing abstract → arXiv title search (fuzzy)
      5. If still missing abstract → Semantic Scholar title search (fuzzy)
      6. If still missing PDF → try to derive from newly found arxiv_id

    Modifies candidates in-place and returns the same list.
    """
    enrich_log: list[dict] = []

    for i, p in enumerate(candidates):
        actions: list[str] = []

        # Step 1: Check existing
        p.has_abstract = bool(p.abstract_raw and p.abstract_raw.strip())
        pdf_url = _derive_pdf_url(p)
        if pdf_url:
            p.pdf_url = pdf_url
            p.has_pdf_link = True
        else:
            p.has_pdf_link = bool(p.pdf_url and p.pdf_url.strip())

        # Step 2: arXiv by ID (if we have arxiv_id but no abstract)
        if not p.has_abstract and (p.arxiv_id or p.arxiv_url):
            aid = p.arxiv_id or _arxiv_id_from_url(p.arxiv_url)
            if aid:
                try:
                    meta = _fetch_arxiv_by_id(aid)
                    if meta.get("abstract"):
                        p.abstract_raw = meta["abstract"]
                        p.has_abstract = True
                        actions.append(f"arXiv-ID({aid}): got abstract")
                    if meta.get("pdf_url") and not p.has_pdf_link:
                        p.pdf_url = meta["pdf_url"]
                        p.has_pdf_link = True
                        actions.append(f"arXiv-ID({aid}): got PDF")
                    if meta.get("arxiv_id") and not p.arxiv_id:
                        p.arxiv_id = meta["arxiv_id"]
                except Exception as e:
                    actions.append(f"arXiv-ID({aid}): ERROR {e}")
                time.sleep(arxiv_delay)

        # Step 3: arXiv title search (if still missing abstract)
        if not p.has_abstract and p.title:
            try:
                meta = _search_arxiv_by_title(p.title)
                if meta.get("abstract"):
                    p.abstract_raw = meta["abstract"]
                    p.has_abstract = True
                    actions.append(f"arXiv-search: matched '{meta.get('title', '')[:50]}'")
                if meta.get("arxiv_id") and not p.arxiv_id:
                    p.arxiv_id = meta["arxiv_id"]
                    p.arxiv_url = f"https://arxiv.org/abs/{meta['arxiv_id']}"
                if meta.get("pdf_url") and not p.has_pdf_link:
                    p.pdf_url = meta["pdf_url"]
                    p.has_pdf_link = True
                    actions.append("arXiv-search: got PDF")
            except Exception as e:
                actions.append(f"arXiv-search: ERROR {e}")
            time.sleep(arxiv_delay)

        # Step 4: Semantic Scholar title search (if still missing abstract)
        if not p.has_abstract and p.title:
            try:
                meta = _search_semantic_scholar(p.title)
                if meta.get("abstract"):
                    p.abstract_raw = meta["abstract"]
                    p.has_abstract = True
                    actions.append(f"S2-search: matched '{meta.get('title', '')[:50]}'")
                if meta.get("arxiv_id") and not p.arxiv_id:
                    p.arxiv_id = meta["arxiv_id"]
                    p.arxiv_url = f"https://arxiv.org/abs/{meta['arxiv_id']}"
                if meta.get("pdf_url") and not p.has_pdf_link:
                    p.pdf_url = meta["pdf_url"]
                    p.has_pdf_link = True
                    actions.append("S2-search: got PDF")
            except Exception as e:
                actions.append(f"S2-search: ERROR {e}")
            time.sleep(s2_delay)

        # Step 5: Re-derive PDF if we got a new arxiv_id
        if not p.has_pdf_link:
            pdf_url = _derive_pdf_url(p)
            if pdf_url:
                p.pdf_url = pdf_url
                p.has_pdf_link = True
                actions.append("derived PDF from new arxiv_id")

        source_text = derive_source_text_contract({
            "paper_id": p.paper_id,
            "title": p.title,
            "venue": p.venue,
            "year": str(p.year),
            "source_type": p.source_type,
            "source_url": p.source_url,
            "paper_link": p.paper_link,
            "landing_url": p.landing_url,
            "pdf_url": p.pdf_url,
            "arxiv_id": p.arxiv_id,
            "arxiv_url": p.arxiv_url,
            "openreview_forum_id": p.openreview_forum_id,
        })
        p.source_text_status = source_text.source_text_status
        p.source_text_url = source_text.source_text_url
        p.source_text_source = source_text.source_text_source
        p.source_text_evidence = source_text.source_text_evidence
        p.source_text_search_query = source_text.source_text_search_query

        if actions:
            enrich_log.append({
                "idx": i + 1,
                "paper_id": p.paper_id,
                "title": p.title[:60],
                "actions": actions,
            })
            print(f"  [{i+1}/{len(candidates)}] {p.title[:50]} → {'; '.join(actions)}")

    # Summary
    has_abstract = sum(1 for p in candidates if p.has_abstract)
    has_pdf = sum(1 for p in candidates if p.has_pdf_link)
    missing_abstract = len(candidates) - has_abstract
    missing_pdf = len(candidates) - has_pdf

    print(f"[meta-enrich] abstract: {has_abstract}/{len(candidates)}, "
          f"PDF link: {has_pdf}/{len(candidates)}")

    if missing_abstract > 0:
        print(f"[meta-enrich] WARNING: {missing_abstract} papers still missing abstract:")
        for p in candidates:
            if not p.has_abstract:
                print(f"  - {p.paper_id}: {p.title[:60]}")

    if log:
        log.meta_has_abstract = has_abstract
        log.meta_has_pdf = has_pdf
        log.meta_missing_abstract = missing_abstract
        log.meta_missing_pdf = missing_pdf
        for entry in enrich_log:
            for action in entry["actions"]:
                if "ERROR" in action:
                    log.meta_errors.append(f"{entry['paper_id']}: {action}")

    return candidates
