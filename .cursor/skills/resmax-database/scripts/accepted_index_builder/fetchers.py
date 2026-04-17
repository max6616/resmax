from __future__ import annotations

import json
import re
import signal
import time
import urllib.request
import urllib.parse
from pathlib import Path

from .models import SourceConfig


class _FetchTimeout(Exception):
    pass


def _fetch_with_total_timeout(url: str, headers: dict, socket_timeout: int = 30, total_timeout: int = 120) -> bytes:
    """Fetch URL with both per-socket and total wall-clock timeout."""
    old_handler = signal.getsignal(signal.SIGALRM)
    def _alarm(signum, frame):
        raise _FetchTimeout(f"total timeout {total_timeout}s exceeded for {url}")
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(total_timeout)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
            data = resp.read()
        return data
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def fetch_text(source: SourceConfig, fixtures_dir: Path, timeout: int = 60) -> str:
    url = source.url
    if url.startswith("fixture://"):
        rel = url[len("fixture://"):]
        return (fixtures_dir / rel).read_text(encoding="utf-8")

    raw = _fetch_with_total_timeout(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/json,*/*"},
        socket_timeout=timeout,
        total_timeout=max(timeout * 3, 120),
    )
    return raw.decode("utf-8", errors="replace")


def fetch_json(source: SourceConfig, fixtures_dir: Path, timeout: int = 30) -> dict:
    return json.loads(fetch_text(source, fixtures_dir=fixtures_dir, timeout=timeout))


def fetch_openreview_api_v2(
    group: str,
    accepted_venue_prefixes: list[str],
    timeout: int = 60,
    page_size: int = 1000,
) -> dict:
    """Paginate through OpenReview API v2 search endpoint and return accepted notes.

    Uses /notes/search?query=*&group=<group> with offset pagination.
    Filters notes whose content.venue.value starts with any of accepted_venue_prefixes.
    Returns a dict compatible with openreview_notes_json parser: {"notes": [...]}.
    """
    base = "https://api2.openreview.net/notes/search"
    all_notes: list[dict] = []
    offset = 0
    total = None

    while True:
        params = urllib.parse.urlencode({
            "query": "*",
            "group": group,
            "limit": page_size,
            "offset": offset,
        })
        url = f"{base}?{params}"
        raw = _fetch_with_total_timeout(
            url,
            headers={
                "User-Agent": "resmax-accepted-index/1.0",
                "Accept": "application/json",
            },
            socket_timeout=timeout,
            total_timeout=max(timeout * 2, 90),
        )
        data = json.loads(raw.decode("utf-8", errors="replace"))

        notes = data.get("notes", [])
        if total is None:
            total = data.get("count", 0)
            print(f"  [OpenReview] group={group}, total submissions={total}")

        for note in notes:
            venue = note.get("content", {}).get("venue", {}).get("value", "")
            if any(venue.lower().startswith(p.lower()) for p in accepted_venue_prefixes):
                all_notes.append(note)

        offset += len(notes)
        if not notes or offset >= total:
            break
        time.sleep(0.5)

    print(f"  [OpenReview] accepted notes after filtering: {len(all_notes)}")
    return {"notes": all_notes}


def fetch_aaai_ojs_all_issues(
    archive_url: str,
    year_tag: str,
    timeout: int = 60,
) -> str:
    """Fetch all AAAI OJS Technical Tracks issue pages for a given year and concatenate.

    1. Fetches the archive page(s) to discover issue URLs matching year_tag (e.g. "AAAI-25").
    2. Fetches each matching issue page.
    3. Returns concatenated HTML of all issue pages.
    """
    import re as _re

    def _get(url: str) -> str:
        raw = _fetch_with_total_timeout(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                "Accept": "text/html,*/*",
            },
            socket_timeout=timeout,
            total_timeout=max(timeout * 2, 90),
        )
        return raw.decode("utf-8", errors="replace")

    all_issue_urls: list[str] = []
    page = 1
    max_pages = 10
    found_year = False
    while page <= max_pages:
        page_url = archive_url if page == 1 else f"{archive_url}/{page}"
        html = _get(page_url)

        issue_pattern = _re.compile(
            r'<a\s+class="title"\s+href="(https://ojs\.aaai\.org/index\.php/AAAI/issue/view/\d+)">\s*'
            + _re.escape(year_tag) + r'\s+Technical\s+Tracks',
            _re.I | _re.S,
        )
        found = issue_pattern.findall(html)
        all_issue_urls.extend(found)

        if found:
            found_year = True
        elif found_year:
            break

        page += 1
        time.sleep(0.3)

    all_issue_urls = list(dict.fromkeys(all_issue_urls))
    print(f"  [AAAI OJS] found {len(all_issue_urls)} Technical Tracks issues for {year_tag}")

    combined_html = ""
    for i, url in enumerate(all_issue_urls):
        print(f"  [AAAI OJS] fetching issue {i+1}/{len(all_issue_urls)}: {url}")
        combined_html += _get(url) + "\n"
        time.sleep(0.3)

    return combined_html


def _http_get(url: str, timeout: int = 60) -> str:
    raw = _fetch_with_total_timeout(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
        socket_timeout=timeout,
        total_timeout=max(timeout * 3, 120),
    )
    return raw.decode("utf-8", errors="replace")


def fetch_acmmm_vue_accepted_chunk(base_url: str, chunk_name: str, timeout: int = 60) -> str:
    """Load ACM MM Vue SPA accepted-papers chunk: resolve app bundle hash, then chunk hash.

    base_url: e.g. https://2024.acmmm.org (no trailing path required).
    chunk_name: webpack chunk id for the Accepted Papers route, e.g. chunk-240a60f6.
    """
    base = base_url.rstrip("/")
    index_html = _http_get(base + "/", timeout=timeout)
    app_m = re.search(r'src="(/js/app\.[a-f0-9]+\.js)"', index_html)
    if not app_m:
        app_m = re.search(r"src='(/js/app\.[a-f0-9]+\.js)'", index_html)
    if not app_m:
        raise ValueError("Could not find /js/app.[hash].js in ACM MM index HTML")
    app_path = app_m.group(1)
    app_js = _http_get(base + app_path, timeout=timeout)
    chunk_re = re.compile(re.escape(f'"{chunk_name}"') + r':"([a-f0-9]+)"')
    hm = chunk_re.search(app_js)
    if not hm:
        raise ValueError(f'Chunk id "{chunk_name}" not found in app bundle')
    chunk_path = f"/js/{chunk_name}.{hm.group(1)}.js"
    print(f"  [acmmm-vue] fetching {base}{chunk_path}")
    return _http_get(base + chunk_path, timeout=timeout)
