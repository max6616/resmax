#!/usr/bin/env python3
"""Per-paper abstract fallback enrichment using asyncio concurrency.

Layer 3 strategy — guaranteed coverage for papers that Layer 2 (batch APIs) missed.
Processes only rows that still lack abstracts after enrich_abstracts.py.

Fallback chain per paper (stops at first success):
  Conference path:
    1. CVF OpenAccess page scrape (CVPR/ICCV — 100% reliable)
    2. AAAI OJS page scrape (AAAI — 100% reliable)
    3. ACM DL page scrape (KDD etc. with DOI)
  Journal fast path (auto-routed by venue):
    J1. JMLR abs page scrape (JMLR — 100% reliable, ~20/s)
    J2. CrossRef DOI lookup (IEEE/Elsevier journals with DOI)
    J3. S2 DOI lookup (bridge for journals with DOI)
  Generic path (all venues):
    4. OpenAlex title search → S2 DOI bridge if no abstract
    5. CrossRef title search → S2 DOI bridge if no abstract
    6. S2 title search
    7. arXiv title search
    8. Google search via SerpAPI (final fallback, budget-limited)
    9. Direct Google Scholar HTML scrape (free, no API key needed)

Usage:
  python3 enrich_abstracts_fallback.py --csv paper_database/accepted_index.csv
  python3 enrich_abstracts_fallback.py --csv paper_database/accepted_index.csv --filter CVPR --concurrency 15
  python3 enrich_abstracts_fallback.py --csv paper_database/accepted_index.csv --dry-run
"""
from __future__ import annotations

import asyncio
import csv
import html as html_module
import json
import re
import shutil
import sys
import time
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Optional

try:
    import aiohttp
except ImportError:
    print("[ERROR] aiohttp is required: pip install aiohttp", file=sys.stderr)
    sys.exit(1)

# Load shared secrets / local-config (sources .secrets/*.env and .localconfig/*.env).
# File path: .cursor/skills/resmax-database/scripts/enrich_abstracts_fallback.py
# parents: [0]=scripts, [1]=resmax-database, [2]=skills
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
sys.path.insert(0, str(_SHARED))
from secrets_loader import get_secret  # noqa: E402


def _contact_email() -> str:
    """Contact email advertised in the User-Agent header to polite APIs.

    OpenAlex and Crossref request a mailto in User-Agent to route callers
    to their fast polite pool. Configured via RESMAX_CONTACT_EMAIL in
    `.secrets/contact.env`; falls back to a generic placeholder so the
    scripts still run end-to-end when the user has not set one.
    """
    return get_secret(
        "RESMAX_CONTACT_EMAIL",
        env_file=".secrets/contact.env",
        default="resmax@example.com",
    ) or "resmax@example.com"


# ---------------------------------------------------------------------------
# Title normalization (shared with meta_enrich.py)
# ---------------------------------------------------------------------------

