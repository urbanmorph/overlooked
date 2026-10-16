# Progress

Newest first. Updated as work happens.

## Status (16 October 2026)

| Area | State |
|---|---|
| Repository, licence, secrets | Done. Public repo `urbanmorph/overlooked` (MIT). Actions secrets: GBIF and bucket-scoped R2 keys only. |
| Cloudflare | R2 bucket `overlooked-data` (private, CORS set). Data function (`functions/data/`) tested locally on wrangler. Pages project `overlooked-india` created and linked to GitHub; production deploys off. |
| Plan | `docs/plan.md`, approved 16 October 2026, updated as decisions change. |
| Module 1: last-seen ledger | Pipeline works on Kerala (GBIF test download). Overview and ledger pages work on test data. |
| Module 2: change feed | Not started. Needs two monthly snapshots. |
| Module 3: new species | Sources checked (Plazi, IPNI, Index Fungorum, BSI). Not built. |
| Monthly run (GitHub Actions) | Workflows in place, tested end to end on Kerala. Schedules off until `PIPELINE_ENABLED` is set. |
| Source limits | Documented in `docs/sources.md`. Pipeline follows them (GBIF downloads one at a time, crons off the hour). |

## Log

### 16 October 2026

- Decision: for BSI and ZSI we rely on the web-policy clause that allows free reproduction with prominent acknowledgement. No permission request. Every page that uses their data credits them by name.
- Cloudflare Pages project `overlooked-india` created (GitHub `main`, output `site/`, R2 bound as `DATA`, rebuilds only for `site/` and `functions/`). Production deploys off until a real snapshot is published.
- Source limits documented in `docs/sources.md` (GBIF, COL, Kew, IPNI, Index Fungorum, MycoBank, ZooBank, Plazi, BSI, iNaturalist, IUCN, bharatlas, Cloudflare, GitHub, data.gov.in).
- Pipeline changed to match: GBIF downloads run one after another and a 429 waits for the next check; User-Agent carries the repository URL; crons moved off the hour (02:17 and :47).
- BSI survey: no technical block. Plant Discoveries 2007 to 2025 online (2025 out since 30 June 2026); new edition about 1 July. Indian Virtual Herbarium: HTML only, no coordinates, about 26,100 types and 160,000 India records; new type specimens found by barcode prefix in about 20 requests. Web policy allows free reproduction with prominent credit, but a second clause asks for written permission: ask BSI to confirm.
- Pages Function for `/data/*` written and tested on wrangler with local R2: GET, HEAD, Range (206), ETag (304), `cache/` blocked, POST refused. Links now use `/ledger` (Pages redirects `.html`).
- Pages project: Cloudflare's GitHub app on `urbanmorph` covers selected repositories only, and `overlooked` is not one. Adding it needs an organisation owner.
- BSI: the earlier blanket exclusion was a misread instruction. BSI is now synced like every other source. A survey of BSI data and terms is running.
- Rate limits of all sources: research running; results go to `docs/sources.md`.
- Query C (species history and names) written. Queries B and D dropped. Kerala test download for query C running at GBIF.
- Unsurveyed groups: a group with no record in an area since the chosen year is set apart, not counted as quiet. Test data: districts with quiet species fell from 641 to 576.
- Site text rewritten to about 70% of ASD-STE100.
- Found: GBIF SQL downloads key species by Catalogue of Life ID (for example `5VKF2`). Pipeline and links changed to match.
- Kerala test on GitHub Actions passed (35 s): download, boundaries, build, checks, artifact, commit.
- Overview and ledger pages built for speed: no database or map library in the browser. Overview: 8 requests, 135 KB. Lighthouse mobile: 100 for accessibility, best practices and SEO.
- Kerala ledger (doi:10.15468/dl.6mfzfh): 8.85 million records, 9,243 species, 35,502 species x district rows.
- Grid test: coordinates rounded to 3 decimals beat a 1.7 km grid (0.2% against 1.6% of records in the wrong district).
- Overlap check: nothing found does modules 1 to 3 for India. Notes in `supporting-docs/overlap-check.md`.
- Repository, R2 bucket, secrets, plan and design canvas set up.
