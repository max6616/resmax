r"""Paper-source fetching and URL mining (Stage 5.5.a).

Three-layer source strategy (each kept in a per-paper folder):

    paper_sources/<safe_id>/
        paper.pdf            # raw PDF (always, when pdf_url is reachable)
        paper.pdftxt         # PyMuPDF text-layer extraction (char-faithful URLs)
        paper.md             # MinerU markdown (written by main agent via MCP)
        paper.tex            # arxiv-to-prompt flattened LaTeX (when arxiv_id)
        arxiv_source.tar.gz  # raw arXiv e-print tarball (when arxiv_id)
        arxiv_source/        # untarred tree (preserves original multi-file layout)

Why three layers (keep all - they have complementary strengths):

  1. arXiv flattened TeX
       + source-level fidelity; exact \cite{}, \url{}, equations
       - coverage < 100% (ECCV/CVF-only papers have no arxiv_id)

  2. PDF text-layer (PyMuPDF `get_text("text")`)
       + char-faithful: reads the PDF's /ToUnicode CMap, so `I` != `l` even on
         OCR-hostile glyphs. This is the *only* reliable source for short
         identifiers like URLs, emails, bibkeys.
       - poor for agent reading (no reflow, broken sentences across columns)

  3. MinerU markdown
       + best for LLM reading: reflowed paragraphs, clean structure, good for
         "what baselines does this paper use"
       - lossy for URLs (I/l/1 confusion observed in 4dgs_editing CTRL-D case)

URL mining runs on *all* available sources and unions the results. Char-faithful
sources (TeX, PDF text) are the authority; MD contributes hints that must be
cross-checked. See SKILL.md "Stage 5.5.a" for full rationale.
"""
from __future__ import annotations

import io
import re
import shutil
import tarfile
from pathlib import Path
from typing import Optional

try:
    from arxiv_to_prompt import process_latex_source  # type: ignore
    HAS_ARXIV_TO_PROMPT = True
except ImportError:  # pragma: no cover
    process_latex_source = None  # type: ignore[assignment]
    HAS_ARXIV_TO_PROMPT = False

try:
    import pymupdf  # type: ignore
    HAS_PYMUPDF = True
except ImportError:  # pragma: no cover
    try:
        import fitz as pymupdf  # type: ignore
        HAS_PYMUPDF = True
    except ImportError:
        pymupdf = None  # type: ignore[assignment]
        HAS_PYMUPDF = False

try:
    import requests  # type: ignore
    HAS_REQUESTS = True
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]
    HAS_REQUESTS = False


# Many venue CDNs (OpenReview / ACM) 403 on generic bot User-Agents. Use a
# recent Chrome string. arXiv is fine with anything.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DOWNLOAD_TIMEOUT = 45
MAX_PDF_BYTES = 80 * 1024 * 1024  # 80 MB safety cap (long ICLR PDFs can be ~40 MB)


# ---------------------------------------------------------------------------
# URL mining
# ---------------------------------------------------------------------------

_GITHUB_URL_RE = re.compile(
    r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
    re.IGNORECASE,
)
# Project pages: <owner>.github.io/<repo>/... — hints, not actionable
_GITHUB_IO_URL_RE = re.compile(
    r"https?://[A-Za-z0-9_-]+\.github\.io/[A-Za-z0-9_./-]*",
    re.IGNORECASE,
)


def _clean_url_token(raw: str) -> str:
    return raw.rstrip(").,;:}]>!?\"'")


def _dedup_ordered(items: list[str], limit: Optional[int] = None) -> list[str]:
    seen: dict[str, None] = {}
    for x in items:
        if x and x not in seen:
            seen[x] = None
            if limit and len(seen) >= limit:
                break
    return list(seen.keys())


