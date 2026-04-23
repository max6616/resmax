"""Legal open-access PDF resolvers (Stage 5.5.a Layer 1-3).

When a paper's direct PDF URLs (Layer 0: pdf_url / arxiv_id / openreview_forum_id
/ doi) all fail, we ask OA-aware academic metadata services whether the author
has self-archived a legal copy anywhere (arXiv backup, author homepage,
institutional repo). This is the correct way to handle ACM/Springer/Elsevier
papers without fighting per-publisher anti-bot walls.

Priority (each layer returns 0+ candidate PDF URLs; caller unions in order):

    1. Unpaywall    — purpose-built for "is there a legal OA copy?"; needs
                      a contact email (set RESMAX_UNPAYWALL_EMAIL or accept
                      the default placeholder).
    2. OpenAlex     — large scholarly graph with per-location pdf_url.
    3. Semantic S2  — openAccessPdf field (often agrees with Unpaywall).
    4. arXiv search — title-based lookup to recover missing arxiv_id.

None of these bypass Cloudflare; they *avoid* Cloudflare by locating alternate
legal hosts (author websites, mirrors, preprint archives).

Empirically observed for 4dgs_editing:
  * ICLR/ICML/NeurIPS papers without openreview_forum_id get recovered via
    OpenAlex locations.
  * ACM MM 2025 papers with no author self-archive are correctly classified
    by all three APIs as `is_oa = False`, so we can route them to the
    optional Sci-Hub fallback with confidence that no legal copy exists.
"""
from __future__ import annotations

import os
import re
import time
import urllib.parse
from typing import Optional

try:
    import requests  # type: ignore
    HAS_REQUESTS = True
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]
    HAS_REQUESTS = False


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
API_TIMEOUT = 15
# Unpaywall explicitly requires a contact email in the query string; a
# generic placeholder works for a handful of calls but real usage should
# set RESMAX_CONTACT_EMAIL via .secrets/contact.env so the polite-pool
# routing kicks in. RESMAX_UNPAYWALL_EMAIL is accepted as a legacy alias.
DEFAULT_EMAIL = (
    os.environ.get("RESMAX_CONTACT_EMAIL")
    or os.environ.get("RESMAX_UNPAYWALL_EMAIL")
    or "resmax@example.com"
)


def _json_get(url: str, *, timeout: int = API_TIMEOUT) -> tuple[Optional[dict], int, str]:
    """GET + JSON parse with uniform error reporting."""
    if not HAS_REQUESTS:
        return None, 0, "requests not installed"
    try:
        r = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None, r.status_code, f"HTTP {r.status_code}: {r.text[:120]}"
        return r.json(), 200, ""
    except Exception as e:
        return None, 0, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Layer 1: Unpaywall
# ---------------------------------------------------------------------------

def unpaywall_lookup(doi: str, *, email: Optional[str] = None) -> dict:
    """Query Unpaywall for legal OA copies of a DOI.

    Returns {ok, is_oa, pdf_urls (priority-ordered), evidence (str), error}.
    Empty doi is a fast no-op.
    """
    doi = (doi or "").strip()
    if not doi:
        return {"ok": False, "is_oa": None, "pdf_urls": [],
                "evidence": "no doi", "error": "no doi"}
    email = email or DEFAULT_EMAIL
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='')}?email={urllib.parse.quote(email)}"
    data, status, err = _json_get(url)
    if not data:
        return {"ok": False, "is_oa": None, "pdf_urls": [],
                "evidence": "", "error": f"unpaywall {status}: {err}"}

    is_oa = data.get("is_oa", False)
    pdf_urls: list[str] = []

    def _push(loc: dict):
        u = loc.get("url_for_pdf") or loc.get("url")
        if u and u not in pdf_urls:
            pdf_urls.append(u)

    best = data.get("best_oa_location") or {}
    if best:
        _push(best)
    for loc in (data.get("oa_locations") or []):
        _push(loc)

    return {"ok": True, "is_oa": bool(is_oa), "pdf_urls": pdf_urls,
            "evidence": f"is_oa={is_oa}, locations={len(data.get('oa_locations') or [])}",
            "error": ""}


# ---------------------------------------------------------------------------
# Layer 2: OpenAlex
# ---------------------------------------------------------------------------

