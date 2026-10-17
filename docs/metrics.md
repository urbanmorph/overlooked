# Usage metrics

Overlooked counts how the site is used so that we can improve it. The counts are first-party, server-side and aggregate. This follows the mugilu pattern (`mugilu/apps/worker/src/metrics.ts`): aggregate counters in D1, no IP, no cookies, no per-user rows, no client-side beacon.

## How it works

- `functions/_middleware.js` runs after each response is ready. It gives the response back unchanged.
- `functions/lib/metrics.js` (`observe`) looks at the request and the response and returns a list of counters to add. `record` adds them to D1 in one batch, inside `waitUntil`, so the visitor does not wait for it.
- All counts come from requests that the site already makes. The site sends no extra request for metrics.
- If the `DB` binding is absent, nothing is counted. If D1 fails, the error is ignored. A metrics error never changes or delays a page or a `/data/` file.
- `site/_routes.json` keeps `/assets/*` and `/fonts/*` out of the Functions, so static files do not use Functions requests.

## What is stored

One table, `daily(day, dim, key, n)`: one counter per UTC day, per dimension, per key (`migrations/0001_metrics.sql`).

| dim | key | from |
|---|---|---|
| `class` | `human`, `llm` or `bot` | each HTML page request |
| `page` | page path, for example `/ledger` | human HTML page views |
| `country` | two-letter country code | `request.cf.country` |
| `device` | `mobile`, `tablet` or `desktop` | the user agent, read and then dropped |
| `ref` | referring host, for example `google.com` | the `Referer` header; host only, our own hosts dropped |
| `view` | `observed`, `identified` or `iucn` | `?view=` on the front page |
| `group` | group key, for example `birds` | `?group=` on the front page |
| `state` | LGD state code | `?state=` on the front page |
| `species` | GBIF key or Catalogue of Life ID | `/species?key=` page opens |
| `search` | first two letters of a search, for example `pa` | the search file the front page fetches (`layers/master/<m>/search/<p>.json`) |
| `group_open` | group index | the group file the front page fetches (`layers/master/<m>/g/<gi>.json`) |

Only page views with status 200 and an HTML body count. Prefetches, HEAD requests, errors and other files do not count. Values that do not match a strict pattern (for example a long or strange `?group=`) are dropped, not stored.

Bots and AI crawlers add one `class` counter and nothing else (the same lists as mugilu), so the other counts show people.

## What is not stored

- No IP address, no cookie, no user agent string, no session or user ID.
- No search text. Only the two-letter prefix that picks the search file. The rest of the text stays in the browser.
- No full referrer URL. Only the host.
- No rows per visit. Each dimension is a separate counter, so the table cannot say which country opened which species, or which search came from which page.

## Limits

- **Filters are not recorded.** The filters on the front page run in the browser and send no request, so the server cannot see them.
- `?view=`, `?group=` and `?state=` show the state when a front page loads (a shared link or a reload). Changes made on the page update the address with `history.replaceState` and send no request, so they are not counted. Groups opened on the page are counted through `group_open`.
- The browser caches `/data/` files for 5 minutes, and the page fetches each file once per page load. So `search` and `group_open` count at most one per prefix or group per page load, and fewer when the browser cache answers.
- A counter can be low for a day when D1 drops a write. The counts are approximate.

## Retention

The counters hold no personal data, so they are kept. To delete old days, run:

```sh
npx wrangler d1 execute overlooked-metrics --remote --command "DELETE FROM daily WHERE day < date('now','-400 days')"
```

## Privacy paragraph (for PDGI.md)

> **Privacy.** No third-party analytics, no tracking scripts, no ad tech, no accounts and no personal data. The first-party usage counts we keep (to improve the site, not to sell) are aggregate and server-side: daily counters of page views, country, device class, referring host, species pages opened, groups opened, and the two-letter prefix of front-page searches. We store no IP address, no cookies, no user agent, no search text, no per-user or per-visit records, and the site sends no client-side beacon. Each count is kept separately, so no record links one visitor's country, searches and pages. Evidence: `functions/_middleware.js`, `functions/lib/metrics.js`, `migrations/0001_metrics.sql`, this file.

