# How Overlooked follows PDGI

[Overlooked](https://overlooked-india.pages.dev) is built on the principles of [People's Digital Goods and Infrastructure (PDGI)](https://pdgi.org/blog/peoples-digital-goods-and-infrastructure/): people before digital, rights-centric, commons-oriented, transparent.

This scorecard shows what we do for each principle, links the evidence, and says where we fall short.

Status key: ✅ implemented · 🟡 partial · ⛳ gap, with intended direction.

## Scorecard

### People before digital (rights and collective identity): ✅
Overlooked holds no observations of its own and decides nothing about a species. It joins what others document (the Zoological Survey of India and the Botanical Survey of India, Ministry of Environment, Forest and Climate Change; Royal Botanic Gardens, Kew; GBIF; iNaturalist; Plazi; the IUCN Red List) into one list, with names from the Catalogue of Life, and shows three things per species: observed, identified, IUCN status. A species that BSI or ZSI lists counts as documented, whatever an aggregator holds. The footer of every page credits BSI and ZSI by name. Every page and every data file credits its sources and says plainly that this is not an official checklist or conservation assessment; for the status of a species it sends people to BSI, ZSI, the IUCN Red List and the state forest department. No accounts, no profiles, no personal data.
Evidence: the `licence`, `attribution` and `disclaimer` in every published `summary.json` (`pipeline/site_data.py`, `RIGHTS`), [Sources and method](https://overlooked-india.pages.dev/method), the BSI and ZSI acknowledgement in [docs/sources.md](./docs/sources.md).

### Transparency and accountability: ✅
Open source (MIT), open repository, and an open pipeline that runs on GitHub Actions in public. Each month is a dated snapshot. A published file never changes; a correction adds new files, and the progress log records it (for example, records that cannot go in a district, added to 2026-10 on 19 October 2026). Every GBIF figure cites its download DOI. The plan, the decisions and a dated progress log are in the repository. Mistakes found in the data are fixed in the open, with the fix and its effect recorded (for example, duplicate Catalogue of Life keys merged in October 2026).
Evidence: this repository, [docs/plan.md](./docs/plan.md), [docs/progress.md](./docs/progress.md), the workflow runs, the DOIs on the method page.

### Decentralisation and no lock-in: ✅
No account, no signup, no key. Every figure on the site comes from open JSON and Parquet files at stable paths under `/data/`, which anyone can download or read directly; the site is a static page over those files. The whole system (pipeline, data layout, site) is forkable and self-hostable from the MIT repository.
Evidence: [/llms.txt](https://overlooked-india.pages.dev/llms.txt) (the data layout), the download list on the method page, the [MIT licence](./LICENSE).

### Free software and the digital commons: 🟡
Code: MIT. Data and text: CC BY 4.0, Sathya Sankaran. The sources are respected rather than relicensed: each keeps its own terms, we use official APIs and downloads within their published rate limits, and we do not scrape sites that ask not to be scraped.
What falls short: not every upstream is fully open. IUCN Red List data is for non-commercial use with attribution; some GBIF datasets are CC BY-NC; BSI and ZSI material is reproduced free of charge with acknowledgement, not under an open licence. Overlooked is non-commercial and passes those terms on.
Direction: keep the per-source terms visible on every file, and prefer open sources where two say the same thing.

### Privacy: ✅
No accounts, no cookies, no email, no personal data, no advertising, no third-party fonts (the fonts are served from the site itself). Usage is counted server-side and in aggregate only, from the requests the site already makes (pages, and which group, state or two-letter search prefix a request asks for): no IP addresses, no identifiers, no per-person records, and no tracking script of our own. Page speed and page views come from Cloudflare Web Analytics, which is cookieless; it is the only script on the pages that is not ours, and we say so here.
Evidence: `functions/` (server-side counts), [docs/metrics.md](./docs/metrics.md), the page source.

### Built to be built on (cooperativism for infrastructure): 🟡
The data is the product: a master list with source tags, statuses, labels and per-state masks, documented in `/llms.txt`, free to reuse under CC BY 4.0 with the credits in each file. Others can build checklists, field lists, dashboards or research on it without asking. The front page lists Records to fix for data publishers: GBIF records from India with no exact location or no species name, the datasets that hold most of them, and links to correct them.
What falls short: a versioned JSON schema, an OpenAPI description, an MCP server for AI assistants, and embeddable species cards, as our sister projects offer.
Direction: publish the schema and an MCP server over the same files, so tools and assistants use the same canonical data with the credits attached.

### Humans in the loop (AI does not cut people out): ✅
No figure on the site is generated by a model: every number is computed from the sources by open code. For AI tools, the rights travel with the data: `licence`, `attribution` and `disclaimer` sit inside every summary file, `/llms.txt` asks that they are passed on, and the pages carry schema.org JSON-LD (a `Dataset` with `creditText` on the method page, a `WebSite` on the front page).
Evidence: `summary.json`, [/llms.txt](https://overlooked-india.pages.dev/llms.txt), the JSON-LD in the page source.

### A non-digital alternative must exist: 🟡
Overlooked informs; it does not replace any official process. The official channels (BSI, ZSI, IUCN, the state forest department) are named on every summary and on the method page. Each species page has a Next step block that names the place to act: the description, iNaturalist, GBIF, the Catalogue of Life, the IUCN Red List or the state forest department. The data can be downloaded and printed.
Direction: a printable monthly bulletin per state and group (field lists of species to look for and observations that need a name) for forest departments, BSI and ZSI regional centres, universities and naturalist groups.

### Grassroots and reaching the divide-affected: 🟡
The site is light (no map library, small files, fonts served from the site) and works on phones; each page is usable at 360 px.
What falls short: the interface is English only, species are shown by scientific name only, and the pages need JavaScript (a notice with links to the open files is shown without it).
Direction: common names in Indian languages from the sources that hold them, a localised interface, and pre-rendered plain HTML pages per species and per state that work without JavaScript and can be found in search.

### Algorithmic transparency: ✅
The few rules that shape the figures are public and in code: how names are matched to the Catalogue of Life (and kept, labelled, when they do not match), how duplicate keys are merged, how records that cannot go in a district (no coordinates, coordinates uncertain by more than 25 km, coordinates GBIF marks as possibly wrong) are placed by the state name as published, counted as observed and labelled by problem, what counts as observed and as identified, and how DNA-sequence records are labelled. No ranking or profiling of people.
Evidence: [Sources and method](https://overlooked-india.pages.dev/method), `pipeline/names.py`, `pipeline/unlocated.py`, `pipeline/ref/state_names.csv`, the tests in `tests/`.

## Fork this

Want to show your project follows PDGI? Map each principle to the concrete thing you do, link the evidence, and mark the gaps honestly. Copy this file as a template and keep it in your repo, where its git history becomes the record of your work. (We forked it from [mugilu](https://github.com/urbanmorph/mugilu/blob/main/PDGI.md), which forked it from [bharatlas](https://github.com/urbanmorph/geodata/blob/main/PDGI.md).)

Built by [Urban Morph](https://urbanmorph.com). PDGI framework: [pdgi.org](https://pdgi.org/).