def openalex_lookup(doi: str = "", title: str = "") -> dict:
    """Query OpenAlex by DOI (preferred) or title search.

    Returns {ok, is_oa, pdf_urls, evidence, error}.
    """
    doi = (doi or "").strip()
    title = (title or "").strip()
    if not doi and not title:
        return {"ok": False, "is_oa": None, "pdf_urls": [],
                "evidence": "no doi/title", "error": "no doi/title"}

    if doi:
        url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(doi, safe='')}"
        data, status, err = _json_get(url)
        if not data:
            return {"ok": False, "is_oa": None, "pdf_urls": [],
                    "evidence": "", "error": f"openalex(doi) {status}: {err}"}
        works = [data]
    else:
        q = urllib.parse.quote(title)
        url = f"https://api.openalex.org/works?search={q}&per-page=3"
        data, status, err = _json_get(url)
        if not data:
            return {"ok": False, "is_oa": None, "pdf_urls": [],
                    "evidence": "", "error": f"openalex(title) {status}: {err}"}
        works = data.get("results") or []

    is_oa = any((w.get("open_access") or {}).get("is_oa") for w in works)
    pdf_urls: list[str] = []
    for w in works:
        oa = w.get("open_access") or {}
        for u in (oa.get("oa_url"),):
            if u and u.lower().endswith(".pdf") and u not in pdf_urls:
                pdf_urls.append(u)
        for loc in (w.get("locations") or []):
            u = loc.get("pdf_url")
            if u and u not in pdf_urls:
                pdf_urls.append(u)
    return {"ok": True, "is_oa": is_oa, "pdf_urls": pdf_urls,
            "evidence": f"works={len(works)}, any_oa={is_oa}",
            "error": ""}


# ---------------------------------------------------------------------------
# Layer 3: Semantic Scholar
# ---------------------------------------------------------------------------

def semantic_scholar_lookup(doi: str = "", title: str = "") -> dict:
    """Query Semantic Scholar Graph API.

    S2 is heavily rate-limited (429 common); caller should treat failures as
    best-effort.
    """
    doi = (doi or "").strip()
    title = (title or "").strip()
    if not doi and not title:
        return {"ok": False, "is_oa": None, "pdf_urls": [],
                "evidence": "no doi/title", "error": "no doi/title"}

    base_fields = "title,openAccessPdf,externalIds"
    if doi:
        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{urllib.parse.quote(doi, safe='')}?fields={base_fields}"
        data, status, err = _json_get(url)
        if not data:
            return {"ok": False, "is_oa": None, "pdf_urls": [],
                    "evidence": "", "error": f"s2(doi) {status}: {err}"}
        papers = [data]
    else:
        q = urllib.parse.quote(title)
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={q}&limit=3&fields={base_fields}"
        data, status, err = _json_get(url)
        if not data:
            return {"ok": False, "is_oa": None, "pdf_urls": [],
                    "evidence": "", "error": f"s2(title) {status}: {err}"}
        papers = data.get("data") or []

    pdf_urls: list[str] = []
    has_any_oa = False
    for p in papers:
        oa = p.get("openAccessPdf") or {}
        u = oa.get("url") or ""
        if u:
            has_any_oa = True
            if u not in pdf_urls:
                pdf_urls.append(u)
    return {"ok": True, "is_oa": has_any_oa, "pdf_urls": pdf_urls,
            "evidence": f"papers={len(papers)}, any_oa={has_any_oa}",
            "error": ""}


# ---------------------------------------------------------------------------
# Layer 4: arXiv title search (recover missing arxiv_id)
# ---------------------------------------------------------------------------

_ARXIV_FUZZY_TOKEN = re.compile(r"[A-Za-z0-9]+")


