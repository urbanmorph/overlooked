# How Overlooked follows PDGI

[Overlooked](https://yellide.com) is built on the principles of [People's Digital Goods and Infrastructure (PDGI)](https://pdgi.org/blog/peoples-digital-goods-and-infrastructure/): people before digital, rights-centric, commons-oriented, transparent. The categories are the ones [bharatlas](https://github.com/urbanmorph/geodata/blob/main/PDGI.md) uses.

Status key: ✅ implemented · 🟡 partial · ⛳ gap, with intended direction.

## Scorecard

### People before digital (rights and collective identity): 🟡
Overlooked holds no observations of its own and decides nothing about a species. It joins what others document (ZSI, BSI, Kew, the lichen and bryophyte checklists, GBIF, iNaturalist, Plazi, the IUCN Red List) and credits each one. A species that BSI or ZSI lists counts as documented, whatever an aggregator holds. Every page, file and MCP answer says that this is not an official checklist or conservation assessment, and sends people to BSI, ZSI, the IUCN Red List and the state forest department.
The smallest area published is a district; no coordinates. Every species is shown by district, threatened species too, with the year of its latest record there. These records are public on GBIF with their coordinates, and iNaturalist and many publishers make records of species at risk less exact before they reach GBIF. Every district page and answer says how to read the list and asks people to respect the species (Wild Life (Protection) Act, 1972).
Falls short: lists of threatened species by district are easier to find here than on GBIF.
Evidence: `licence`, `attribution` and `disclaimer` in every `summary.json` (`RIGHTS` in `pipeline/site_data.py`), [Sources and method](https://yellide.com/method), `DISTRICT_NOTE` and `RESPECT_NOTE` in `functions/lib/places.js`.

### Transparency and accountability: ✅
The pipeline runs in public on GitHub Actions. Each week is a dated build; a published file never changes. Every GBIF figure cites its download DOI. Decisions and corrections are in a dated progress log, with their effect (for example, duplicate Catalogue of Life keys merged in October 2026; every species shown by district from 14 November 2026).
Evidence: [docs/plan.md](./docs/plan.md), [docs/progress.md](./docs/progress.md), the workflow runs.

### Decentralisation and no lock-in: ✅
No account, no key. Every figure comes from open JSON and Parquet files at stable paths under `/data/` (CORS open); the site and the MCP server read the same files. The pipeline, data layout and site can be forked and hosted by anyone from the MIT repository.
Evidence: [/llms.txt](https://yellide.com/llms.txt), the [MIT licence](./LICENSE).

### Free software and the digital commons: 🟡
Code: MIT. Data and text: CC BY 4.0, Sathya Sankaran, free to reuse with the credits in each file. Each source keeps its own terms; we use official APIs and downloads within their limits.
Falls short: not every source is fully open. The IUCN Red List is non-commercial with attribution; some GBIF datasets are CC BY-NC; BSI and ZSI material is free to reproduce with acknowledgement, not under an open licence. Overlooked is non-commercial and passes those terms on.
Direction: prefer the open source where two say the same thing.

### Privacy: ✅
No accounts, no cookies, no personal data. Use is counted on the server in aggregate only (pages, and the group, state or search prefix asked for): no IP addresses, no identifiers. Cloudflare Web Analytics, cookieless, is the only script that is not ours.
Evidence: `functions/lib/metrics.js`, [docs/metrics.md](./docs/metrics.md).

### Platform cooperativism: 🟡
Contributions go to the sources, where they stay with their authors: the site sends people to name waiting observations on iNaturalist, and Records to fix lists GBIF records from India with no exact place or no species name, by dataset, so publishers correct them at the source. Checklists, field lists, dashboards and research can build on the list without asking.
Falls short: no shared governance: one person decides, in the open. Anyone can raise an issue or a pull request.
Direction: let the people who use and correct the list (taxonomists, naturalist groups, data publishers) take part in its decisions.

### Humans in the loop (AI does not cut people out): ✅
No figure is made by a model. AI names stay a shortlist: a taxonomist approves every name, and no AI identification is posted to iNaturalist. The MCP server ([/mcp](https://yellide.com/mcp), no key, read only) gives AI assistants the list with `licence`, `attribution` and `disclaimer` in every answer, and its instructions and `/llms.txt` ask that they are passed on. The pages carry schema.org JSON-LD (a `Dataset` with `creditText` on the method page).
Evidence: `functions/lib/mcp.js`, [/llms.txt](https://yellide.com/llms.txt), the JSON-LD in the page source.

### A non-digital alternative must exist: 🟡
Overlooked informs; it replaces no official process. The official channels (BSI, ZSI, the IUCN Red List, the state forest department) are named on every summary, and each species page names the place to act. The data can be downloaded and printed.
Direction: a printable bulletin per state and group for forest departments, BSI and ZSI regional centres, universities and naturalist groups.

### Grassroots and reaching the divide-affected: 🟡
The pages are light (no map library, fonts from the site) and work at 360 px. Species and place pages give a plain summary without JavaScript.
Falls short: the interface is English only; search takes Latin and English names, not names in Indian languages (about 6,000 species have them, from Wikidata).
Direction: search by names in Indian languages; through the MCP server, an AI assistant can take a question in any Indian language and answer from the same data.

### Algorithmic fairness: 🟡
No one is ranked or profiled. Every number is computed from the sources by open code, and the rules are on the method page: name matching to the Catalogue of Life, merged keys, records placed by district and by WII province, what counts as an open record.
Falls short: the records follow where people look. Districts and groups with few naturalists show fewer species; the pages say so, but the figures are not corrected for it.
Direction: give the records and observers of a place beside its species count.
Evidence: [Sources and method](https://yellide.com/method), `pipeline/names.py`, `pipeline/places.py`, `pipeline/biogeo.py`.

Built by [Urban Morph](https://urbanmorph.com).
