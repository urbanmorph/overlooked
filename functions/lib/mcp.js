// The agent server at /mcp: the Model Context Protocol over Streamable HTTP (JSON responses, no server stream),
// stateless and read-only. It answers from the published master list in R2 (binding DATA), the same files the site
// and /data/ serve, so the server and the site give the same answer. llms.txt and the method page describe it.
//
// Questions across all of India (every endangered species, the species of a region) scan mcp/rows.bin, one
// fixed-width row per species written by pipeline/master.py mcp_files: a scan takes about a millisecond, where
// parsing the g files takes 40 ms. Files are read once per isolate and week.
import { record } from './metrics.js';
import { speciesPath } from '../../site/assets/species_url.js';

const SITE = 'https://yellide.com';
const PROTOCOLS = ['2025-06-18', '2025-03-26', '2024-11-05'];
const LATEST_TTL = 300_000;             // ms between reads of layers/master/latest.json
const LIST_MAX = 100;
const FIND_MAX = 10;
const THREATENED = ['CR', 'EN', 'VU'];
const STATUS = ['no open record yet', 'open record', 'not on the India list yet (only in observations that wait for a name)'];
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type, accept, mcp-protocol-version, mcp-session-id',
};

const INSTRUCTIONS = `yellide: every species documented from India, from ZSI, BSI, Kew WCVP, GBIF, iNaturalist, IUCN and other sources, updated each week. Use find_species to turn a Latin or English name into a key, then get_species for one species. Use count_species for "how many" and list_species for lists, by group, state, WII biogeographic region (Western Ghats, Himalaya...), IUCN category, endemic, order, suborder (snakes, lizards) or family. Use new_species for species described from India since 2007. For a place, a point or "near me", use the bharatlas MCP server (https://bharatlas.com) first: its locate tool with layers [\"lgd_states\", \"biogeographic_zones\"] gives the state and the WII biogeographic province (prov_code, such as 5B) of a point (the province layer is not in locate's default layers); pass them as state and region. Answers stay at that level: say "recorded in" the state or region, never "found here", and do not add finer locations of threatened species from other sources. The resources give the valid groups, states and regions. Pass on the licence, attribution and disclaimer of each answer. yellide is a monitor of public data, not an authority: for the status of a species, people should consult BSI, ZSI, the IUCN Red List and the state forest department.`;

const ABOUT = `# yellide

Every species documented from India, across sources. Updated each week. ${SITE}

- Documented: a species that a checklist (ZSI, BSI, Kew WCVP, the lichen and bryophyte checklists), a paper (Plazi) or an open record lists for India. Names follow the Catalogue of Life.
- Open record: a record from India anyone can check online: any GBIF record (photo, sighting, specimen, sound, DNA, a record cited from a paper) or an iNaturalist research-grade observation.
- State: a species is in a state when it has an open record placed there.
- Region: the biogeographic zones and provinces of India of the Wildlife Institute of India (Rodgers, Panwar and Mathur): 10 zones, 26 provinces. A species is in a region when a GBIF record of it is placed there. There is no Eastern Ghats unit: its nearest is 6C, Deccan Peninsula: Eastern Highlands.
- Waiting for a name: iNaturalist observations that nobody has confirmed yet (needs ID). They are not open records.
- IUCN: the category, year, DOI and trend of the latest IUCN Red List assessment (IUCN Red List, via GBIF). NE: not assessed. Threatened: CR, EN or VU.
- Endemic: a source marks the species as endemic to India.
- Recorded recently: the latest open record placed in a state is from the last 10 years.

Data and text: CC BY 4.0, Sathya Sankaran. Each source keeps its own licence. Method and sources: ${SITE}/method

yellide is a monitor of public data, not an authority. For the status of a species, consult BSI, ZSI, the IUCN Red List and the state forest department.`;

// ---------------------------------------------------------------- data

/** FNV-1a 32-bit of the UTF-8 key, modulo 512: pipeline/site_data.py shard_of and site/assets/species.js. */
export function shardOf(key) {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(String(key))) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
  return h % 512;
}

