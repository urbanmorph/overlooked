// First-party usage metrics, server-side and aggregate (the mugilu pattern, apps/worker/src/metrics.ts).
// Every count is derived from a request the site already makes: no client-side beacon, no cookies,
// no IP, no user agent string, no per-user rows. Each dimension is a separate daily counter, so two
// facts about one visit (its country and the species it opened) are never stored together.
// Writes are best-effort: a metrics failure must never change or delay a response.

const OWN_HOST = /(^|\.)overlooked-india\.pages\.dev$|^localhost$|^127\.0\.0\.1$/;
const VIEWS = new Set(['observed', 'identified', 'iucn']);
const GROUP = /^[a-z]{1,16}$/;        // front page group keys: birds, insects, plants, ...
const STATE = /^\d{1,3}$/;            // LGD state code
const SPECIES = /^[A-Za-z0-9]{1,20}$/; // GBIF usage key or Catalogue of Life ID
const SEARCH = /\/layers\/master\/[^/]+\/search\/([a-z_]{2})\.json$/;
const GROUP_FILE = /\/layers\/master\/[^/]+\/g\/(\d{1,4})\.json$/;

/** human, llm (AI crawlers and agents) or bot (search crawlers, scripts). Same lists as mugilu. */
export function clientClass(ua) {
  const s = (ua ?? '').toLowerCase();
  if (!s) return 'bot';
  if (/gptbot|chatgpt|oai-searchbot|openai|claudebot|claude-user|claude-web|anthropic|perplexity|google-extended|bytespider|amazonbot|applebot-extended|meta-externalagent|meta-externalfetcher|cohere-ai|youbot|ccbot|diffbot|mcp|modelcontextprotocol/.test(s)) return 'llm';
  if (/bot|crawl|spider|slurp|curl|wget|python|http-client|go-http|java\/|okhttp|libwww|headless|scan|monitor|facebookexternalhit|whatsapp|telegram|embedly|preview/.test(s)) return 'bot';
  return 'human';
}

/** mobile, tablet or desktop. */
export function deviceClass(ua) {
  const s = (ua ?? '').toLowerCase();
  if (/ipad|tablet|android(?!.*mobile)/.test(s)) return 'tablet';
  if (/mobi|iphone|ipod|android/.test(s)) return 'mobile';
  return 'desktop';
}

/** The referring host (no www, no path, no query), or null for none, our own pages, or junk. */
export function refHost(raw) {
  if (!raw) return null;
  try {
    const host = new URL(raw).hostname.toLowerCase().replace(/^www\./, '').replace(/[^a-z0-9.-]/g, '').slice(0, 60);
    return host && !OWN_HOST.test(host) ? host : null;
  } catch {
    return null;
  }
}

const pagePath = p => (p.replace(/\.html$/, '').replace(/\/index$/, '/').replace(/(.)\/+$/, '$1') || '/').slice(0, 64);

/** The [dimension, key] counters one request adds, given the response the site sent. Pure. */
export function observe(request, response) {
  if (request.method !== 'GET') return [];
  const h = request.headers;
  if (/prefetch|prerender/.test(`${h.get('sec-purpose') || ''} ${h.get('purpose') || ''}`)) return [];
  const url = new URL(request.url);
  const ua = h.get('user-agent');
  const cls = clientClass(ua);
  const ok = response.status === 200 || response.status === 206 || response.status === 304;

  if (url.pathname.startsWith('/data/')) {
    if (!ok || cls !== 'human') return [];
    const s = url.pathname.match(SEARCH);
    if (s) return [['search', s[1]]];
    const g = url.pathname.match(GROUP_FILE);
    if (g) return [['group_open', g[1]]];
    return [];
  }

  if (response.status !== 200 || !(response.headers.get('content-type') || '').includes('text/html')) return [];
  if (cls !== 'human') return [['class', cls]];

  const path = pagePath(url.pathname);
  const out = [['class', 'human'], ['page', path], ['device', deviceClass(ua)]];
  const country = request.cf?.country;
  if (typeof country === 'string' && /^[A-Z0-9]{2}$/.test(country)) out.push(['country', country]);
  const ref = refHost(h.get('referer'));
  if (ref) out.push(['ref', ref]);

  const q = url.searchParams;
  if (path === '/') {
    if (VIEWS.has(q.get('view'))) out.push(['view', q.get('view')]);
    if (GROUP.test(q.get('group') || '')) out.push(['group', q.get('group')]);
    if (STATE.test(q.get('state') || '')) out.push(['state', q.get('state')]);
  } else if (path === '/species' && SPECIES.test(q.get('key') || '')) {
    out.push(['species', q.get('key')]);
  }
  return out;
}

const UPSERT = 'INSERT INTO daily (day, dim, key, n) VALUES (?, ?, ?, 1) ON CONFLICT(day, dim, key) DO UPDATE SET n = n + 1';

/** Add the counters to D1 in one batch. Does nothing without a binding; never throws. */
export async function record(db, day, pairs) {
  if (!db || !pairs.length) return;
  try {
    const upsert = db.prepare(UPSERT);
    await db.batch(pairs.map(([dim, key]) => upsert.bind(day, dim, key)));
  } catch {
    // best-effort: metrics must never surface to a visitor
  }
}
