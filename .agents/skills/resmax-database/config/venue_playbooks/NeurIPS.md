# NeurIPS Venue Playbook

## Primary Source

- NeurIPS uses the virtual conference platform: `https://neurips.cc/static/virtual/data/neurips-{YEAR}-orals-posters.json`
- JSON includes: title, authors, abstract, decision, topic, poster_url
- Parser: `virtual_conference_json`
- Abstracts available directly from primary source

## Auxiliary Sources

- Proceedings page (`https://papers.nips.cc/paper_files/paper/{YEAR}`): title, authors, paper_link
- OpenReview group: `NeurIPS.cc/{YEAR}/Conference`

## Review Data

- **Reviews public**: Yes — accepted paper reviews are public on OpenReview
- **Platform**: OpenReview v2
- **API group**: `NeurIPS.cc/{YEAR}/Conference`
- **Review invitation**: `NeurIPS.cc/{YEAR}/Conference/Submission{number}/-/Official_Review`
- **Score scale**: 1-10 (2024 and earlier), **1-6 (2025 onwards)** — major scale change
- **Reviewers/paper**: typically 3-4
- **Data includes**: reviews (summary, strengths, weaknesses, questions), author rebuttals, meta-reviews, scores, confidence, decision/track
- Rejected paper review visibility varies by year

## Parser Versions Used

| Year | Parser | URL Pattern | Entry Count |
|------|--------|-------------|-------------|
| 2024 | `virtual_conference_json` | neurips-2024-orals-posters.json | 4610 |
| 2025 | `virtual_conference_json` | neurips-2025-orals-posters.json | 6002 |

## Lessons Learned

- NeurIPS 2025 changed scoring scale from 1-10 to 1-6 — must record `review_score_scale` per year
- NeurIPS 2025 event_type contains `{location}` placeholder (e.g. `{location} Poster`), does not affect acceptance_type inference
- NeurIPS 2024 has very low openreview_forum_id coverage (~1.3%) in the current database — needs backfill via OpenReview API title matching before review enrichment
- Confidence scale: 1-5 (consistent across years)