class ToolError extends Error {}
const plain = s => String(s ?? '').toLowerCase().replace(/['’]/g, '').replace(/[-\s]+/g, ' ').trim();
// pipeline/master.py prefix: the first two letters, lower case ASCII; anything else is '_'.
const prefix = s => [...String(s).toLowerCase().slice(0, 2)].map(c => (c >= 'a' && c <= 'z' ? c : '_')).join('').padEnd(2, '_');
const url = (key, name) => (key ? SITE + speciesPath(key, name) : null);

let memo = { checked: 0, base: null, week: null, files: new Map() };
/** For tests: forget what this isolate has read. */
export function _reset() { memo = { checked: 0, base: null, week: null, files: new Map() }; }

async function r2(env, key, kind = 'json') {
  const o = await env.DATA.get(key);
  if (!o) return null;
  return kind === 'json' ? o.json() : o.arrayBuffer();
}

/** The current week of the master list (re-read every LATEST_TTL); the cache empties when the week changes. */
async function current(env) {
  if (!memo.base || Date.now() - memo.checked > LATEST_TTL) {
    const latest = await r2(env, 'layers/master/latest.json');
    if (!latest?.base) throw new Error('no published list');
    if (latest.base !== memo.base) memo.files = new Map();
    Object.assign(memo, { base: latest.base, week: latest.period, checked: Date.now() });
  }
  return memo;
}

/** Keep a read (a promise) for the isolate and week; a failed read is dropped, so the next call tries again. */
function kept(m, id, read) {
  if (!m.files.has(id)) m.files.set(id, read().catch(e => { m.files.delete(id); throw e; }));
  return m.files.get(id);
}

/** A file of the current list. The index, summary and meta files are kept for the isolate and week; the shards
 *  (sp, pic, search: 1,400 files, 60 MB) are read each time, so an isolate never grows past its memory limit.
 *  Missing files are null. */
async function file(env, path, kind = 'json', keep = true) {
  const m = await current(env);
  return keep ? kept(m, path, () => r2(env, m.base + path, kind)) : r2(env, m.base + path, kind);
}
const shard = (env, path) => file(env, path, 'json', false);

const ARRAYS = { u8: Uint8Array, u16: Uint16Array, u32: Uint32Array };

/** The species index as typed-array columns (col.<field>[row]; nul.<field>: the value that means null), built once per
 *  isolate and week: a scan over all of India then reads plain arrays. */
async function index(env) {
  const m = await current(env);
  return kept(m, '@index', () => columns(env));
}

async function columns(env) {
  const [meta, rows, text] = await Promise.all([file(env, 'mcp/meta.json'), file(env, 'mcp/rows.bin', 'bin'), file(env, 'mcp/text.txt', 'bin')]);
  if (!meta || !rows || !text) throw new Error('this list has no agent index yet');
  const view = new DataView(rows), n = meta.rows, w = meta.row_bytes, col = {}, nul = {};
  for (const [f, [off, type, nv]] of Object.entries(meta.fields)) {
    const a = new ARRAYS[type](n);
    if (type === 'u8') for (let i = 0; i < n; i++) a[i] = view.getUint8(i * w + off);
    else if (type === 'u16') for (let i = 0; i < n; i++) a[i] = view.getUint16(i * w + off, true);
    else for (let i = 0; i < n; i++) a[i] = view.getUint32(i * w + off, true);
    col[f] = a;
    nul[f] = nv;
  }
  const val = (f, i) => (col[f][i] === nul[f] ? null : col[f][i]);
  const bytes = new Uint8Array(text), dec = new TextDecoder();
  const names = i => {
    const at = col.text[i];
    let end = at; while (bytes[end] !== 10) end++;
    const [key, name, english] = dec.decode(bytes.subarray(at, end)).split('\t');
    return { key: key || null, name, english: english || null };
  };
  return { n, col, nul, val, names, families: meta.families };
}

// ---------------------------------------------------------------- filters

const oneOf = (what, value, valid) => {
  throw new ToolError(`Unknown ${what} "${value}". Valid values: ${valid.join(', ')}.`);
};

function groupsOf(S, value) {
  const q = plain(value);
  const exact = S.groups.findIndex(g => plain(g) === q);
  if (exact >= 0) return [exact];
  const some = S.groups.flatMap((g, i) => (plain(g).includes(q) ? [i] : []));
  return some.length ? some : oneOf('group', value, S.groups);
}

function stateOf(S, value) {
  const q = plain(value);
  const i = S.states.findIndex(s => plain(s.name) === q || s.code === String(value));
  return i >= 0 ? i : oneOf('state', value, S.states.map(s => s.name));
}

/** A province code (5B), a province (Western Ghats: Mountains) or a zone (Western Ghats): the province bits. */
function regionBits(S, value) {
  const q = plain(value);
  const bits = S.provinces.flatMap(([code, prov, zone], i) =>
    (plain(code) === q || plain(prov) === q || plain(zone) === q ? [i] : []));
  if (bits.length) return bits;
  const hint = /eastern ghats/.test(q) ? ' There is no Eastern Ghats unit in the WII classification: its nearest is 6C, Deccan Peninsula: Eastern Highlands.' : '';
  throw new ToolError(`Unknown region "${value}".${hint} Valid zones: ${[...new Set(S.provinces.map(p => p[2]))].join(', ')}; or a province code (${S.provinces.map(p => p[0]).join(', ')}). See the resource yellide://regions.`);
}

function iucnSet(S, values) {
  const out = [];
  for (const v of [].concat(values)) {
    const c = String(v).toUpperCase();
    if (c === 'THREATENED') THREATENED.forEach(t => out.push(S.iucn.indexOf(t)));
    else if (S.iucn.includes(c)) out.push(S.iucn.indexOf(c));
    else oneOf('IUCN category', v, [...S.iucn, 'threatened']);
  }
  return out;
}

const SUBORDER_WORDS = { snake: 'Serpentes', snakes: 'Serpentes', lizard: 'Sauria', lizards: 'Sauria' };

/** A table to test a small index value (group, IUCN category) in one read. */
const table = (size, ids) => { const t = new Uint8Array(size); for (const i of ids) t[i] = 1; return t; };

const year = (what, v) => {
  const y = Number(v);
  if (!Number.isInteger(y) || y < 1000 || y > 3000) throw new ToolError(`${what} must be a year, such as 2020.`);
  return y;
};

/** The filter arguments of count_species and list_species, as one test of an index row. */
function filter(S, ix, a) {
  const tests = [], { col, nul } = ix;
  if (a.group != null) { const t = table(256, groupsOf(S, a.group)), g = col.group; tests.push(i => t[g[i]] === 1); }
  if (a.state != null) {
    const b = stateOf(S, a.state), m = b < 32 ? col.states_lo : col.states_hi, k = b % 32;
    tests.push(i => ((m[i] >>> k) & 1) === 1);
  }
  if (a.region != null) {
    let mask = 0;
    for (const b of regionBits(S, a.region)) mask |= 1 << b;
    const p = col.provinces, none = nul.provinces;
    tests.push(i => p[i] !== none && (p[i] & mask) !== 0);
  }
  if (a.iucn != null) { const t = table(256, iucnSet(S, a.iucn)), c = col.iucn; tests.push(i => t[c[i]] === 1); }
  if (a.endemic != null) {
    const b = S.labels.findIndex(l => l.code === 'end'), want = a.endemic ? 1 : 0, l = col.labels;
    tests.push(i => ((l[i] >>> b) & 1) === want);
  }
  if (a.order != null) {
    const o = S.orders.findIndex(x => plain(x) === plain(a.order)), c = col.order;
    if (o < 0) oneOf('order', a.order, ['an order name such as Squamata, Anura, Lepidoptera or Orchidales (Latin)']);
    tests.push(i => c[i] === o);
  }
  if (a.suborder != null) {
    const name = SUBORDER_WORDS[plain(a.suborder)] || a.suborder;
    const s = S.suborders.findIndex(x => plain(x) === plain(name)), c = col.suborder;
    if (s < 0) oneOf('suborder', a.suborder, ['Serpentes (snakes)', 'Sauria (lizards)']);
    tests.push(i => c[i] === s);
  }
  if (a.family != null) {
    const f = ix.families.findIndex(x => plain(x) === plain(a.family)), c = col.family;
    if (f < 0) oneOf('family', a.family, ['a family name in Latin, such as Elapidae or Orchidaceae']);
    tests.push(i => c[i] === f);
  }
  if (a.open_record != null) { const want = a.open_record ? 1 : 0, c = col.status; tests.push(i => (c[i] === 1 ? 1 : 0) === want); }
  // 0 means null for the years, so "since" leaves out species with no year.
  if (a.recorded_since != null) { const y = year('recorded_since', a.recorded_since), c = col.last_year; tests.push(i => c[i] >= y); }
  if (a.described_since != null) { const y = year('described_since', a.described_since), c = col.described; tests.push(i => c[i] >= y); }
  const k = tests.length;
  return i => { for (let t = 0; t < k; t++) if (!tests[t](i)) return false; return true; };
}

/** Groups where no source marks any species as endemic (computed once per index). */
function unmarked(S, ix) {
  if (!ix.unmarked) {
    const end = S.labels.findIndex(l => l.code === 'end'), marked = new Set();
    const { labels, group } = ix.col;
    for (let i = 0; i < ix.n; i++) if ((labels[i] >>> end) & 1) marked.add(group[i]);
    ix.unmarked = S.groups.filter((_, g) => !marked.has(g));
  }
  return ix.unmarked;
}

function filterNote(S, ix, a) {
  const notes = [];
  if (a.endemic != null) {
    notes.push('Endemic marks come from the sources that give them (Kew WCVP for plants, ZSI and other checklists for some animal groups). '
      + `These groups have no endemic mark yet: ${unmarked(S, ix).join('; ')}. There, 0 endemic means not marked, not that none is endemic.`);
  }
  if (a.state != null) notes.push('A species is in a state when it has an open record placed there.');
  if (a.state != null && a.region != null) {
    notes.push('With a state and a region: species with records in the state and records in the region, not always in the part where they meet.');
  }
  if (a.region != null) notes.push('A species is in a region when a GBIF record of it is placed there (WII biogeographic provinces).');
  if (a.recorded_since != null) notes.push('Recorded since: the latest open record placed in any state of India.');
  return notes.join(' ') || undefined;
}

// ---------------------------------------------------------------- tools

// Places: no tool takes or gives a place finer than a state or a WII biogeographic province. Lists of threatened
// species by district and recent year are what collectors and traders look for (method page, Sensitive locations);
// the species pages and open files stop at the district. A district filter needs per-species rules first.
// tests/mcp.test.mjs keeps this.

const FILTERS = {
  group: { type: 'string', description: 'A group of the list, or a word of it: "Birds", "butterflies", "mammals" (all mammal groups), "orchids". See yellide://groups.' },
  state: { type: 'string', description: 'A state or union territory of India: "Karnataka". See yellide://states.' },
  region: { type: 'string', description: 'A WII biogeographic zone ("Western Ghats", "Himalaya", "North-East", "Islands"), a province ("Western Ghats: Mountains") or a province code ("5B"). See yellide://regions.' },
  iucn: { type: 'array', items: { type: 'string' }, description: 'IUCN Red List categories: CR, EN, VU, NT, LC, DD, NE (not assessed), or "threatened" (CR, EN, VU).' },
  endemic: { type: 'boolean', description: 'true: only species a source marks as endemic to India; false: only species not marked. Some groups have no marks yet (the answer names them).' },
  order: { type: 'string', description: 'An order (Latin): "Squamata", "Anura" (frogs), "Lepidoptera".' },
  suborder: { type: 'string', description: 'For order Squamata: "snakes" (Serpentes) or "lizards" (Sauria).' },
  family: { type: 'string', description: 'A family (Latin): "Elapidae", "Orchidaceae".' },
  open_record: { type: 'boolean', description: 'true: species with an open record from India; false: species known only from checklists and papers.' },
  recorded_since: { type: 'integer', description: 'Species with an open record placed in a state in this year or later.' },
  described_since: { type: 'integer', description: 'Species described in this year or later.' },
};

const TOOLS = [
  {
    name: 'find_species', title: 'Find a species by name',
    description: 'Find species of India by Latin name or English common name (any word of it, from its start: "great indian bustard", "naja", "cobra"). Returns up to 10 species with their key for get_species, group, IUCN category and status.',
    inputSchema: { type: 'object', properties: { name: { type: 'string', description: 'A Latin or English name, or its start.' } }, required: ['name'] },
    run: findSpecies,
  },
  {
    name: 'get_species', title: 'One species in full',
    description: 'One species of India by its key (from find_species or list_species): sources that list it, open record, states with an open record, WII regions, IUCN category with the year, DOI and trend of the assessment, endemic, year described and authority, family and order, evidence (type specimens, photos, DNA barcodes), names in Indian languages, a photo with its credit, and iNaturalist observations that wait for a name.',
    inputSchema: { type: 'object', properties: { key: { type: 'string', description: 'The species key, such as "GCMS".' } }, required: ['key'] },
    run: getSpecies,
  },
  {
    name: 'count_species', title: 'Count species',
    description: 'How many species of India: documented, with an open record, threatened (IUCN CR, EN, VU), recorded in the last 10 years, endemic, and per IUCN category. All filters are optional and combine: "how many butterflies in India", "threatened birds in Kerala", "endemic frogs of the Western Ghats".',
    inputSchema: { type: 'object', properties: FILTERS },
    run: countSpecies,
  },
  {
    name: 'list_species', title: 'List species',
    description: 'List species of India with optional filters that combine: "critically endangered species in India", "endangered animals in Karnataka", "snakes of the Western Ghats", "birds of Goa recorded since 2020". Rows by group, then Latin name; up to 100 per page, with the total and a cursor for the next page.',
    inputSchema: {
      type: 'object',
      properties: { ...FILTERS, limit: { type: 'integer', description: 'Rows per page, 1 to 100 (default 50).' }, cursor: { type: 'string', description: 'next_cursor from the previous page.' } },
    },
    run: listSpecies,
  },
  {
    name: 'new_species', title: 'New species described from India',
    description: 'Species described from India since a year (2007 or later), from Plazi, the BSI Plant Discoveries and the ZSI Animal Discoveries: the year, the group, the state of the type locality, the journal and a link to the paper, and whether it has been recorded since. "new species discovered in India 2025", "new frog species from India".',
    inputSchema: {
      type: 'object',
      properties: {
        since: { type: 'integer', description: 'Described in this year or later (2007 or later).' },
        group: FILTERS.group, state: { type: 'string', description: 'The state of the type locality.' },
        limit: { type: 'integer', description: 'Rows per page, 1 to 100 (default 50).' }, cursor: { type: 'string', description: 'next_cursor from the previous page.' },
      },
      required: ['since'],
    },
    run: newSpecies,
  },
];
for (const t of TOOLS) t.annotations = { readOnlyHint: true, openWorldHint: false };

const pageOf = a => ({ limit: Math.min(Math.max(Number(a.limit) || 50, 1), LIST_MAX), from: Math.max(Number(a.cursor) || 0, 0) });

async function findSpecies(env, S, a) {
  const q = plain(a.name);
  if (q.length < 2) throw new ToolError('Give at least two letters of a name.');
  const f = await shard(env, `search/${prefix(q)}.json`);
  const by = new Map();
  for (const r of f?.rows || []) {
    const n = plain(r[0]);
    if (!(n.startsWith(q) || n.includes(' ' + q))) continue;
    const common = r.length > 8, id = r[1] || 'n:' + (common ? r[8] : r[0]);
    const s = by.get(id) || { key: r[1] || null, name: common ? r[8] : r[0], english: null, group: S.groups[r[2]],
      iucn: S.iucn[r[4]], status: STATUS[r[3]], described: r[7], url: url(r[1], common ? r[8] : r[0]), exact: false };
    if (common && !s.english) s.english = r[0];
    s.exact ||= n === q;
    by.set(id, s);
  }
  const species = [...by.values()].sort((x, y) => y.exact - x.exact).slice(0, FIND_MAX).map(({ exact, ...s }) => s);
  // A Latin name's English name is in the search file of its own first letters: take it from the picture file.
  await Promise.all(species.filter(s => s.key && !s.english).map(async s => {
    s.english = (await shard(env, `pic/${shardOf(s.key)}.json`))?.[s.key]?.[5] || null;
  }));
  return { species };
}

async function getSpecies(env, S, a) {
  const key = String(a.key || '');
  const sh = shardOf(key);
  const [sp, pics] = await Promise.all([shard(env, `sp/${sh}.json`), shard(env, `pic/${sh}.json`)]);
  const r = sp?.[key];
  if (!r) throw new ToolError(`No species with key "${key}". Use find_species to get a key.`);
  const [name, gi, sources, status, iucn, labels, states, taxon, nIndia, , year, authority, paper, iucnYear, iucnDoi,
    partners, interIndia, , types, photos, barcode, local, , , , , , iucnTrend, family, order, suborder, provinces] = r;
  const pic = pics?.[key];
  const end = S.labels.findIndex(l => l.code === 'end');
  const place = S.waiting?.places?.india;
  const prov = new Map(S.provinces.map(p => [p[0], p[1]]));
  return {
    key, name, english: pic?.[5] || null, group: S.groups[gi], family: family || null, order: order || null, suborder: suborder || null,
    status: STATUS[status], open_record: status === 1,
    iucn: { category: S.iucn[iucn], year: iucnYear ?? null, doi: iucnDoi ?? null, trend: iucnTrend ?? null },
    endemic: end >= 0 && Math.floor(labels / 2 ** end) % 2 === 1,
    sources: S.sources.filter((_, i) => Math.floor(sources / 2 ** i) % 2 === 1),
    states_with_open_record: S.states.filter((_, i) => Math.floor(states / 2 ** i) % 2 === 1).map(s => s.name),
    regions: provinces ? provinces.map(c => `${c} ${prov.get(c) ?? ''}`.trim()) : null,
    described: { year: year ?? null, authority: authority ?? null },
    paper: paper ? { journal: paper[1] || null, link: paper[2] || null, records_after: paper[3] ?? null } : null,
    evidence: { type_specimen_records_from_india: types ?? null, photo_records_from_india: photos ?? null,
      dna_barcode: ['none', 'yes, not from India', 'yes, from India'][barcode] ?? null },
    interactions: partners == null ? null : { partner_species: partners, recorded_in_india: Boolean(interIndia) },
    names_in_indian_languages: local || null,
    photo: pic ? { url: pic[0], page: pic[1], credit: [pic[2], pic[3], pic[4]].filter(Boolean).join(', ') } : null,
    waiting_for_a_name: taxon ? {
      observations_in_india: nIndia,
      identify: `https://www.inaturalist.org/observations/identify?quality_grade=needs_id&taxon_id=${taxon}&place_id=${place}`,
    } : null,
    url: url(key, name),
  };
}

/** One species as get_species gives it, with the summary and the week, for the species page (functions/species/[[path]].js).
 *  null when the list has no such key. */
export async function lookupSpecies(env, key) {
  const S = await file(env, 'summary.json');
  try {
    return { S, s: await getSpecies(env, S, { key }), week: memo.week };
  } catch (e) {
    if (e instanceof ToolError) return null;
    throw e;
  }
}

async function countSpecies(env, S, a) {
  const ix = await index(env);
  const ok = filter(S, ix, a), { status, iucn, last_year: last, labels } = ix.col;
  const thr = table(256, THREATENED.map(c => S.iucn.indexOf(c))), end = S.labels.findIndex(l => l.code === 'end');
  const since = S.recent_from, byIucn = new Array(S.iucn.length).fill(0);
  let documented = 0, open = 0, threatened = 0, recent = 0, endemic = 0;
  for (let i = 0; i < ix.n; i++) {
    if (!ok(i)) continue;
    documented++;
    if (status[i] === 1) open++;
    byIucn[iucn[i]]++;
    threatened += thr[iucn[i]];
    if (last[i] >= since) recent++;
    endemic += (labels[i] >>> end) & 1;
  }
  return {
    counts: { documented, open_record: open, threatened, [`recorded_since_${since}`]: recent, endemic },
    by_iucn: Object.fromEntries(S.iucn.flatMap((k, i) => (byIucn[i] ? [[k, byIucn[i]]] : []))), note: filterNote(S, ix, a),
  };
}

async function listSpecies(env, S, a) {
  const ix = await index(env);
  const ok = filter(S, ix, a), { col, val } = ix, { limit, from } = pageOf(a);
  const end = S.labels.findIndex(l => l.code === 'end');
  const species = [];
  let total = 0, next = null;
  for (let i = 0; i < ix.n; i++) {
    if (!ok(i)) continue;
    total++;
    if (i < from) continue;
    if (species.length === limit) { next ??= String(i); continue; }
    const { key, name, english } = ix.names(i), f = val('family', i);
    species.push({ key, name, english, group: S.groups[col.group[i]], family: f == null ? null : ix.families[f],
      iucn: S.iucn[col.iucn[i]], endemic: ((col.labels[i] >>> end) & 1) === 1, open_record: col.status[i] === 1,
      latest_record_year: val('last_year', i), described: val('described', i), url: url(key, name) });
  }
  return { total, species, next_cursor: next, note: filterNote(S, ix, a) };
}

async function newSpecies(env, S, a) {
  const m = await current(env);
  const ns = await kept(m, '@newspecies', async () => {
    const latest = await r2(env, 'layers/newspecies/latest.json');
    return latest?.file ? r2(env, latest.file) : null;
  });
  if (!ns) throw new Error('no published new species list');
  const since = year('since', a.since);
  if (since < ns.first_year) throw new ToolError(`since must be ${ns.first_year} or later.`);
  const { columns: c, lookups: l } = ns, { limit, from } = pageOf(a);
  const groups = a.group != null ? new Set(l.group.flatMap((g, i) => (plain(g).includes(plain(a.group)) ? [i] : []))) : null;
  if (groups && !groups.size) oneOf('group', a.group, l.group.filter(Boolean));
  const state = a.state != null ? l.state.findIndex(s => plain(s) === plain(a.state)) : null;
  if (state === -1) oneOf('state', a.state, l.state.filter(Boolean));
  const species = [];
  let total = 0, next = null;
  for (let i = 0; i < c.name.length; i++) {
    if (c.year[i] < since || (groups && !groups.has(c.group[i])) || (state != null && c.state[i] !== state)) continue;
    total++;
    if (i < from) continue;
    if (species.length === limit) { next ??= String(i); continue; }
    const link = (l.link[c.link[i]] || '') + (c.link_rest[i] || '');
    species.push({ name: c.name[i], key: c.key[i] || null, year: c.year[i], group: l.group[c.group[i]] || null,
      type_locality_state: l.state[c.state[i]] || null, journal: l.journal[c.journal[i]] || null, link: link || null,
      sources: l.sources[c.sources[i]], records_since_description: l.status[c.status[i]], latest_record_after: c.latest_after[i],
      url: url(c.key[i], c.name[i]) });
  }
  return { total, species, next_cursor: next };
}

// ---------------------------------------------------------------- resources

const RESOURCES = [
  { uri: 'yellide://about', name: 'about', title: 'What yellide is', mimeType: 'text/markdown', text: () => ABOUT },
  { uri: 'yellide://groups', name: 'groups', title: 'Groups of the list', mimeType: 'application/json', text: S => JSON.stringify(S.groups) },
  { uri: 'yellide://states', name: 'states', title: 'States and union territories', mimeType: 'application/json', text: S => JSON.stringify(S.states.map(s => s.name)) },
  {
    uri: 'yellide://regions', name: 'regions', title: 'WII biogeographic zones and provinces', mimeType: 'application/json',
    text: S => {
      const zones = {};
      for (const [code, , zone] of S.provinces) (zones[zone] ||= []).push(code);
      return JSON.stringify({ source: 'Wildlife Institute of India (Rodgers, Panwar and Mathur), GODL-India, via bharatlas', zones,
        provinces: S.provinces.map(([code, province, zone]) => ({ code, province, zone })),
        note: 'There is no Eastern Ghats unit: its nearest is 6C, Deccan Peninsula: Eastern Highlands.' });
    },
  },
];

// ---------------------------------------------------------------- JSON-RPC

const reply = (id, result) => ({ jsonrpc: '2.0', id, result });
const fail = (id, code, message) => ({ jsonrpc: '2.0', id: id ?? null, error: { code, message } });

async function answer(msg, env, metric) {
  const { id, method, params = {} } = msg || {};
  if (!msg || msg.jsonrpc !== '2.0' || typeof method !== 'string') return fail(id, -32600, 'Invalid request');
  if (id === undefined) return null;                    // a notification: nothing to answer
  switch (method) {
    case 'initialize':
      return reply(id, {
        protocolVersion: PROTOCOLS.includes(params.protocolVersion) ? params.protocolVersion : PROTOCOLS[0],
        capabilities: { tools: {}, resources: {} },
        serverInfo: { name: 'yellide', title: 'yellide: species of India', version: '1.0.0', websiteUrl: SITE },
        instructions: INSTRUCTIONS,
      });
    case 'ping':
      return reply(id, {});
    case 'tools/list':
      return reply(id, { tools: TOOLS.map(({ run, ...t }) => t) });
    case 'resources/list':
      return reply(id, { resources: RESOURCES.map(({ text, ...r }) => r) });
    case 'resources/read': {
      const r = RESOURCES.find(x => x.uri === params.uri);
      if (!r) return fail(id, -32002, `Resource not found: ${params.uri}`);
      const S = await file(env, 'summary.json');
      return reply(id, { contents: [{ uri: r.uri, mimeType: r.mimeType, text: r.text(S) }] });
    }
    case 'tools/call': {
      const tool = TOOLS.find(t => t.name === params.name);
      if (!tool) return fail(id, -32602, `Unknown tool: ${params.name}`);
      metric(tool.name);
      try {
        const S = await file(env, 'summary.json');
        const out = { week: memo.week, ...(await tool.run(env, S, params.arguments || {})),
          licence: S.licence, attribution: S.attribution, disclaimer: S.disclaimer };
        return reply(id, { content: [{ type: 'text', text: JSON.stringify(out) }], structuredContent: out });
      } catch (e) {
        if (!(e instanceof ToolError)) throw e;
        return reply(id, { content: [{ type: 'text', text: e.message }], isError: true });
      }
    }
    default:
      return fail(id, -32601, `Method not found: ${method}`);
  }
}

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...CORS } });

