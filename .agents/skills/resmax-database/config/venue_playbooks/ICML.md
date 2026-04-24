# ICML Venue Playbook

## Primary Source

- ICML uses the virtual conference platform: `https://icml.cc/static/virtual/data/icml-{YEAR}-orals-posters.json`
- JSON includes: title, authors, abstract, decision, topic, poster_url
- Parser: `virtual_conference_json`
- Abstracts available directly from primary source

## Auxiliary Sources

- OpenReview group: `ICML.cc/{YEAR}/Conference`

## Review Data

- **Reviews public**: Partially — review *text* is public, but *scores* may be hidden
- **Platform**: OpenReview v2
- **API group**: `ICML.cc/{YEAR}/Conference`
- **Score field**: `overall_recommendation` (not `rating`)
- **Confidence field**: none (ICML does not expose reviewer confidence)
- **Reviewers/paper**: 4 (>99% get at least 3)
- **Data includes**: review text (summary, strengths, weaknesses, etc.), rebuttals, decision
- Rejected paper reviews: opt-in only (authors choose whether to make public)

### Year-specific notes

| Year | Review text | Scores | Notes |
|------|-------------|--------|-------|
| 2024 | Not public | Not public | Submissions on OpenReview but reviews not exposed |
| 2025 | Public | Hidden (`overall_recommendation` field exists but value is empty) | Only Position Paper track (73 papers) has numeric scores |

## Parser Versions Used

| Year | Parser | URL Pattern | Entry Count |
|------|--------|-------------|-------------|
| 2024 | `virtual_conference_json` | icml-2024-orals-posters.json | 2778 |
| 2025 | `virtual_conference_json` | icml-2025-orals-posters.json | 3459 |

## Lessons Learned

- ICML 2024: submissions on OpenReview but reviews not public — marked `review_available=no`
- ICML 2024 has 0% openreview_forum_id coverage in the current database — needs backfill via OpenReview API title matching
- ICML 2025 has 99.8% forum_id coverage (from virtual conference JSON)
- ICML 2025: review text public but `overall_recommendation` score field is empty (hidden by policy). Only Position Paper track (73 papers) has numeric scores
- ICML 2025 has `Accept (spotlight poster)` variant in decision field, standardized to Spotlight
- ICML moved to OpenReview in 2023