def extract_github_urls(text: str, max_urls: int = 5) -> list[str]:
    """Return unique github.com/<owner>/<repo> URLs (case-preserving)."""
    if not text:
        return []
    out = []
    for raw in _GITHUB_URL_RE.findall(text):
        cleaned = _clean_url_token(raw)
        parts = cleaned.split("/", 5)
        if len(parts) >= 5:
            cleaned = "/".join(parts[:5])
        out.append(cleaned)
    return _dedup_ordered(out, max_urls)


def extract_project_page_urls(text: str, max_urls: int = 3) -> list[str]:
    """Return unique `*.github.io` project-page URLs (case-preserving)."""
    if not text:
        return []
    out = [_clean_url_token(raw) for raw in _GITHUB_IO_URL_RE.findall(text)]
    return _dedup_ordered(out, max_urls)


# ---------------------------------------------------------------------------
# Per-source fetchers
# ---------------------------------------------------------------------------

def _http_get(url: str) -> tuple[Optional[bytes], int, str]:
    """Return (body | None, status_code, error_str).

    A successful return has body != None and status_code == 200.
    """
    if not HAS_REQUESTS or not url:
        return None, 0, "requests not installed" if not HAS_REQUESTS else "empty url"
    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT,
                          headers=headers, allow_redirects=True) as r:
            if r.status_code != 200:
                return None, r.status_code, f"HTTP {r.status_code}"
            total = 0
            chunks: list[bytes] = []
            for chunk in r.iter_content(64 * 1024):
                if chunk:
                    total += len(chunk)
                    if total > MAX_PDF_BYTES:
                        return None, 200, f"exceeded MAX_PDF_BYTES ({MAX_PDF_BYTES})"
                    chunks.append(chunk)
            return b"".join(chunks), 200, ""
    except Exception as e:
        return None, 0, f"{type(e).__name__}: {e}"


def _looks_like_pdf(data: bytes) -> bool:
    """PDFs start with `%PDF-`. Reject HTML error pages that returned HTTP 200."""
    return bool(data) and data[:5] == b"%PDF-"


def derive_pdf_candidates(
    *,
    pdf_url: str = "",
    arxiv_id: str = "",
    openreview_forum_id: str = "",
    doi: str = "",
    paper_link: str = "",
) -> list[str]:
    """Build a de-duplicated list of candidate PDF URLs in priority order.

    Priority rationale (empirically validated on 4dgs_editing S set):
      1. pdf_url from accepted_index (most authoritative, if present)
      2. arXiv (anonymous, reliable, no UA games)
      3. OpenReview (needs a browser UA - handled in _http_get)
      4. ACM DOI (IP-walled for non-subscribers but still worth a shot)
      5. paper_link as last resort if it *looks* like a PDF
    """
    out: list[str] = []
    if pdf_url and pdf_url.strip():
        out.append(pdf_url.strip())
    if arxiv_id and arxiv_id.strip():
        out.append(f"https://arxiv.org/pdf/{arxiv_id.strip()}.pdf")
    if openreview_forum_id and openreview_forum_id.strip():
        out.append(f"https://openreview.net/pdf?id={openreview_forum_id.strip()}")
    if doi and doi.strip():
        out.append(f"https://dl.acm.org/doi/pdf/{doi.strip()}")
    if paper_link and paper_link.strip().lower().endswith(".pdf"):
        out.append(paper_link.strip())
    return _dedup_ordered(out)