def _title_similarity(a: str, b: str) -> float:
    """Simple Jaccard of lowercased alphanumeric tokens (>=4 chars)."""
    ta = {t.lower() for t in _ARXIV_FUZZY_TOKEN.findall(a) if len(t) >= 4}
    tb = {t.lower() for t in _ARXIV_FUZZY_TOKEN.findall(b) if len(t) >= 4}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def arxiv_title_search(title: str, *, min_similarity: float = 0.55) -> dict:
    """Look up a paper on arXiv by title. Returns candidate arxiv_id + PDF URL.

    We're conservative: accept only if title Jaccard >= min_similarity, so
    generic queries don't return unrelated papers.
    """
    title = (title or "").strip()
    if not HAS_REQUESTS or not title:
        return {"ok": False, "arxiv_id": "", "pdf_urls": [],
                "evidence": "", "error": "no requests or empty title"}
    q = urllib.parse.quote(title)
    url = f"http://export.arxiv.org/api/query?search_query=ti:{q}&max_results=5"
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=API_TIMEOUT)
    except Exception as e:
        return {"ok": False, "arxiv_id": "", "pdf_urls": [],
                "evidence": "", "error": f"{type(e).__name__}: {e}"}
    if r.status_code != 200:
        return {"ok": False, "arxiv_id": "", "pdf_urls": [],
                "evidence": "", "error": f"HTTP {r.status_code}"}
    entries = re.findall(r"<entry>.*?</entry>", r.text, re.S)
    best_sim = 0.0
    best_id = ""
    best_title = ""
    for e in entries:
        tm = re.search(r"<title>(.*?)</title>", e, re.S)
        idm = re.search(r"<id>http://arxiv.org/abs/([^<]+)</id>", e)
        if not tm or not idm:
            continue
        sim = _title_similarity(title, tm.group(1))
        if sim > best_sim:
            best_sim = sim
            best_id = idm.group(1)
            best_title = tm.group(1).strip()
    if best_sim < min_similarity:
        return {"ok": False, "arxiv_id": "", "pdf_urls": [],
                "evidence": f"best_sim={best_sim:.2f} (< {min_similarity})",
                "error": "no similar title"}
    # strip version suffix for the URL: 2405.14276v2 -> 2405.14276
    bare = re.sub(r"v\d+$", "", best_id)
    return {
        "ok": True,
        "arxiv_id": bare,
        "pdf_urls": [f"https://arxiv.org/pdf/{bare}.pdf"],
        "evidence": f"sim={best_sim:.2f} matched={best_title[:80]!r}",
        "error": "",
    }


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def resolve_oa_pdf_urls(
    *,
    doi: str = "",
    title: str = "",
    arxiv_id: str = "",
    api_delay: float = 0.3,
) -> dict:
    """Run all legal OA layers and return a priority-ordered candidate list.

    Returns:
        {
          pdf_urls:   [str, ...] (Unpaywall → OpenAlex → S2 → arXiv order),
          recovered_arxiv_id: str  (non-empty iff arxiv search found one),
          recovered_doi: str       (non-empty iff title→DOI reverse lookup succeeded),
          evidence:   {layer_name: {is_oa, evidence, error}},
          is_oa_any:  bool  (any layer reported is_oa=True),
        }
    """
    pdf_urls: list[str] = []
    evidence: dict = {}
    is_oa_any = False
    recovered_doi = ""

    # Skip the whole thing if caller has no identifying info.
    if not doi and not title:
        return {"pdf_urls": [], "recovered_arxiv_id": "", "recovered_doi": "",
                "evidence": {"skipped": "no doi/title"}, "is_oa_any": False}

    # --- Layer 0: reverse-lookup DOI from title via OpenAlex when missing ---
    # accepted_index doesn't persist DOI; rather than forcing an upstream
    # fix, we do a one-shot title->DOI lookup so Unpaywall + Sci-Hub still
    # have something to work with.
    if not doi and title:
        r0, status0, err0 = _json_get(
            f"https://api.openalex.org/works?search={urllib.parse.quote(title)}&per-page=3"
        )
        found_doi = ""
        if r0 and (r0.get("results") or []):
            for w in r0["results"]:
                wdoi = (w.get("doi") or "").removeprefix("https://doi.org/")
                wtitle = w.get("title") or ""
                if wdoi and _title_similarity(title, wtitle) >= 0.6:
                    found_doi = wdoi
                    break
        evidence["title_to_doi"] = {
            "evidence": f"found={found_doi or 'none'}",
            "error": err0 if not r0 else "",
        }
        if found_doi:
            recovered_doi = found_doi
            doi = found_doi  # use downstream
        time.sleep(api_delay)

    # --- Unpaywall (needs DOI) -------------------------------------
    if doi:
        r = unpaywall_lookup(doi)
        evidence["unpaywall"] = {"is_oa": r["is_oa"], "evidence": r["evidence"], "error": r["error"]}
        if r["is_oa"]:
            is_oa_any = True
        for u in r["pdf_urls"]:
            if u not in pdf_urls:
                pdf_urls.append(u)
        time.sleep(api_delay)

    # --- OpenAlex --------------------------------------------------
    r = openalex_lookup(doi=doi, title=title if not doi else "")
    evidence["openalex"] = {"is_oa": r["is_oa"], "evidence": r["evidence"], "error": r["error"]}
    if r["is_oa"]:
        is_oa_any = True
    for u in r["pdf_urls"]:
        if u not in pdf_urls:
            pdf_urls.append(u)
    time.sleep(api_delay)

    # --- Semantic Scholar -----------------------------------------
    r = semantic_scholar_lookup(doi=doi, title=title if not doi else "")
    evidence["semantic_scholar"] = {"is_oa": r["is_oa"], "evidence": r["evidence"], "error": r["error"]}
    if r["is_oa"]:
        is_oa_any = True
    for u in r["pdf_urls"]:
        if u not in pdf_urls:
            pdf_urls.append(u)
    time.sleep(api_delay)

    # --- arXiv title search (only when no arxiv_id yet) -----------
    recovered = ""
    if not arxiv_id and title:
        r = arxiv_title_search(title)
        evidence["arxiv_title_search"] = {"is_oa": None, "evidence": r["evidence"], "error": r["error"]}
        if r["ok"]:
            recovered = r["arxiv_id"]
            for u in r["pdf_urls"]:
                if u not in pdf_urls:
                    pdf_urls.append(u)

    return {
        "pdf_urls": pdf_urls,
        "recovered_arxiv_id": recovered,
        "recovered_doi": recovered_doi,
        "evidence": evidence,
        "is_oa_any": is_oa_any,
    }