## Set-up steps (for the lead; not done by the code)

The D1 database `overlooked-metrics` exists (account `6ba72cdd965276a57d19bf0aadc4d551`, id `44a6390d-8ac8-4ba8-a4a9-3d06294978e0`). Still to do:

### 1. Apply the migration

With wrangler (no `wrangler.toml` is needed when the database is named):

```sh
set -a; . ./.env; set +a     # CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID; never echo them
npx wrangler d1 execute overlooked-metrics --remote --file migrations/0001_metrics.sql
npx wrangler d1 execute overlooked-metrics --remote --command "SELECT name FROM sqlite_master WHERE type='table'"
```

Or with the API:

```sh
python3 - <<'EOF' | curl -sS -X POST \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/d1/database/44a6390d-8ac8-4ba8-a4a9-3d06294978e0/query" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" --data @-
import json; print(json.dumps({"sql": open("migrations/0001_metrics.sql").read()}))
EOF
```

### 2. Add the D1 binding `DB` to the Pages project, keeping `DATA`

The binding name is `DB`, as in geodata, mdshare and twelveswaras. The project is git-connected and has no `wrangler.toml`, so set the binding in the dashboard (Workers & Pages > overlooked-india > Settings > Bindings > Add > D1 database, name `DB`, database `overlooked-metrics`, for Production and for Preview) or with the API. Send the R2 binding again in the same request, so that it stays:

```sh
curl -sS -X PATCH "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/overlooked-india" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" --data '{
  "deployment_configs": {
    "production": {
      "d1_databases": { "DB": { "id": "44a6390d-8ac8-4ba8-a4a9-3d06294978e0" } },
      "r2_buckets":   { "DATA": { "name": "'"$R2_BUCKET"'" } }
    },
    "preview": {
      "d1_databases": { "DB": { "id": "44a6390d-8ac8-4ba8-a4a9-3d06294978e0" } },
      "r2_buckets":   { "DATA": { "name": "'"$R2_BUCKET"'" } }
    }
  }
}' | python3 -c "import json,sys; r=json.load(sys.stdin); c=r['result']['deployment_configs']; print(r['success'], {e: sorted(list(c[e].get('d1_databases') or {}) + list(c[e].get('r2_buckets') or {})) for e in c})"
```

The last line prints only the binding names (expect `['DATA', 'DB']` for both). Bindings apply from the next deployment: push to `main` (or retry the latest deployment) after the change. Preview deployments write to the same database; to keep preview traffic out, bind a separate database for preview or leave preview without `DB`.

### 3. Turn on Web Analytics (RUM)

Workers & Pages > overlooked-india > Metrics > Web Analytics > Enable. This adds the Cloudflare beacon on the next deployment, like collect.bharatlas.com. This is Cloudflare Web Analytics (cookieless, no personal data); it is separate from the server-side counts above. Then put the GraphQL `siteTag` into `ops-dashboard/dashboard.py` (`APPS["overlooked"]["rum"]["tag"]`).

Note: the Web Analytics beacon is a client-side script. If the PDGI Privacy claim must say "no client-side beacon", do not turn it on, and rely on the server-side counts.

### Token permissions

The token in `.env` has R2 Storage Edit, Pages Edit and Account Settings Read. It cannot read D1 now (the D1 API answers 401). Add:

| Task | Permission |
|---|---|
| Apply the migration, delete old days | Account > D1 > Edit |
| Ops dashboard reads the counts | Account > D1 > Read (Edit includes it) |
| Add the binding to the Pages project | Account > Cloudflare Pages > Edit (already there) |
| Ops dashboard reads Web Analytics | Account > Account Analytics > Read (or set `CLOUDFLARE_ANALYTICS_TOKEN` in `.env`) |

Until the token has D1 Read, the ops dashboard falls back to geodata's token (same account).

## Tests

```sh
node --test tests/*.test.mjs
```