def fetch_pdf(
    pdf_urls: list[str] | str,
    paper_dir: Path,
    *,
    overwrite: bool = False,
) -> dict:
    """Ensure `paper_dir/paper.pdf` exists; extract its text layer to
    `paper_dir/paper.pdftxt`.

    Behaviour:
      - If `paper.pdf` already exists (size > 0) and `overwrite=False`, it is
        used as-is (supports manual placement when the canonical PDF is behind
        an IP wall — e.g. user dragged an ACM PDF into the folder).
      - Otherwise tries each URL in `pdf_urls` (string accepted for back-compat)
        in order, using a browser User-Agent, and stops on the first valid PDF.
      - Any candidate that returns HTTP != 200 or non-PDF bytes is logged in
        the returned `attempts` list so the caller can tell the user which
        URLs failed and why.

    Returns:
        {
          ok: bool,
          pdf_path: Path | None,
          pdftxt_path: Path | None,
          text_chars: int,
          source_url: "" | "<url that succeeded>" | "preexisting-file",
          attempts: [{"url": ..., "status": int, "error": str}, ...],
          error: "" | "<final summary>"
        }
    """
    pdf_path = paper_dir / "paper.pdf"
    txt_path = paper_dir / "paper.pdftxt"
    paper_dir.mkdir(parents=True, exist_ok=True)

    if not HAS_PYMUPDF:
        return {"ok": False, "pdf_path": None, "pdftxt_path": None,
                "text_chars": 0, "source_url": "", "attempts": [],
                "error": "pymupdf not installed"}

    # Accept single-string pdf_urls for callsite convenience.
    if isinstance(pdf_urls, str):
        pdf_urls = [pdf_urls] if pdf_urls else []

    attempts: list[dict] = []
    source_url = ""

    # Fast path: preexisting paper.pdf (user-provided or prior run).
    if not overwrite and pdf_path.exists() and pdf_path.stat().st_size > 0:
        source_url = "preexisting-file"
    else:
        # Try each candidate URL.
        for url in pdf_urls:
            if not url:
                continue
            data, status, err = _http_get(url)
            if data and _looks_like_pdf(data):
                pdf_path.write_bytes(data)
                source_url = url
                attempts.append({"url": url, "status": status, "error": ""})
                break
            reason = err or (f"HTTP 200 but not a PDF (got {data[:16]!r})" if data else "no body")
            attempts.append({"url": url, "status": status, "error": reason})

    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        url_list = "; ".join(a["url"] for a in attempts) or "(no candidates given)"
        return {"ok": False, "pdf_path": None, "pdftxt_path": None,
                "text_chars": 0, "source_url": "", "attempts": attempts,
                "error": f"no PDF obtained; tried {len(attempts)} URL(s): {url_list}"}

    # Extract text layer (skip when pdftxt is fresh and PDF hasn't changed).
    if (
        not overwrite
        and txt_path.exists() and txt_path.stat().st_size > 0
        and txt_path.stat().st_mtime >= pdf_path.stat().st_mtime
    ):
        text = txt_path.read_text(encoding="utf-8", errors="ignore")
    else:
        try:
            with pymupdf.open(pdf_path) as doc:
                pages = [page.get_text("text") for page in doc]
            text = "\n\n".join(pages)
        except Exception as e:
            return {"ok": False, "pdf_path": pdf_path, "pdftxt_path": None,
                    "text_chars": 0, "source_url": source_url, "attempts": attempts,
                    "error": f"pymupdf parse failed: {e}"}
        if not text.strip():
            return {"ok": False, "pdf_path": pdf_path, "pdftxt_path": None,
                    "text_chars": 0, "source_url": source_url, "attempts": attempts,
                    "error": "pdf has no text layer (image-only?)"}
        txt_path.write_text(text, encoding="utf-8")

    return {"ok": True, "pdf_path": pdf_path, "pdftxt_path": txt_path,
            "text_chars": len(text), "source_url": source_url,
            "attempts": attempts, "error": ""}


def fetch_arxiv_tex(
    arxiv_id: str,
    *,
    keep_comments: bool = False,
    remove_appendix: bool = False,
    cache_dir: Optional[Path] = None,
) -> Optional[str]:
    """Return flattened LaTeX source for an arXiv paper (or None)."""
    if not HAS_ARXIV_TO_PROMPT or not arxiv_id or not arxiv_id.strip():
        return None
    try:
        text = process_latex_source(
            arxiv_id.strip(),
            keep_comments=keep_comments,
            cache_dir=str(cache_dir) if cache_dir else None,
            use_cache=True,
            remove_appendix_section=remove_appendix,
        )
    except Exception:
        return None
    if not text or not text.strip():
        return None
    return text


