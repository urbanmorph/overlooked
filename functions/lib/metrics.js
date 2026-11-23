// First-party usage metrics, server-side and aggregate (the mugilu pattern, apps/worker/src/metrics.ts).
// Every count is derived from a request the site already makes: no client-side beacon, no cookies,
// no IP, no user agent string, no per-user rows. Each dimension is a separate daily counter, so two
// facts about one visit (its country and the species it opened) are never stored together.
// Writes are best-effort: a metrics failure must never change or delay a response.

const OWN_HOST = /(^|\.)yellide\.com$|(^|\.)overlooked-india\.pages\.dev$|^localhost$|^127\.0\.0\.1$/;
const VIEWS = new Set(['observed', 'recent', 'waiting', 'iucn', 'identified']);   // identified: old links (now waiting)
const GROUP = /^[a-z]{1,16}$/;        // front page group keys: birds, insects, plants, ...
const STATE = /^\d{1,3}$/;            // LGD state code
const SPECIES = /^[A-Za-z0-9]{1,20}$/; // GBIF usage key or Catalogue of Life ID
const SEARCH = /\/layers\/master\/[^/]+\/search\/([a-z_]{2})\.json$/;
const GROUP_FILE = /\/layers\/master\/[^/]+\/g\/(\d{1,4})\.json$/;
const GO_INAT = /^\/go\/inat\/[1-9]\d{0,11}$/;           // counted link to an iNaturalist observation
const SHORTLIST_GROUP = /^[a-z]{1,20}(-[a-z]{1,20}){0,4}$/; // shortlist group keys: true-bugs, bees-wasps-ants, ...

/** human, llm (AI crawlers and agents) or bot (search crawlers, scripts). Same lists as mugilu. */
export function clientClass(ua) {
  const s = (ua ?? '').toLowerCase();
  if (!s) return 'bot';
  if (/gptbot|chatgpt|oai-searchbot|openai|claudebot|claude-user|claude-web|anthropic|perplexity|google-extended|bytespider|amazonbot|applebot-extended|meta-externalagent|meta-externalfetcher|cohere-ai|youbot|ccbot|diffbot|mcp|modelcontextprotocol/.test(s)) return 'llm';
  if (/bot|crawl|spider|slurp|curl|wget|python|http-client|go-http|java\/|okhttp|libwww|headless|lightpanda|scan|monitor|facebookexternalhit|whatsapp|telegram|embedly|preview/.test(s)) return 'bot';
  return 'human';
}

/** Crawlers, monitors, link previews and empty agents: not use, for the counts by mode. Scripts (curl, python, node,
 *  DuckDB) and AI clients acting for a person (Claude-User, ChatGPT-User) are use: they are how the API and MCP are read. */
export function isBot(ua) {
  return !ua || /bot|crawl|spider|slurp|headless|lightpanda|scan|monitor|uptime|preview|facebookexternalhit|whatsapp|telegram|embedly|bytespider|google-extended|meta-external|cohere-ai/i.test(ua);
}

// MCP client products, from the client's own name at initialize; anything else is 'other', so a name someone gave
// their own client is never kept. The first match wins: a probe is a monitor whatever product it names, and
// cursor-vscode is cursor. One list for ops, yellide (overlooked) and mugilu, agreed 23 Nov 2026: the reference copy
// is ops-dashboard/worker/src/mcp-clients.js; keep the copies identical. A product name maps to itself.
const CLIENTS = [
  ['monitor', /probe|health|check|liveness|monitor|uptime|beat|registry|directory|census|catalog|glama/],
  ['claude-code', /claude[ -]?code/], ['claude-ai', /claude/], ['cursor', /cursor/], ['codex', /codex/],
  ['chatgpt', /chatgpt|openai/], ['windsurf', /windsurf|codeium/], ['vscode', /visual studio code|vscode|copilot/],
  ['gemini', /gemini/], ['cline', /\bcline\b/], ['zed', /^zed\b/], ['inspector', /inspector/],
];
export const MCP_CLIENTS = [...CLIENTS.map(([k]) => k), 'other'];

/** The MCP client product for a clientInfo.name: one of MCP_CLIENTS. */
export function mcpClient(name) {
  const s = typeof name === 'string' ? name.toLowerCase().slice(0, 100) : '';
  return CLIENTS.find(([, re]) => re.test(s))?.[0] ?? 'other';
}

/** Whether a request carries a browser's own headers: every current browser sends Accept-Language, and Sec-Fetch-*
 *  (Safari since 16.4). A client that names a browser but sends neither is a script or a headless browser. */
function browserHeaders(h) {
  if (h.has('accept-language')) return true;
  for (const k of h.keys()) if (k.startsWith('sec-fetch-')) return true;
  return false;
}

/** A fetch made by one of our own pages (the website), not by another site, a script, an agent, or a person who
 *  followed a link to the file (a navigation). Browsers without Sec-Fetch headers send our page as the Referer. */
function ownPage(h) {
  if (h.get('sec-fetch-mode') === 'navigate') return false;
  if (h.get('sec-fetch-site') === 'same-origin') return true;
  try { return OWN_HOST.test(new URL(h.get('referer')).hostname); } catch { return false; }
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

  // The redirect itself, not the page: only the group of the observation is kept, never its id.
  if (GO_INAT.test(url.pathname)) {
    const g = url.searchParams.get('g') || '';
    return response.status === 302 && cls === 'human' && SHORTLIST_GROUP.test(g) ? [['inat_out', g]] : [];
  }

  if (url.pathname.startsWith('/data/')) {
    if (!ok) return [];
    // Use by mode: a JSON file read by another site, a script or an agent is the API; another whole file is a
    // download (range reads, such as DuckDB's of a Parquet file, are parts of one and are not counted).
    if (!ownPage(h)) {
      if (isBot(ua)) return [];
      if (/\.json$/.test(url.pathname)) return [['mode', 'api']];
      return response.status === 200 ? [['mode', 'download']] : [];
    }
    if (cls !== 'human') return [];
    const s = url.pathname.match(SEARCH);
    if (s) return [['search', s[1]]];
    const g = url.pathname.match(GROUP_FILE);
    if (g) return [['group_open', g[1]]];
    return [];
  }

  if (response.status !== 200 || !(response.headers.get('content-type') || '').includes('text/html')) return [];
  if (cls !== 'human') return [['class', cls]];
  if (!browserHeaders(h)) return [['class', 'bot']];

  // a species page is one page, /species, whatever its key and slug (/species/<key>/<slug>)
  const own = url.pathname.match(/^\/species\/([^/]+)/);
  const path = own ? '/species' : pagePath(url.pathname);
  const out = [['class', 'human'], ['mode', 'website'], ['page', path], ['device', deviceClass(ua)]];
  const country = request.cf?.country;
  if (typeof country === 'string' && /^[A-Z0-9]{2}$/.test(country)) out.push(['country', country]);
  const ref = refHost(h.get('referer'));
  if (ref) out.push(['ref', ref]);

  const q = url.searchParams;
  if (path === '/') {
    if (VIEWS.has(q.get('view'))) out.push(['view', q.get('view')]);
    if (GROUP.test(q.get('group') || '')) out.push(['group', q.get('group')]);
    if (STATE.test(q.get('state') || '')) out.push(['state', q.get('state')]);
  } else if (path === '/species') {
    let key = q.get('key') || '';
    try { if (own) key = decodeURIComponent(own[1]); } catch { key = ''; }
    if (SPECIES.test(key)) out.push(['species', key]);
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
