-- Overlooked usage metrics: first-party, server-side, aggregate (docs/metrics.md).
-- One counter per day per dimension per key. No IP, no cookies, no user agent string,
-- no per-user or per-visit rows. Dimensions are counted separately and never joined,
-- so the table cannot say which country opened which species.
--
-- dim        key
-- class      human | llm | bot          (HTML page requests, by client class)
-- page       /, /ledger, /species, ...  (human page views)
-- country    IN, US, ...                (Cloudflare country of the request)
-- device     mobile | tablet | desktop
-- ref        external referring host    (host only: google.com, no path or query)
-- view       observed | identified | iucn  (front page ?view= on load)
-- group      birds, insects, ...        (front page ?group= on load)
-- state      LGD state code             (front page ?state= on load)
-- species    GBIF key or COL ID         (/species?key= page opens)
-- search     two-letter search prefix   (search shard fetched; never the typed text)
-- group_open group index                (group file fetched on the front page)

CREATE TABLE IF NOT EXISTS daily (
  day  TEXT NOT NULL,              -- UTC date, YYYY-MM-DD
  dim  TEXT NOT NULL,
  key  TEXT NOT NULL,
  n    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, dim, key)
);
CREATE INDEX IF NOT EXISTS idx_daily_dim ON daily (dim, key);