/** The /mcp endpoint. waitUntil keeps the metrics write alive after the response. */
export async function handle(request, env, waitUntil) {
  if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
  // A browser gets the page with the instructions (site/mcp.html): the same address for people and agents. The asset
  // server answers /mcp with mcp.html; /mcp.html would redirect back here.
  if (request.method === 'GET' && /text\/html/.test(request.headers.get('accept') || '') && env.ASSETS) {
    return env.ASSETS.fetch(new Request(new URL('/mcp', request.url), { headers: { accept: 'text/html' } }));
  }
  if (request.method !== 'POST') {
    return new Response('This is an MCP server (Streamable HTTP): send JSON-RPC with POST. See https://yellide.com/llms.txt',
      { status: 405, headers: { Allow: 'POST, OPTIONS', ...CORS } });
  }
  let body;
  try { body = await request.json(); } catch { return json(fail(null, -32700, 'Parse error'), 400); }
  const names = [];
  const metric = name => names.push(['mcp', name]);
  let out;
  try {
    out = Array.isArray(body)
      ? (await Promise.all(body.map(m => answer(m, env, metric)))).filter(Boolean)
      : await answer(body, env, metric);
  } catch (e) {
    return json(fail(body?.id, -32603, `Internal error: ${e.message}`), 500);
  }
  if (names.length && env.DB) waitUntil(record(env.DB, new Date().toISOString().slice(0, 10), names));
  if (out == null || (Array.isArray(out) && !out.length)) return new Response(null, { status: 202, headers: CORS });
  return json(out);
}
