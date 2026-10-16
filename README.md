# Overlooked

A national monitor of the gaps in India's public biodiversity data. It updates itself each month.

Each month it rebuilds from dated snapshots of public sources and shows what changed since the last run.
It holds no sightings and takes no user input. Every figure links back to its source and snapshot.

It follows the data story [The Overlooked Species](https://overlooked-species.surge.sh).

## Modules

1. **Last-seen ledger.** For each species and district: when was the latest public record?
2. **Change feed.** What changed since last month.
3. **Follow-up on new species.** Species described from India since 2015: recorded since, or still waiting?

Later: official lists against public records, the identification backlog, and where the data flow stops.

## How it works

- A monthly GitHub Actions job runs the pipeline (Python, DuckDB) and writes Parquet files to Cloudflare R2.
- The site is static, on Cloudflare. DuckDB-WASM queries the Parquet files in the browser. There is no server.
- District boundaries come from LGD, through [bharatlas](https://bharatlas.com).

## Status

Early design. Nothing is published yet.

## Licence

Code: MIT. Data and text on the site: CC BY 4.0, credited to Sathya Sankaran.
Each source keeps its own licence and is credited on the site.
