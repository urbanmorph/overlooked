# Progress

Newest first. Updated as work happens.

## Status (16 October 2026)

| Area | State |
|---|---|
| Repository, licence, secrets | Done. Public repo `urbanmorph/overlooked` (MIT). Actions secrets: GBIF and bucket-scoped R2 keys only. |
| Cloudflare | **Live: https://overlooked-india.pages.dev** (16 October 2026). R2 bucket `overlooked-data` holds snapshot `2026-10`. |
| Plan | `docs/plan.md`, approved 16 October 2026, updated as decisions change. |
| Module 1: last-seen ledger | **Live** on the first all-India snapshot (2026-10). |
| Module 2: change feed | Not started. Needs two monthly snapshots. |
| Module 5: identification backlog | Brought forward. iNaturalist layer (backlog by state and group, identifiers, direct check of quiet species) and GBIF query U built; backlog page and ledger note built; testing. |
| Module 3: new species | Sources checked (Plazi, IPNI, Index Fungorum, BSI). Not built. |
| Monthly run (GitHub Actions) | Workflows in place, tested end to end on Kerala. Schedules off until `PIPELINE_ENABLED` is set. |
| Source limits | Documented in `docs/sources.md`. Pipeline follows them (GBIF downloads one at a time, crons off the hour). |

## Log

### 16 October 2026

- **Public launch.** First all-India snapshot `2026-10` published (doi:10.15468/dl.hbk62c, doi:10.15468/dl.c8fw5y, doi:10.15468/dl.hsmcmy): 53,445 species, 63.8 million records, 784 districts, 549,804 ledger rows; 6,990 species with no public record in India since 1980; 651 districts with quiet species; 419,594 records not named to species. Production deploys on; https://overlooked-india.pages.dev live. Live overview: first paint 444 ms, 8 requests, 198 KB. iNaturalist layer workflow started.
- Fixed: `.gitignore` rule `data/` also matched `functions/data/` and `site/data/`, so the data function had never been committed. Rules now apply to the top-level folders only.
- Rerunning the publish was a no-op for R2 (same inputs) and recorded the run as published; `latest.json` now keeps the original snapshot time.
- All-India run: species history ready at 20:23 IST (146,689 rows); query U submitted (`0030871-260928105237408`). GBIF and GitHub work went on while the laptop slept; only local helpers paused.
- Module 5 checked in the browser on test data: 2,955,818 iNaturalist observations from India wait for a name (54% of verifiable ones; 76% added before 2026). Fungi: 95% waiting, 865 identifiers in 12 months. Ledger notes work; the iNaturalist request budget stops cleanly and continues next run.
- All-India run `2026-10`: ledger download ready at 19:44 (11.8 million rows, 311 MB, key `0030725-260928105237408`). Build on Actions passed the health check and submitted species history (`0030812-260928105237408`); query U follows.
- Module 5 brought forward. The India Biodiversity Portal is not contacted; its GBIF dataset is used as it is.
- iNaturalist layer: all 36 states mapped to iNaturalist places (two manual matches: Ladakh; Dadra, Nagar Haveli, Daman & Diu). Backlog by state, group and year; identifiers per group; direct check of quiet species with a 9,000-request daily budget that continues next day. Stored apart from the GBIF snapshot, with its own date. First sample: of 10 fish quiet in Kerala since 1980, 7 have recent research-grade iNaturalist observations in India, several without an open licence.
- GBIF query U (records not named to species) added; runs already started pick it up after their other downloads.
- New page: Waiting for a name (`/backlog`). Ledger shows "iNaturalist: seen in India <date>" next to quiet species.
- Runs are now idempotent and incremental (see plan section 7): rebuild with the same inputs skipped (tested), R2 uploads resume and skip identical files (tested), month skipped if GBIF reports no change. Health check of 12 sources at every refresh: all working on 16 October.
- Fixed: locally, inherited shell variables from another project overrode this project's R2 keys. `.env` now takes priority (GitHub Actions was not affected).
- iNaturalist reaches us through GBIF (1.71 million India records, updated weekly), but about 0.8 million research-grade observations without an open licence and about 3 million awaiting identification do not. The India Biodiversity Portal's GBIF dataset stops in 2024. Options put to the owner: direct iNaturalist check for quiet species; ask the Portal to republish; bring module 5 (identification backlog) forward.
- End-to-end test passed on both Kerala downloads (doi:10.15468/dl.6mfzfh, doi:10.15468/dl.v7fx5r): full monthly build in 11 s; all 9,243 species named; page data and district map written; both pages work on it with no errors. Pages now show a plain message if data fails to load.
- Owner approved a real snapshot in R2 and production deploys. All-India run `2026-10` started on Actions: ledger download `0030725-260928105237408` submitted 13:21 UTC; species history follows when it finishes.
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