def _normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _title_similarity(a: str, b: str) -> float:
    wa = set(_normalize_title(a).split())
    wb = set(_normalize_title(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _is_title_match(query: str, candidate: str, threshold: float = 0.80) -> bool:
    if _title_similarity(query, candidate) >= threshold:
        return True
    nq, nc = _normalize_title(query), _normalize_title(candidate)
    if nq in nc or nc in nq:
        return True
    nq_nospace = nq.replace(" ", "")
    nc_nospace = nc.replace(" ", "")
    if nq_nospace == nc_nospace:
        return True
    if len(nq_nospace) > 10 and len(nc_nospace) > 10:
        if nq_nospace in nc_nospace or nc_nospace in nq_nospace:
            return True
    return False


# ---------------------------------------------------------------------------
# Source 1: CVF OpenAccess page scrape
# ---------------------------------------------------------------------------

async def _fetch_cvf_abstract(session: aiohttp.ClientSession, paper_link: str) -> Optional[str]:
    """Scrape abstract from CVF OpenAccess individual paper HTML page."""
    html_url = paper_link
    if "/papers/" in html_url and html_url.endswith(".pdf"):
        html_url = html_url.replace("/papers/", "/html/").replace("_paper.pdf", "_paper.html")
    elif not html_url.endswith(".html"):
        return None

    if "openaccess.thecvf.com" not in html_url:
        return None

    try:
        async with session.get(html_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()
            m = re.search(r'<div id="abstract">\s*(.*?)\s*</div>', text, re.S)
            if m:
                abstract = re.sub(r"<[^>]+>", "", m.group(1))
                abstract = re.sub(r"\s+", " ", abstract).strip()
                return abstract if len(abstract) > 20 else None
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Source 2: AAAI OJS page scrape
# ---------------------------------------------------------------------------

async def _fetch_aaai_abstract(session: aiohttp.ClientSession, paper_link: str) -> Optional[str]:
    """Scrape abstract from AAAI OJS individual article page."""
    m = re.search(r"ojs\.aaai\.org/index\.php/AAAI/article/view/(\d+)", paper_link)
    if not m:
        return None
    article_url = f"https://ojs.aaai.org/index.php/AAAI/article/view/{m.group(1)}"

    try:
        async with session.get(article_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()
            m2 = re.search(r'<section class="item abstract">(.*?)</section>', text, re.S)
            if m2:
                abstract = re.sub(r"<[^>]+>", "", m2.group(1))
                abstract = re.sub(r"\s+", " ", abstract).strip()
                if abstract.lower().startswith("abstract"):
                    abstract = abstract[8:].strip()
                return abstract if len(abstract) > 20 else None
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Source 3: arXiv title search
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "of", "in", "on", "to", "at",
    "by", "is", "it", "its", "as", "be", "do", "if", "no", "not", "so",
    "up", "we", "our", "via", "with", "from", "into", "that", "this",
    "than", "your", "how", "what", "when", "where", "which", "who",
    "can", "are", "was", "were", "been", "has", "have", "had",
    "but", "yet", "also", "more", "most", "very", "each", "every",
    "based", "using", "towards", "toward", "through", "between",
}


async def _search_arxiv(session: aiohttp.ClientSession, title: str) -> Optional[dict]:
    clean = _normalize_title(title)
    words = [w for w in clean.split() if len(w) > 2 and w not in _STOPWORDS][:6]
    if len(words) < 2:
        return None
    query = "+AND+".join(f"ti:{w}" for w in words)
    url = f"http://export.arxiv.org/api/query?search_query={query}&max_results=5&sortBy=relevance"

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            body = await resp.text()
    except Exception:
        return None

    best, best_sim = None, 0.0
    for entry in re.findall(r"<entry>(.*?)</entry>", body, re.S):
        t_m = re.search(r"<title>(.*?)</title>", entry, re.S)
        a_m = re.search(r"<summary>(.*?)</summary>", entry, re.S)
        id_m = re.search(r"<id>http://arxiv\.org/abs/(\d{4}\.\d{4,5})", entry)
        if t_m and a_m:
            cand_title = re.sub(r"\s+", " ", t_m.group(1)).strip()
            sim = _title_similarity(title, cand_title)
            if sim > best_sim:
                best_sim = sim
                abstract = re.sub(r"\s+", " ", a_m.group(1)).strip()
                best = {
                    "abstract": abstract,
                    "title": cand_title,
                    "arxiv_id": id_m.group(1) if id_m else "",
                }

    return best if best_sim >= 0.80 and best else None


# ---------------------------------------------------------------------------
# Source 4: Semantic Scholar title search
# ---------------------------------------------------------------------------

async def _search_s2(session: aiohttp.ClientSession, title: str) -> Optional[dict]:
    clean = re.sub(r"[^\w\s]", " ", title)
    clean = re.sub(r"\s+", " ", clean).strip()[:200]
    encoded = urllib.parse.quote(clean)
    url = (f"https://api.semanticscholar.org/graph/v1/paper/search"
           f"?query={encoded}&limit=3&fields=title,abstract,externalIds,openAccessPdf")

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception:
        return None

    best, best_sim = None, 0.0
    for p in data.get("data", []):
        sim = _title_similarity(title, p.get("title", ""))
        if sim > best_sim:
            best_sim = sim
            result = {"title": p.get("title", "")}
            if p.get("abstract"):
                result["abstract"] = p["abstract"]
            ext = p.get("externalIds", {})
            if ext.get("ArXiv"):
                result["arxiv_id"] = ext["ArXiv"]
            if ext.get("DOI"):
                result["doi"] = ext["DOI"]
            best = result

    return best if best_sim >= 0.80 and best and best.get("abstract") else None


# ---------------------------------------------------------------------------
# Source 5: OpenAlex title search
# ---------------------------------------------------------------------------

async def _search_openalex(session: aiohttp.ClientSession, title: str) -> Optional[dict]:
    encoded = urllib.parse.quote(title[:200])
    url = (f"https://api.openalex.org/works?search={encoded}"
           f"&per_page=3&select=id,title,abstract_inverted_index,doi")

    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": f"mailto:{_contact_email()}"},
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception:
        return None

    for r in data.get("results", []):
        if not _is_title_match(title, r.get("title", "")):
            continue
        result: dict = {"title": r.get("title", "")}

        raw_doi = r.get("doi", "")
        if raw_doi:
            doi = re.sub(r"^https?://doi\.org/", "", raw_doi)
            result["doi"] = doi

        aii = r.get("abstract_inverted_index")
        if aii:
            word_positions = []
            for word, positions in aii.items():
                for pos in positions:
                    word_positions.append((pos, word))
            word_positions.sort()
            abstract = " ".join(w for _, w in word_positions)
            if len(abstract) > 20:
                result["abstract"] = abstract

        return result if result.get("abstract") or result.get("doi") else None

    return None


# ---------------------------------------------------------------------------
# Source 6: ACM Digital Library page scrape (KDD etc.)
# ---------------------------------------------------------------------------

async def _fetch_acm_abstract(session: aiohttp.ClientSession, doi: str) -> Optional[str]:
    """Scrape abstract from ACM DL page using DOI."""
    if not doi:
        return None
    url = f"https://dl.acm.org/doi/{doi}"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
        ) as resp:
            if resp.status != 200:
                return None
            text = await resp.text()
            m = re.search(
                r'<section[^>]*class="[^"]*abstract[^"]*"[^>]*>(.*?)</section>',
                text, re.S,
            )
            if not m:
                m = re.search(r'<div\s+class="abstractSection[^"]*"[^>]*>(.*?)</div>', text, re.S)
            if m:
                abstract = re.sub(r"<[^>]+>", " ", m.group(1))
                abstract = re.sub(r"\s+", " ", abstract).strip()
                return abstract if len(abstract) > 20 else None
    except Exception:
        return None
    return None


def _extract_doi_from_link(paper_link: str) -> str:
    """Extract DOI from paper_link URL."""
    m = re.match(r"https?://doi\.org/(10\.\d{4,}/[^\s,]+)", paper_link)
    if m:
        return m.group(1)
    m = re.search(r"https?://dl\.acm\.org/doi/(10\.\d{4,}/[^\s,?#]+)", paper_link)
    if m:
        return m.group(1)
    return ""


# ---------------------------------------------------------------------------
# Source 7: S2 DOI direct lookup (bridge from OpenAlex DOI discovery)
# ---------------------------------------------------------------------------

async def _s2_doi_lookup(session: aiohttp.ClientSession, doi: str) -> Optional[dict]:
    """Fetch abstract from S2 using a known DOI (not search, direct lookup)."""
    if not doi:
        return None
    url = (f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}"
           f"?fields=title,abstract,externalIds")
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            result: dict = {}
            if data.get("abstract"):
                result["abstract"] = data["abstract"]
            ext = data.get("externalIds", {})
            if ext.get("ArXiv"):
                result["arxiv_id"] = ext["ArXiv"]
            if ext.get("DOI"):
                result["doi"] = ext["DOI"]
            return result if result.get("abstract") else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Source 8: CrossRef title search (DOI authority, often has abstracts)
# ---------------------------------------------------------------------------

def _clean_jats_xml(text: str) -> str:
    """Strip JATS XML tags from CrossRef abstract."""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


async def _search_crossref(session: aiohttp.ClientSession, title: str) -> Optional[dict]:
    """Search CrossRef by title. Returns {abstract, doi, title} if matched."""
    clean = re.sub(r"[^\w\s]", " ", title)
    clean = re.sub(r"\s+", " ", clean).strip()[:200]
    encoded = urllib.parse.quote(clean)
    url = (f"https://api.crossref.org/works?query.title={encoded}"
           f"&rows=3&select=DOI,title,abstract")

    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={"User-Agent": f"mailto:{_contact_email()}"},
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception:
        return None

    for item in data.get("message", {}).get("items", []):
        cand_title = (item.get("title") or [""])[0]
        cand_title = _clean_jats_xml(cand_title)
        if not _is_title_match(title, cand_title):
            continue
        result: dict = {"title": cand_title}
        if item.get("DOI"):
            result["doi"] = item["DOI"]
        raw_abstract = item.get("abstract", "")
        if raw_abstract:
            abstract = _clean_jats_xml(raw_abstract)
            if len(abstract) > 20:
                result["abstract"] = abstract
        return result if result.get("abstract") or result.get("doi") else None

    return None


# ---------------------------------------------------------------------------
# Source 9: Google search via SerpAPI (final fallback)
# ---------------------------------------------------------------------------

async def _search_google_abstract(
    session: aiohttp.ClientSession, title: str, serpapi_key: str,
) -> Optional[dict]:
    """Use SerpAPI Google search to find paper abstract as last resort.

    Strategy: search "<title> abstract" and parse snippets / knowledge graph.
    If we find a DOI in the results, also try S2 DOI lookup.
    """
    if not serpapi_key:
        return None

    query = f'"{title}" abstract'
    encoded = urllib.parse.quote(query)
    url = (f"https://serpapi.com/search.json?q={encoded}"
           f"&api_key={serpapi_key}&num=5&hl=en")

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception:
        return None

    result: dict = {}

    # Check knowledge graph
    kg = data.get("knowledge_graph", {})
    if kg.get("description") and _is_title_match(title, kg.get("title", "")):
        desc = kg["description"]
        if len(desc) > 50:
            result["abstract"] = desc

    # Check organic results for DOI links and snippets
    for item in data.get("organic_results", [])[:5]:
        link = item.get("link", "")
        snippet = item.get("snippet", "")

        doi_m = re.search(r"doi\.org/(10\.\d{4,}/[^\s,\"]+)", link)
        if not doi_m:
            doi_m = re.search(r"dl\.acm\.org/doi/(10\.\d{4,}/[^\s,\"?#]+)", link)
        if doi_m and not result.get("doi"):
            result["doi"] = doi_m.group(1)

        if (not result.get("abstract") and snippet
                and len(snippet) > 80
                and _title_similarity(title, item.get("title", "")) > 0.3):
            result["abstract"] = snippet

    return result if result.get("abstract") or result.get("doi") else None


# ---------------------------------------------------------------------------
# Source 10: Direct Google Scholar HTML scrape (free, no API key)
# ---------------------------------------------------------------------------

async def _search_google_scholar_direct(
    session: aiohttp.ClientSession, title: str,
) -> Optional[dict]:
    """Scrape Google Scholar search results directly (no API key needed).

    Strategy: search exact title on Google Scholar, parse result snippets
    and follow links to arXiv/S2/ACM pages to extract abstract.
    Rate-limited to avoid blocks.
    """
    query = urllib.parse.quote(f'"{title}"')
    url = f"https://scholar.google.com/scholar?q={query}&hl=en"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                return None
            html_text = await resp.text()
    except Exception:
        return None

    result: dict = {}

    gs_snippet_pattern = re.compile(
        r'<div class="gs_rs">(.*?)</div>', re.DOTALL
    )
    gs_title_pattern = re.compile(
        r'<h3 class="gs_rt"[^>]*>(.*?)</h3>', re.DOTALL
    )
    gs_link_pattern = re.compile(r'href="(https?://[^"]+)"')

    titles_found = gs_title_pattern.findall(html_text)
    snippets_found = gs_snippet_pattern.findall(html_text)

    for i, (gs_title_html, snippet_html) in enumerate(zip(titles_found, snippets_found)):
        gs_title_clean = re.sub(r'<[^>]+>', '', gs_title_html).strip()
        if _title_similarity(title, gs_title_clean) < 0.5:
            continue

        snippet_clean = re.sub(r'<[^>]+>', '', snippet_html).strip()
        snippet_clean = re.sub(r'\s+', ' ', snippet_clean)
        if len(snippet_clean) > 80:
            result["abstract"] = snippet_clean
            break

        links_in_title = gs_link_pattern.findall(gs_title_html)
        for link in links_in_title:
            if "arxiv.org/abs/" in link:
                arxiv_m = re.search(r'arxiv\.org/abs/(\d{4}\.\d{4,5})', link)
                if arxiv_m:
                    result["arxiv_id"] = arxiv_m.group(1)
            elif "doi.org/" in link:
                doi_m = re.search(r'doi\.org/(10\.\d{4,}/[^\s,"]+)', link)
                if doi_m:
                    result["doi"] = doi_m.group(1)
        break

    return result if result.get("abstract") or result.get("arxiv_id") or result.get("doi") else None


# ---------------------------------------------------------------------------
# Journal fast-path sources
# ---------------------------------------------------------------------------

JOURNAL_VENUES = frozenset({"TPAMI", "IJCV", "JMLR", "AIJ", "TNNLS"})
OPENALEX_SKIP_VENUES = frozenset({"IJCV", "JMLR"})


async def _fetch_jmlr_abstract(
    session: aiohttp.ClientSession, paper_link: str,
) -> Optional[str]:
    """Fetch abstract from JMLR abs page derived from the PDF link.

    PDF:  https://jmlr.org/papers/volume25/23-078/23-078.pdf
    Abs:  https://jmlr.org/papers/v25/23-078.html
    """
    m = re.match(r"https?://jmlr\.org/papers/volume(\d+)/([^/]+)/", paper_link)
    if not m:
        return None
    vol, paper_id = m.group(1), m.group(2)
    abs_url = f"https://jmlr.org/papers/v{vol}/{paper_id}.html"
    try:
        async with session.get(abs_url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()
        am = re.search(r'<p\s+class="abstract">\s*(.*?)\s*</p>', html, re.S)
        if am:
            text = re.sub(r"<[^>]+>", " ", am.group(1))
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 30:
                return text
    except Exception:
        pass
    return None


async def _fetch_springer_abstract(
    session: aiohttp.ClientSession, doi: str,
) -> Optional[str]:
    """Fetch abstract from Springer article page via dc.description meta tag."""
    url = f"https://link.springer.com/article/{doi}"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=20),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html",
            },
        ) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()
        m = re.search(
            r'<meta\s+name="dc\.description"\s+content="([^"]+)"', html, re.I
        )
        if m:
            text = re.sub(r"\s+", " ", html_module.unescape(m.group(1))).strip()
            if len(text) > 30:
                return text
    except Exception:
        pass
    return None


