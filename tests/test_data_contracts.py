from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".agents" / "skills" / "_shared"))

from data_contracts import (  # noqa: E402
    derive_pdf_contract,
    derive_source_text_contract,
    normalize_repo_url,
    normalize_yes_no,
    review_score_status,
)


def test_normalize_repo_url_keeps_real_trailing_chars() -> None:
    assert normalize_repo_url("https://github.com/geekan/MetaGPT") == "https://github.com/geekan/MetaGPT"
    assert normalize_repo_url("https://github.com/org/repo.") == "https://github.com/org/repo"
    assert normalize_repo_url("github.com/org/repo.git.") == "https://github.com/org/repo"
    assert normalize_repo_url("https://github.com/org/repo/tree/main") == "https://github.com/org/repo"


def test_pdf_contract_derives_canonical_pdf_urls() -> None:
    row = {"arxiv_id": "2401.00001", "paper_link": "https://arxiv.org/abs/2401.00001"}
    pdf = derive_pdf_contract(row)
    assert pdf.pdf_status == "available"
    assert pdf.pdf_url == "https://arxiv.org/pdf/2401.00001.pdf"
    assert pdf.pdf_source == "arxiv_id"

    row = {
        "paper_link": "https://openaccess.thecvf.com/content/CVPR2025/html/Foo_Bar_CVPR_2025_paper.html"
    }
    assert derive_pdf_contract(row).pdf_url.endswith("/papers/Foo_Bar_CVPR_2025_paper.pdf")

    row = {"paper_link": "https://aclanthology.org/2024.acl-long.55/"}
    pdf = derive_pdf_contract(row)
    assert pdf.pdf_source == "acl_anthology"
    assert pdf.pdf_url == "https://aclanthology.org/2024.acl-long.55.pdf"


def test_yes_no_and_review_score_status() -> None:
    assert normalize_yes_no("true") == "yes"
    assert normalize_yes_no("0") == "no"
    assert review_score_status({"review_available": "yes", "review_scores": "6;7"}) == "complete"
    assert review_score_status({"review_available": "yes", "review_num_reviewers": "3"}) == "no_scores"
    assert review_score_status({"review_available": "no"}) == "unavailable"


def test_source_text_contract_keeps_pdf_and_landing_distinct() -> None:
    pdf = derive_source_text_contract({
        "title": "Paper With PDF",
        "paper_link": "https://aclanthology.org/2024.acl-long.55/",
    })
    assert pdf.source_text_status == "pdf_available"
    assert pdf.source_text_url == "https://aclanthology.org/2024.acl-long.55.pdf"
    assert not pdf.source_text_search_query

    landing = derive_source_text_contract({
        "title": "Publisher Only",
        "doi": "10.1145/3637528.3671966",
    })
    assert landing.source_text_status == "publisher_landing_only"
    assert landing.source_text_url == "https://doi.org/10.1145/3637528.3671966"
    assert landing.source_text_search_query == '"Publisher Only" PDF'
