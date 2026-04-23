"""Sci-Hub mirror fallback (Stage 5.5.a Layer 4 - opt-out).

**WHAT IT IS**: A last-resort fallback used only after Unpaywall/OpenAlex/S2
(all legal) have returned no PDF. Sci-Hub is a widely-known academic mirror
that serves PDFs addressed by DOI. It is a *gray* source: legal status varies
by jurisdiction. We wire it in because the alternatives for a locked ACM/
Springer paper are (a) give up, (b) manually download every time, or (c)
bypass publisher anti-bot walls (fragile). This option is enabled by default
but gated behind an `enable_sci_hub` flag so users can turn it off.

**HOW IT WORKS**:
  1. We query a prioritized list of Sci-Hub mirror domains with the DOI.
     A mirror is considered functional if it returns HTTP 200 and the HTML
     body contains a PDF embed (iframe/embed/object with a .pdf src).
  2. If found, we extract the embedded PDF URL and return it to the caller,
     which passes it through the normal `fetch_pdf` validator (PDF magic
     bytes, size cap, PyMuPDF parse). If the embed URL is protocol-relative
     (`//host/...`), we prepend `https:`.
  3. We give up early if the mirror explicitly says the article is not in
     the database (typical for papers < ~1 year old).

**HOW TO OVERRIDE THE MIRROR LIST**:
    export RESMAX_SCI_HUB_MIRRORS="sci-hub.ru,sci-hub.st,sci-hub.se"

**LIMITATIONS**:
  - New papers (< ~1-2 years) often aren't indexed; for those we return None
    and the caller routes the paper into `no_oa_copy_found`.
  - Mirror domains rotate; if all fail we fall through without raising.
"""
from __future__ import annotations

import os
import re
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
MIRROR_TIMEOUT = 15

DEFAULT_MIRRORS = ("sci-hub.ru", "sci-hub.se", "sci-hub.st", "sci-hub.ee")


def _mirrors() -> tuple[str, ...]:
    override = os.environ.get("RESMAX_SCI_HUB_MIRRORS", "").strip()
    if override:
        return tuple(m.strip() for m in override.split(",") if m.strip())
    return DEFAULT_MIRRORS


_NOT_IN_DB_PATTERNS = (
    "статья отсутствует в базе",   # Russian: "article not in database"
    "article not in",               # English variant
    "not found in",
    "article is not",
)


# Match PDF embed/iframe. Sci-Hub uses various tag styles; we accept any.
# Handles protocol-relative (//host/...) and absolute (https://host/...) URLs.
_PDF_EMBED_RE = re.compile(
    r'(?:embed|iframe|object)[^>]+(?:src|data)\s*=\s*"([^"]+\.pdf[^"]*)"',
    re.IGNORECASE,
)


def _normalize_pdf_url(raw: str, mirror: str) -> str:
    """Convert embed src to an absolute URL."""
    raw = raw.strip()
    if raw.startswith("//"):
        return f"https:{raw}"
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    # Relative path: prepend mirror host
    return f"https://{mirror}/{raw.lstrip('/')}"


def sci_hub_pdf_url(doi: str, *, mirrors: Optional[tuple[str, ...]] = None) -> dict:
    """Try Sci-Hub mirrors for a DOI; return an embedded PDF URL if found.

    Returns:
        {
          ok: bool,
          pdf_url: str | "",
          mirror: str | "",
          evidence: [{mirror, status, note}, ...],
          error: str,
        }
    """
    doi = (doi or "").strip()
    if not doi:
        return {"ok": False, "pdf_url": "", "mirror": "",
                "evidence": [], "error": "no doi"}
    if not HAS_REQUESTS:
        return {"ok": False, "pdf_url": "", "mirror": "",
                "evidence": [], "error": "requests not installed"}

    mirrors = mirrors or _mirrors()
    evidence: list[dict] = []

    for host in mirrors:
        url = f"https://{host}/{urllib.parse.quote(doi, safe='/')}"
        try:
            r = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=MIRROR_TIMEOUT,
                allow_redirects=True,
            )
        except Exception as e:
            evidence.append({"mirror": host, "status": 0,
                             "note": f"{type(e).__name__}: {e}"})
            continue

        status = r.status_code
        body_lower = r.text.lower() if r.text else ""

        if status != 200:
            evidence.append({"mirror": host, "status": status,
                             "note": f"non-200 ({len(r.text)} bytes)"})
            continue

        if any(p in body_lower for p in _NOT_IN_DB_PATTERNS):
            evidence.append({"mirror": host, "status": 200,
                             "note": "article not in database"})
            # Not in DB on one mirror usually == not in DB anywhere; but we
            # continue in case a different mirror has it.
            continue

        match = _PDF_EMBED_RE.search(r.text)
        if not match:
            evidence.append({"mirror": host, "status": 200,
                             "note": "no pdf embed found"})
            continue

        pdf_url = _normalize_pdf_url(match.group(1), host)
        evidence.append({"mirror": host, "status": 200,
                         "note": f"found pdf: {pdf_url[:80]}"})
        return {"ok": True, "pdf_url": pdf_url, "mirror": host,
                "evidence": evidence, "error": ""}

    return {"ok": False, "pdf_url": "", "mirror": "",
            "evidence": evidence, "error": f"no mirror served an embed ({len(mirrors)} tried)"}