def fetch_arxiv_source_tarball(arxiv_id: str, paper_dir: Path, *, overwrite: bool = False) -> dict:
    """Download the raw e-print tarball and extract it.

    Returns: {ok, tarball_path, source_dir, error}
    """
    arxiv_id = (arxiv_id or "").strip()
    if not arxiv_id:
        return {"ok": False, "tarball_path": None, "source_dir": None, "error": "no arxiv_id"}

    tarball_path = paper_dir / "arxiv_source.tar.gz"
    source_dir = paper_dir / "arxiv_source"

    if (
        not overwrite
        and tarball_path.exists() and tarball_path.stat().st_size > 0
        and source_dir.exists() and any(source_dir.iterdir())
    ):
        return {"ok": True, "tarball_path": tarball_path, "source_dir": source_dir, "error": ""}

    paper_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    data, status, http_err = _http_get(url)
    if not data:
        return {"ok": False, "tarball_path": None, "source_dir": None,
                "error": f"arxiv e-print download failed ({status}): {http_err}"}

    tarball_path.write_bytes(data)
    # Some arxiv e-prints are single .tex or .pdf, not tar.gz. Try tar first.
    if source_dir.exists():
        shutil.rmtree(source_dir, ignore_errors=True)
    source_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
            tar.extractall(source_dir, filter="data")
    except Exception:
        # Not a tarball: keep the raw bytes as arxiv_source.bin and move on.
        shutil.rmtree(source_dir, ignore_errors=True)
        return {"ok": True, "tarball_path": tarball_path, "source_dir": None,
                "error": "arxiv e-print not a tarball (single-file source)"}

    return {"ok": True, "tarball_path": tarball_path, "source_dir": source_dir, "error": ""}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _safe_id(paper_id: str) -> str:
    return paper_id.replace("/", "__").replace(":", "_")