async def _fetch_crossref_abstract_by_doi(
    session: aiohttp.ClientSession, doi: str,
) -> Optional[str]:
    """Fetch abstract directly from CrossRef by DOI (no title search needed)."""
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='')}"
    try:
        async with session.get(
            url,
            headers={"Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
        abstract = data.get("message", {}).get("abstract", "")
        if abstract:
            text = re.sub(r"<[^>]+>", " ", abstract)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 30:
                return text
    except Exception:
        pass
    return None


async def _enrich_one(
    session: aiohttp.ClientSession,
    row: dict,
    semaphores: dict[str, asyncio.Semaphore],
    dry_run: bool,
    serpapi_key: str = "",
    serpapi_budget: Optional[list] = None,
) -> str:
    """Try all fallback sources for one paper. Returns source name or empty.

    Auto-routes journal papers through a fast path before the generic chain.
    serpapi_budget is a mutable single-element list [remaining_count] for
    global budget tracking across concurrent tasks.
    """
    title = row.get("title", "").strip()
    venue = row.get("venue", "").upper()
    paper_link = row.get("paper_link", "")

    def _apply_doi(doi: str) -> None:
        if doi and not row.get("doi", "").strip() and not dry_run:
            row["doi"] = doi

    def _apply_arxiv(arxiv_id: str) -> None:
        if arxiv_id and not row.get("arxiv_id", "").strip() and not dry_run:
            row["arxiv_id"] = arxiv_id
            row["arxiv_url"] = f"https://arxiv.org/abs/{arxiv_id}"

    # Source 1: CVF page
    if venue in ("CVPR", "ICCV") and "openaccess.thecvf.com" in paper_link:
        async with semaphores["cvf"]:
            result = await _fetch_cvf_abstract(session, paper_link)
            if result:
                if not dry_run:
                    row["abstract_raw"] = result
                return "cvf_page"
            await asyncio.sleep(0.1)

    # Source 2: AAAI page
    if venue == "AAAI" and "ojs.aaai.org" in paper_link:
        async with semaphores["aaai"]:
            result = await _fetch_aaai_abstract(session, paper_link)
            if result:
                if not dry_run:
                    row["abstract_raw"] = result
                return "aaai_page"
            await asyncio.sleep(0.2)

    # Source 3: ACM DL page (KDD and other ACM venues)
    doi = row.get("doi", "").strip() or _extract_doi_from_link(paper_link)
    if doi and ("acm" in paper_link.lower() or doi.startswith("10.1145/")):
        async with semaphores["acm"]:
            result = await _fetch_acm_abstract(session, doi)
            if result:
                if not dry_run:
                    row["abstract_raw"] = result
                _apply_doi(doi)
                return "acm_page"
            await asyncio.sleep(0.2)

    # ---- Journal fast path (auto-routed by venue) ----
    if venue in JOURNAL_VENUES:
        # J1: JMLR — scrape official abs page (~20/s, 100% reliable)
        if venue == "JMLR" and "jmlr.org" in paper_link:
            async with semaphores["jmlr"]:
                abstract = await _fetch_jmlr_abstract(session, paper_link)
                if abstract:
                    if not dry_run:
                        row["abstract_raw"] = abstract
                    return "jmlr_abs_page"
                await asyncio.sleep(0.05)

        # J1b: Springer page scrape (IJCV — dc.description meta tag)
        j_doi = row.get("doi", "").strip()
        if venue == "IJCV" and j_doi and j_doi.startswith("10.1007/"):
            async with semaphores["springer"]:
                abstract = await _fetch_springer_abstract(session, j_doi)
                if abstract:
                    if not dry_run:
                        row["abstract_raw"] = abstract
                    return "springer_page"
                await asyncio.sleep(0.5)

        # J2: CrossRef DOI lookup (IEEE/Elsevier journals — fast, ~10/s)
        if not j_doi:
            j_doi = row.get("doi", "").strip()
        if j_doi and venue not in ("JMLR", "IJCV"):
            async with semaphores["crossref"]:
                abstract = await _fetch_crossref_abstract_by_doi(session, j_doi)
                if abstract:
                    if not dry_run:
                        row["abstract_raw"] = abstract
                    return "crossref_doi_direct"
                await asyncio.sleep(0.1)

            # J3: S2 DOI lookup (bridge)
            async with semaphores["s2"]:
                result = await _s2_doi_lookup(session, j_doi)
                if result and result.get("abstract"):
                    if not dry_run:
                        row["abstract_raw"] = result["abstract"]
                    _apply_arxiv(result.get("arxiv_id", ""))
                    return "s2_doi_direct"
                await asyncio.sleep(0.2)

    # Source 4: OpenAlex title search → S2 DOI bridge
    # Skip for venues where OpenAlex is known to lack abstracts
    discovered_doi = ""
    if title and venue not in OPENALEX_SKIP_VENUES:
        async with semaphores["openalex"]:
            result = await _search_openalex(session, title)
            if result and result.get("abstract"):
                if not dry_run:
                    row["abstract_raw"] = result["abstract"]
                _apply_doi(result.get("doi", ""))
                return "openalex_search"
            if result and result.get("doi"):
                discovered_doi = result["doi"]
            await asyncio.sleep(0.05)

        if discovered_doi:
            async with semaphores["s2"]:
                result = await _s2_doi_lookup(session, discovered_doi)
                if result and result.get("abstract"):
                    if not dry_run:
                        row["abstract_raw"] = result["abstract"]
                    _apply_doi(discovered_doi)
                    _apply_arxiv(result.get("arxiv_id", ""))
                    return "openalex_doi_bridge"
                await asyncio.sleep(1.0)

    # Source 5: CrossRef title search → S2 DOI bridge
    if title:
        async with semaphores["crossref"]:
            result = await _search_crossref(session, title)
            if result and result.get("abstract"):
                if not dry_run:
                    row["abstract_raw"] = result["abstract"]
                _apply_doi(result.get("doi", ""))
                return "crossref_search"
            crossref_doi = result.get("doi", "") if result else ""
            await asyncio.sleep(0.5)

        if crossref_doi and crossref_doi != discovered_doi:
            async with semaphores["s2"]:
                result = await _s2_doi_lookup(session, crossref_doi)
                if result and result.get("abstract"):
                    if not dry_run:
                        row["abstract_raw"] = result["abstract"]
                    _apply_doi(crossref_doi)
                    _apply_arxiv(result.get("arxiv_id", ""))
                    return "crossref_doi_bridge"
                await asyncio.sleep(1.0)

    # Source 6: S2 title search
    if title:
        async with semaphores["s2"]:
            result = await _search_s2(session, title)
            if result and result.get("abstract"):
                if not dry_run:
                    row["abstract_raw"] = result["abstract"]
                _apply_arxiv(result.get("arxiv_id", ""))
                _apply_doi(result.get("doi", ""))
                return "s2_search"
            await asyncio.sleep(1.0)

    # Source 7: arXiv title search
    if title:
        async with semaphores["arxiv"]:
            result = await _search_arxiv(session, title)
            if result and result.get("abstract"):
                if not dry_run:
                    row["abstract_raw"] = result["abstract"]
                _apply_arxiv(result.get("arxiv_id", ""))
                return "arxiv_search"
            await asyncio.sleep(3.0)

    # Source 8: Google search via SerpAPI (final fallback, budget-limited)
    if title and serpapi_key and (serpapi_budget is None or serpapi_budget[0] > 0):
        if serpapi_budget is not None:
            serpapi_budget[0] -= 1
        async with semaphores["google"]:
            result = await _search_google_abstract(session, title, serpapi_key)
            if result:
                google_doi = result.get("doi", "")
                if result.get("abstract"):
                    if not dry_run:
                        row["abstract_raw"] = result["abstract"]
                    _apply_doi(google_doi)
                    return "google_search"
                # Google found DOI but no abstract → S2 DOI bridge
                if google_doi:
                    async with semaphores["s2"]:
                        s2_result = await _s2_doi_lookup(session, google_doi)
                        if s2_result and s2_result.get("abstract"):
                            if not dry_run:
                                row["abstract_raw"] = s2_result["abstract"]
                            _apply_doi(google_doi)
                            _apply_arxiv(s2_result.get("arxiv_id", ""))
                            return "google_doi_bridge"
                        await asyncio.sleep(1.0)
            await asyncio.sleep(0.5)

    # Source 9: Direct Google Scholar HTML scrape (free, no API key)
    if title:
        async with semaphores["google"]:
            result = await _search_google_scholar_direct(session, title)
            if result:
                if result.get("abstract"):
                    if not dry_run:
                        row["abstract_raw"] = result["abstract"]
                    _apply_arxiv(result.get("arxiv_id", ""))
                    _apply_doi(result.get("doi", ""))
                    return "google_scholar_direct"
                # Found arxiv_id or DOI but no abstract → bridge via S2
                bridge_arxiv = result.get("arxiv_id", "")
                bridge_doi = result.get("doi", "")
                if bridge_arxiv:
                    async with semaphores["s2"]:
                        s2_result = await _s2_doi_lookup(session, bridge_arxiv)
                        if s2_result and s2_result.get("abstract"):
                            if not dry_run:
                                row["abstract_raw"] = s2_result["abstract"]
                            _apply_arxiv(bridge_arxiv)
                            return "scholar_arxiv_bridge"
                        await asyncio.sleep(1.0)
                if bridge_doi:
                    async with semaphores["s2"]:
                        s2_result = await _s2_doi_lookup(session, bridge_doi)
                        if s2_result and s2_result.get("abstract"):
                            if not dry_run:
                                row["abstract_raw"] = s2_result["abstract"]
                            _apply_doi(bridge_doi)
                            return "scholar_doi_bridge"
                        await asyncio.sleep(1.0)
            await asyncio.sleep(5.0)

    return ""


async def run_enrichment(rows: list[dict], targets: list[int],
                         concurrency: int, dry_run: bool,
                         serpapi_key: str = "",
                         serpapi_budget_limit: int = 0) -> dict[str, int]:
    """Run async enrichment on target rows. Returns source -> count mapping."""
    semaphores = {
        "cvf": asyncio.Semaphore(concurrency),
        "aaai": asyncio.Semaphore(max(concurrency // 2, 3)),
        "acm": asyncio.Semaphore(max(concurrency // 2, 5)),
        "openalex": asyncio.Semaphore(min(concurrency, 15)),
        "crossref": asyncio.Semaphore(min(concurrency, 10)),
        "s2": asyncio.Semaphore(2),
        "arxiv": asyncio.Semaphore(1),
        "google": asyncio.Semaphore(3),
        "jmlr": asyncio.Semaphore(min(concurrency, 20)),
        "springer": asyncio.Semaphore(min(concurrency, 5)),
    }

    serpapi_budget: Optional[list] = None
    if serpapi_budget_limit > 0:
        serpapi_budget = [serpapi_budget_limit]
        print(f"[fallback] SerpAPI budget: {serpapi_budget_limit} searches", flush=True)

    source_counts: dict[str, int] = {}
    completed = 0
    total = len(targets)
    start_time = time.time()

    async with aiohttp.ClientSession(
        headers={"User-Agent": f"resmax/1.0; mailto:{_contact_email()}"},
        connector=aiohttp.TCPConnector(limit=concurrency + 10),
    ) as session:

        async def _process(idx: int) -> None:
            nonlocal completed
            source = await _enrich_one(
                session, rows[idx], semaphores, dry_run, serpapi_key,
                serpapi_budget=serpapi_budget,
            )
            completed += 1
            if source:
                source_counts[source] = source_counts.get(source, 0) + 1

            report_interval = max(1, min(50, total // 5))
            if completed % report_interval == 0 or completed == total:
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                enriched_so_far = sum(source_counts.values())
                eta = (total - completed) / rate if rate > 0 else 0
                budget_str = ""
                if serpapi_budget is not None:
                    budget_str = f" serpapi_left={serpapi_budget[0]}"
                print(f"  [{completed}/{total}] enriched={enriched_so_far} "
                      f"rate={rate:.1f}/s ETA={eta:.0f}s "
                      f"sources={dict(source_counts)}{budget_str}",
                      flush=True)

        tasks = [_process(idx) for idx in targets]
        await asyncio.gather(*tasks)

    return source_counts


def main():
    import argparse
    import os
    p = argparse.ArgumentParser(description="Per-paper abstract fallback (Layer 3)")
    p.add_argument("--csv", required=True)
    p.add_argument("--filter", default="")
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--serpapi-key", default="",
                   help="SerpAPI key for Google search fallback (or set SERPAPI_KEY env var)")
    p.add_argument("--serpapi-budget", type=int, default=0,
                   help="Max SerpAPI searches (0 = unlimited). Protects limited quotas.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    serpapi_key = args.serpapi_key or os.environ.get("SERPAPI_KEY", "")

    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        print(f"[ERROR] CSV not found: {csv_path}", file=sys.stderr)
        return 1

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    print(f"[fallback] loaded {len(rows)} rows", flush=True)
    if serpapi_key:
        print(f"[fallback] SerpAPI Google search enabled", flush=True)
    else:
        print(f"[fallback] SerpAPI not configured (set --serpapi-key or SERPAPI_KEY)",
              flush=True)

    targets: list[int] = []
    for i, row in enumerate(rows):
        if args.filter and args.filter not in row.get("conf_year", ""):
            continue
        if not row.get("abstract_raw", "").strip():
            targets.append(i)

    print(f"[fallback] {len(targets)} papers still missing abstract", flush=True)
    if not targets:
        return 0

    venue_counts: dict[str, int] = {}
    for idx in targets:
        cy = rows[idx].get("conf_year", "UNKNOWN")
        venue_counts[cy] = venue_counts.get(cy, 0) + 1
    for cy in sorted(venue_counts):
        print(f"  {cy}: {venue_counts[cy]}", flush=True)

    print(f"\n[fallback] starting with concurrency={args.concurrency}...", flush=True)
    source_counts = asyncio.run(
        run_enrichment(rows, targets, args.concurrency, args.dry_run, serpapi_key,
                       serpapi_budget_limit=args.serpapi_budget)
    )

    total_enriched = sum(source_counts.values())
    still_missing = len(targets) - total_enriched
    print(f"\n[fallback] done: enriched={total_enriched}, still_missing={still_missing}",
          flush=True)
    print(f"  sources: {dict(source_counts)}", flush=True)

    if still_missing > 0:
        print(f"\n[fallback] papers still without abstract:", flush=True)
        count = 0
        for idx in targets:
            if not rows[idx].get("abstract_raw", "").strip():
                print(f"  - {rows[idx].get('conf_year','')}: {rows[idx].get('title','')[:80]}",
                      flush=True)
                count += 1
                if count >= 20:
                    print(f"  ... and {still_missing - 20} more", flush=True)
                    break

    if not args.dry_run and total_enriched > 0:
        backup = csv_path.with_suffix(".csv.bak")
        shutil.copy2(csv_path, backup)
        print(f"[fallback] backup: {backup}", flush=True)

        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"[fallback] wrote updated CSV: {csv_path}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
