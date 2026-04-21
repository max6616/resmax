# ACL Venue Playbook

## Primary Source

- ACL uses ACL Anthology: `https://aclanthology.org/events/acl-{YEAR}/`
- Fields: title, authors, abstract, pdf_link
- Parser: `acl_anthology_html`
- Abstracts available from primary source

## Auxiliary Sources

- OpenReview (ACL Rolling Review): `aclweb.org/ACL/ARR/{YEAR}/{MONTH}`

## Review Data

- **Reviews public**: Partial — via ACL Rolling Review (ARR) data release
- **Platform**: OpenReview v2 (ARR infrastructure)
- **API group**: `aclweb.org/ACL/ARR/{YEAR}/{MONTH}`
- **Score scale**: Soundness 1-5 (0.5 increments), Excitement (separate dimension), Confidence 1-5, Action Editor overall 1-5
- **Reviewers/paper**: at least 3
- **Data includes**: reviews (summary, strengths, weaknesses), meta-reviews, reviewer-author discussions, paper drafts
- **Release policy**: Accepted paper reviews released through ARR Data Collection Initiative; rejected paper reviews released after 1-year grace period
- **Structured datasets**: Available from TU Darmstadt (`tudatalib.ulb.tu-darmstadt.de`), covering COLING 2025, NAACL 2025, ACL 2025, EMNLP 2025
- Same policy applies to EMNLP and NAACL (all use ARR)

## Parser Versions Used

| Year | Parser | URL Pattern | Entry Count |
|------|--------|-------------|-------------|
| 2024 | `acl_anthology_html` | aclanthology.org/events/acl-2024/ | 1965 |
| 2025 | `acl_anthology_html` | aclanthology.org/events/acl-2025/ | 3351 |

## Lessons Learned

- ACL/EMNLP/NAACL all use ARR since ~2022 — unified review system
- openreview_forum_id is 0% in current database for ACL venues — needs backfill via ARR OpenReview search or TU Darmstadt dataset
- ARR scoring is multi-dimensional (not a single overall score like ICLR/NeurIPS) — `review_scores` should store the primary "Soundness" score for comparability
- Review data availability is delayed — may not be available immediately after acceptance
- decision field from ACL Anthology has Main/Findings/Main Short/SRW/Industry/Demo distinction