def fetch_and_cache_source(
    paper_id: str,
    arxiv_id: str,
    cache_dir: Path,
    *,
    pdf_url: str = "",
    pdf_url_candidates: Optional[list[str]] = None,
    doi: str = "",
    title: str = "",
    enable_oa_api: bool = True,
    enable_sci_hub: bool = False,
    overwrite: bool = False,
) -> dict:
    """Fetch arXiv TeX + PDF text-layer + tarball (best-effort, each independent).

    `cache_dir` is the parent directory (e.g. `paper_sources/`); each paper
    gets its own subfolder.

    Returns a descriptor:
        {
          paper_id, paper_dir (rel name), sources_present (list of tags),
          source_files (dict tag -> filename within paper_dir),
          github_urls, project_page_urls,
          per_source_urls (dict tag -> dict),
          text_chars (dict tag -> int),
          errors (dict tag -> str),
        }

    Sources attempted:
      - "tex"    : arxiv-to-prompt flattened LaTeX
      - "pdf"    : raw PDF + PyMuPDF text layer (tag covers both files)
      - "arxiv"  : raw e-print tarball + extracted tree
      - "md"     : only reported when a previous mineru run wrote paper.md

    URL mining strategy: run extractors on every fetched text source (TeX,
    pdftxt, md). The descriptor's `github_urls` / `project_page_urls` are the
    *union*, char-faithful first (tex/pdftxt > md).
    """
    paper_dir = cache_dir / _safe_id(paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    arxiv_to_prompt_cache = cache_dir / ".arxiv_to_prompt_cache"

    sources_present: list[str] = []
    source_files: dict[str, str] = {}
    per_source_urls: dict[str, dict[str, list[str]]] = {}
    text_chars: dict[str, int] = {}
    errors: dict[str, str] = {}

    # --- 1. arXiv flattened TeX ----------------------------------------
    tex_path = paper_dir / "paper.tex"
    tex_text: Optional[str] = None
    if arxiv_id and arxiv_id.strip():
        if not overwrite and tex_path.exists() and tex_path.stat().st_size > 0:
            tex_text = tex_path.read_text(encoding="utf-8", errors="ignore")
        else:
            tex_text = fetch_arxiv_tex(arxiv_id, cache_dir=arxiv_to_prompt_cache)
            if tex_text:
                tex_path.write_text(tex_text, encoding="utf-8")
        if tex_text:
            sources_present.append("tex")
            source_files["tex"] = tex_path.name
            per_source_urls["tex"] = {
                "github_urls": extract_github_urls(tex_text),
                "project_page_urls": extract_project_page_urls(tex_text),
            }
            text_chars["tex"] = len(tex_text)
        else:
            errors["tex"] = f"arxiv-to-prompt failed for {arxiv_id}"
    else:
        errors["tex"] = "no arxiv_id"

    # --- 2. arXiv raw e-print tarball ----------------------------------
    if arxiv_id and arxiv_id.strip():
        arxiv_res = fetch_arxiv_source_tarball(arxiv_id, paper_dir, overwrite=overwrite)
        if arxiv_res["ok"]:
            sources_present.append("arxiv")
            source_files["arxiv_tarball"] = "arxiv_source.tar.gz"
            if arxiv_res["source_dir"]:
                source_files["arxiv_source_dir"] = "arxiv_source/"
            if arxiv_res["error"]:
                errors["arxiv"] = arxiv_res["error"]
        else:
            errors["arxiv"] = arxiv_res["error"]

    # --- 3. PDF + text layer (multi-layer fallback) --------------------
    # Layer 0: primary candidates (pdf_url + arxiv + openreview + doi direct)
    # Layer 1: OA aggregator APIs (Unpaywall / OpenAlex / S2) + arXiv title search
    # Layer 2: Sci-Hub mirror rotation (off by default; opt in explicitly)
    candidate_urls: list[str] = []
    if pdf_url_candidates:
        candidate_urls.extend([u for u in pdf_url_candidates if u])
    if pdf_url and pdf_url not in candidate_urls:
        candidate_urls.append(pdf_url)

    all_attempts: list[dict] = []
    fallback_diagnostic: dict = {}

    pdf_res = fetch_pdf(candidate_urls, paper_dir, overwrite=overwrite)
    all_attempts.extend(pdf_res.get("attempts") or [])

    # Layer 1: OA APIs (only if Layer 0 failed)
    effective_doi = doi  # may be filled by title->DOI reverse lookup
    if not pdf_res["ok"] and enable_oa_api and (doi or title):
        from .oa_resolvers import resolve_oa_pdf_urls  # lazy import
        oa = resolve_oa_pdf_urls(doi=doi, title=title, arxiv_id=arxiv_id)
        fallback_diagnostic["oa_api"] = {
            "is_oa_any": oa["is_oa_any"],
            "recovered_arxiv_id": oa["recovered_arxiv_id"],
            "recovered_doi": oa.get("recovered_doi", ""),
            "evidence": oa["evidence"],
            "pdf_urls_found": len(oa["pdf_urls"]),
        }
        if not effective_doi and oa.get("recovered_doi"):
            effective_doi = oa["recovered_doi"]
        # Deduplicate against already-tried URLs
        tried = {a["url"] for a in all_attempts}
        fresh = [u for u in oa["pdf_urls"] if u not in tried]
        if fresh:
            pdf_res2 = fetch_pdf(fresh, paper_dir, overwrite=False)
            all_attempts.extend(pdf_res2.get("attempts") or [])
            if pdf_res2["ok"]:
                pdf_res = pdf_res2

    # Layer 2: Sci-Hub (only if still failing, and we have a DOI—original or recovered)
    if not pdf_res["ok"] and enable_sci_hub and effective_doi:
        from .sci_hub import sci_hub_pdf_url  # lazy import
        sh = sci_hub_pdf_url(effective_doi)
        fallback_diagnostic["sci_hub"] = {
            "ok": sh["ok"],
            "mirror": sh["mirror"],
            "evidence": sh["evidence"],
            "error": sh["error"],
        }
        if sh["ok"] and sh["pdf_url"]:
            pdf_res3 = fetch_pdf([sh["pdf_url"]], paper_dir, overwrite=False)
            all_attempts.extend(pdf_res3.get("attempts") or [])
            if pdf_res3["ok"]:
                pdf_res = pdf_res3

    if pdf_res["ok"]:
        sources_present.append("pdf")
        source_files["pdf"] = "paper.pdf"
        source_files["pdftxt"] = "paper.pdftxt"
        pdf_text = (paper_dir / "paper.pdftxt").read_text(encoding="utf-8", errors="ignore")
        per_source_urls["pdftxt"] = {
            "github_urls": extract_github_urls(pdf_text),
            "project_page_urls": extract_project_page_urls(pdf_text),
        }
        text_chars["pdftxt"] = len(pdf_text)
        if pdf_res.get("source_url"):
            source_files["pdf_source_url"] = pdf_res["source_url"]
    else:
        if pdf_res["error"]:
            errors["pdf"] = pdf_res["error"]
        if all_attempts:
            errors["pdf_attempts"] = all_attempts
        if fallback_diagnostic:
            errors["pdf_fallback"] = fallback_diagnostic

    # --- 4. Pre-existing mineru markdown (if any) ----------------------
    md_path = paper_dir / "paper.md"
    if md_path.exists() and md_path.stat().st_size > 0:
        md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        sources_present.append("md")
        source_files["md"] = md_path.name
        per_source_urls["md"] = {
            "github_urls": extract_github_urls(md_text),
            "project_page_urls": extract_project_page_urls(md_text),
        }
        text_chars["md"] = len(md_text)

    # --- Merge URLs (char-faithful sources first) ----------------------
    all_gh: list[str] = []
    all_gio: list[str] = []
    for tag in ("tex", "pdftxt", "md"):  # priority order
        if tag in per_source_urls:
            all_gh.extend(per_source_urls[tag]["github_urls"])
            all_gio.extend(per_source_urls[tag]["project_page_urls"])

    return {
        "paper_id": paper_id,
        "paper_dir": paper_dir.name,
        "sources_present": sources_present,
        "source_files": source_files,
        "github_urls": _dedup_ordered(all_gh, limit=8),
        "project_page_urls": _dedup_ordered(all_gio, limit=5),
        "per_source_urls": per_source_urls,
        "text_chars": text_chars,
        "errors": errors,
    }


def register_mineru_md(
    paper_id: str,
    md_text: str,
    cache_dir: Path,
) -> dict:
    """Persist an agent-fetched mineru markdown into the paper's folder and
    re-mine URLs across all available sources.
    """
    paper_dir = cache_dir / _safe_id(paper_id)
    paper_dir.mkdir(parents=True, exist_ok=True)
    md_path = paper_dir / "paper.md"
    md_path.write_text(md_text, encoding="utf-8")

    # Re-scan whatever is on disk; do not re-download tex/pdf.
    collected: dict[str, dict[str, list[str]]] = {}
    for fname, tag in (("paper.tex", "tex"), ("paper.pdftxt", "pdftxt"), ("paper.md", "md")):
        fp = paper_dir / fname
        if fp.exists() and fp.stat().st_size > 0:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            collected[tag] = {
                "github_urls": extract_github_urls(content),
                "project_page_urls": extract_project_page_urls(content),
            }

    all_gh: list[str] = []
    all_gio: list[str] = []
    for tag in ("tex", "pdftxt", "md"):
        if tag in collected:
            all_gh.extend(collected[tag]["github_urls"])
            all_gio.extend(collected[tag]["project_page_urls"])

    return {
        "paper_id": paper_id,
        "paper_dir": paper_dir.name,
        "github_urls": _dedup_ordered(all_gh, limit=8),
        "project_page_urls": _dedup_ordered(all_gio, limit=5),
        "per_source_urls": collected,
        "text_chars": {k: sum(1 for _ in v) for k, v in collected.items()},
    }
