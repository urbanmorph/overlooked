// The agent server at /mcp: the Model Context Protocol over Streamable HTTP (JSON responses, no server stream),
// stateless and read-only. It answers from the published master list in R2 (binding DATA), the same files the site
// and /data/ serve, so the server and the site give the same answer. llms.txt and the method page describe it.
//
// Questions across all of India (every endangered species, the species of a region) scan mcp/rows.bin, one
// fixed-width row per species written by pipeline/master.py mcp_files: a scan takes about a millisecond, where
// parsing the g files takes 40 ms. Files are read once per isolate and week.
import { record, isBot, mcpClient } from './metrics.js';
import { DISTRICT_NOTE, RESPECT_NOTE, WILD_NOTE } from './places.js';
import { KINGDOMS, kingdomOf, model, shardOf, nameMatches, plainName as plain, englishOf, speciesPath } from '../../site/assets/species_model.js';

export { shardOf };

const SITE = 'https://yellide.com';
const PROTOCOLS = ['2025-06-18', '2025-03-26', '2024-11-05'];
const LATEST_TTL = 300_000;             // ms between reads of layers/master/latest.json
const LIST_MAX = 100;
const FIND_MAX = 10;
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type, accept, mcp-protocol-version, mcp-session-id',
};

const INSTRUCTIONS = `yellide: every species documented from India, from ZSI, BSI, Kew WCVP, GBIF, iNaturalist, IUCN and other sources, updated each week. Use find_species to turn a Latin or English name into a key, then get_species for one species. Use count_species for "how many" and list_species for lists, by kingdom (animals, plants, fungi, other), group, state, district, WII biogeographic region (Western Ghats, Himalaya...), IUCN category, endemic, order, suborder (snakes, lizards) or family. Use new_species for species described from India since 2007. For a place, a point or "near me", use the bharatlas MCP server (https://bharatlas.com) first: its locate tool with layers [\"lgd_states\", \"lgd_districts\", \"biogeographic_zones\"] gives the state, the district (its LGD code) and the WII biogeographic province (prov_code, such as 5B) of a point (the province layer is not in locate's default layers); pass them as state, district and region. For an area made of districts (a delta, a valley, a landscape), find its districts and pass them as a list: each species counts once. A species is in a district when a GBIF record of it is placed there; it is counted apart (not_wild) only when the record keeper marks every record of it there as planted, kept or introduced, and a plant Kew does not give as native there carries kew_not_native: say "recorded in" the district, with the year of its latest record there, never "found here" or "lives here". For a state or a district, quote count_species' threatened and endemic: they count only species with a dated record there in the last 10 years and no not-native flag; give threatened_all_time and endemic_all_time only as the all-time figures, with that word. To list the species behind a headline count, pass counted: true to list_species. A plant Kew does not give as native there (kew_not_native) or a species GRIIS India lists as introduced (introduced_in_india) may be planted, farmed or invasive: say so. The resources give the valid groups, states, districts and regions. A name with a small spelling mistake is read as the nearest valid name, and the answer says how it was read: tell the user. Pass on the licence, attribution and disclaimer of each answer. yellide is a monitor of public data, not an authority: for the status of a species, people should consult BSI, ZSI, the IUCN Red List and the state forest department.`;

const ABOUT = `# yellide

Every species documented from India, across sources. Updated each week. ${SITE}

- Documented: a species that a checklist (ZSI, BSI, Kew WCVP, the lichen and bryophyte checklists), a paper (Plazi) or an open record lists for India. Names follow the Catalogue of Life.
- Open record: a record from India anyone can check online: any GBIF record (photo, sighting, specimen, sound, DNA, a record cited from a paper) or an iNaturalist research-grade observation.
- State: a species is in a state when it has an open record placed there that no record keeper marks as planted, kept or introduced.
- District: a species is in a district when a GBIF record of it is placed there (LGD districts) that no record keeper marks as planted, kept or introduced. For a district, list_species gives the first and latest year and the number of those records there.
- Places and record keepers: a place's list leaves out only the species whose every record there the record keeper marks as planted, kept or introduced (GBIF's establishment fields); count_species and list_species count them apart, as not_wild (cultivated_or_captive, introduced). yellide decides nothing else: few records carry a mark, so planted trees and crops can be on a list. A plant that Kew's World Checklist of Vascular Plants does not give as native in the place's region carries kew_not_native, and a species the Global Register of Introduced and Invasive Species for India (GRIIS India) lists carries introduced_in_india (list_species); count_species counts them in not_native.
- Counts for a place: count_species' threatened and endemic count only species with a dated record there in the last 10 years (since recent_from) and no not-native flag. threatened_all_time and endemic_all_time count every listed species, with old records and undated ones (often museum specimens labelled with a city). undated_only counts the species whose records there have no year. list_species keeps every species; each row says if the headline counts count it (counted, and not_counted: undated, before_<year>, not_native); pass counted: true for exactly that set, recorded_since for recent records only.
- Kingdom: animals, plants (with mosses and liverworts), fungi (with lichens, named for their fungus) and other (algae, diatoms and the rest). count_species gives by_kingdom; yellide://kingdoms lists the groups of each.
- Region: the biogeographic zones and provinces of India of the Wildlife Institute of India (Rodgers, Panwar and Mathur): 10 zones, 26 provinces. A species is in a region when a GBIF record of it is placed there. There is no Eastern Ghats unit: its nearest is 6C, Deccan Peninsula: Eastern Highlands.
- Waiting for a name: iNaturalist observations that nobody has confirmed yet (needs ID). They are not open records.
- IUCN: the category, year, DOI and trend of the latest IUCN Red List assessment (IUCN Red List, via GBIF). NE: not assessed. Threatened: CR, EN or VU.
- Endemic: a source marks the species as endemic to India.
- Recorded recently: the latest open record placed in a state is from the last 10 years.

Data and text: CC BY 4.0, Sathya Sankaran. Each source keeps its own licence. Method and sources: ${SITE}/method

yellide is a monitor of public data, not an authority. For the status of a species, consult BSI, ZSI, the IUCN Red List and the state forest department.`;

// ---------------------------------------------------------------- data

class ToolError extends Error {}
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

/** Every district (d/places.json): [{code, name, state (LGD code), groups (species per group)}], kept for the
 *  isolate and week; [] for a list from before the district files. */
async function districts(env, S) {
  const m = await current(env);
  return kept(m, '@districts', async () => {
    const f = await file(env, 'd/places.json');
    if (!f) return [];
    const F = model(S).dp;
    return f.rows.map(r => ({ code: r[F.code], name: r[F.name], state: r[F.state], groups: r[F.groups] }));
  });
}

/** The row of each key in the index, built once per isolate and week. */
function rowOf(ix) {
  if (!ix.rowOf) {
    ix.rowOf = new Map();
    for (let i = 0; i < ix.n; i++) ix.rowOf.set(ix.names(i).key, i);
  }
  return ix.rowOf;
}

const DISTRICTS_MAX = 50;
/** f of two years, either of which can be null. */
const either = (f, x, y) => (x == null ? y : y == null ? x : f(x, y));

/** One district a request names: its name or LGD code, with the state when two states have the name. */
function oneDistrict(S, all, value, state, a) {
  const stateName = code => S.states.find(s => s.code === code)?.name ?? code;
  const here = state != null ? all.filter(d => d.state === S.states[stateOf(S, state, a)].code) : all;
  let found = here.filter(d => String(d.code) === String(value).trim());
  if (!found.length) {
    found = nearest(value, here.map(d => d.name)).map(i => here[i]);
    const names = [...new Set(found.map(d => d.name))];
    if (names.length > 1) throw new ToolError(`"${value}" is as near to ${names.join(' as to ')}: which district?`);
    if (found.length) readAs(a, value, found[0].name);
  }
  if (!found.length) throw new ToolError(`Unknown district "${value}"${state != null ? ` in ${state}` : ''}. Give its name or LGD code, as in the resource yellide://districts.`);
  if (found.length > 1) {
    throw new ToolError(`There is a district "${value}" in ${found.map(d => stateName(d.state)).join(' and ')}: give the state too, or the LGD code (${found.map(d => d.code).join(', ')}).`);
  }
  return found[0];
}

/** The districts a request names (one, or a list for an area such as a delta) and their species, each once:
 *  {at: Map(index row -> {first_year, latest_year, records[, districts]})}, the years and records across the
 *  districts, and with several districts the ones it is recorded in. null when no district is asked for. */
async function inDistrict(env, S, ix, a) {
  if (a.district == null) return null;
  const list = Array.isArray(a.district) ? a.district : [a.district];
  if (!list.length || list.length > DISTRICTS_MAX) throw new ToolError(`Give 1 to ${DISTRICTS_MAX} districts.`);
  const asked = [...new Set(list)];
  const all = await districts(env, S);
  const ds = [...new Map(asked.map(v => oneDistrict(S, all, v, a.state, a)).map(d => [d.code, d])).values()];
  const F = model(S).d, rows = rowOf(ix), at = new Map(), several = ds.length > 1;
  const files = await Promise.all(ds.map(d => shard(env, `d/${d.code}.json`)));
  ds.forEach((d, n) => {
    for (const r of files[n]?.rows || []) {
      const i = rows.get(r[F.key]);
      if (i == null) continue;
      const s = at.get(i);
      if (!s) {
        at.set(i, { first_year: r[F.first_year], latest_year: r[F.last_year], records: r[F.records], ...(several ? { districts: [d.name] } : {}) });
        continue;
      }
      s.first_year = either(Math.min, s.first_year, r[F.first_year]);
      s.latest_year = either(Math.max, s.latest_year, r[F.last_year]);
      s.records += r[F.records];
      s.districts.push(d.name);
    }
  });
  for (const s of at.values()) s.districts?.sort((x, y) => x.localeCompare(y));
  // Species whose every record in these districts the record keeper marks (none listed in any of them), and the listed
  // plants Kew does not give as native in any district they are recorded in.
  const notWild = new Map(), flagged = new Map();
  files.forEach(f => {
    for (const [key, why] of f?.not_wild || []) {
      const i = rows.get(key);
      if (i != null && !at.has(i) && !notWild.has(i)) notWild.set(i, why);
    }
    for (const key of f?.kew_not_native || []) {
      const i = rows.get(key);
      if (i != null) flagged.set(i, (flagged.get(i) || 0) + 1);
    }
  });
  const kew = new Set([...flagged].filter(([i, n]) => at.has(i) && n === (at.get(i).districts?.length ?? 1)).map(([i]) => i));
  return { at, notWild, kew };
}

const NOT_WILD = ['cultivated_or_captive', 'introduced'];

/** What a place's answer adds (a district's from inDistrict, a state's from its own file): not_wild, the species it
 *  leaves out because the record keeper marks every record there, by reason, among those that pass every filter but
 *  the place; kew, the set of listed plants Kew does not give as native there; last(i), a listed species' latest year
 *  there (null: its records there have no year), and inState when the state's file gives those years; why(i), the
 *  reasons a listed species is not in the headline counts (undated, before_<recent_from>, not_native; none: counted).
 *  null with no place. */
async function placeOf(env, S, ix, a, dist) {
  let map = dist?.notWild, kew = dist?.kew, last = dist && (i => dist.at.get(i).latest_year), inState = false;
  if (!map && a.state != null) {
    map = new Map(); kew = new Set();
    const f = await shard(env, `d/state-${S.states[stateOf(S, a.state, a)].code}.json`), rows = rowOf(ix);
    for (const [key, why] of f?.not_wild || []) { const i = rows.get(key); if (i != null) map.set(i, why); }
    for (const key of f?.kew_not_native || []) { const i = rows.get(key); if (i != null) kew.add(i); }
    // The state's own latest years; a list built before 26 Nov 2026 has none: the latest year in India.
    const years = new Map();
    for (const [key, y] of f?.last || []) { const i = rows.get(key); if (i != null) years.set(i, y); }
    inState = years.size > 0;
    last = inState ? i => years.get(i) ?? null : i => ix.val('last_year', i);
  }
  if (!map) return null;
  const b = { ...a, district: null, state: null, recorded_since: null, counted: null };
  b[READ] = [];   // the notes are the request's, read once
  const ok = filter(S, ix, b), out = Object.fromEntries(NOT_WILD.map(k => [k, 0]));
  for (const [i, why] of map) if (ok(i) && why in out) out[why]++;
  // Why a listed species is not in the place's headline threatened and endemic counts (none: it is counted).
  const since = S.recent_from, intro = introduced(S, ix);
  const why = i => {
    const y = last(i), w = [];
    if (y == null) w.push('undated'); else if (y < since) w.push(`before_${since}`);
    if (kew.has(i) || intro(i)) w.push('not_native');
    return w;
  };
  return { not_wild: out, kew, last, inState, why };
}

// ---------------------------------------------------------------- filters

const oneOf = (what, value, valid) => {
  throw new ToolError(`Unknown ${what} "${value}". Valid values: ${valid.join(', ')}.`);
};

// Names with a spelling mistake: a name asked for is read as the nearest name the list has, within a few edits for
// its length (none under 5 letters), and the answer says how it was read.
const READ = Symbol('read');

/** Edits between two strings: a letter added, dropped or changed, or two neighbours swapped. */
export function editDistance(a, b) {
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...new Array(b.length).fill(0)]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
    }
  }
  return d[a.length][b.length];
}
const slack = n => (n < 5 ? 0 : n < 9 ? 1 : n < 15 ? 2 : 3);

/** The indexes of the names nearest to value: the ones equal as people type them, else the nearest within slack. */
function nearest(value, names) {
  const q = plain(value), exact = names.flatMap((n, i) => (plain(n) === q ? [i] : []));
  if (exact.length) return exact;
  const edits = names.map(n => editDistance(q, plain(n))), best = Math.min(...edits);
  return best <= slack(q.length) ? names.flatMap((_, i) => (edits[i] === best ? [i] : [])) : [];
}

/** Note that value was read as name (the answer's note says so). */
const readAs = (a, value, name) => { if (a && plain(value) !== plain(name)) (a[READ] ||= []).push(`"${value}" read as ${name}.`); };

/** One name of a list for value, or a tool error naming the valid ones (or the nearest, when two are as near). */
function one(what, value, names, valid, a) {
  const at = nearest(value, names), distinct = [...new Set(at.map(i => names[i]))];
  if (distinct.length > 1) throw new ToolError(`"${value}" is as near to ${distinct.join(' as to ')}: which ${what}?`);
  if (!at.length) oneOf(what, value, valid);
  readAs(a, value, names[at[0]]);
  return at[0];
}

/** The group indexes of a kingdom (animals, plants, fungi, other; a near spelling is read as the nearest). */
function kingdomGroups(S, value, a) {
  const k = KINGDOMS[one('kingdom', value, KINGDOMS, KINGDOMS, a)];
  return S.groups.flatMap((g, i) => (kingdomOf(g) === k ? [i] : []));
}

// Group words that mean a kingdom. "Fungi" is a group of its own (its exact name wins); kingdom "fungi" adds lichens.
const KINGDOM_WORDS = { animal: 'animals', animals: 'animals', plant: 'plants', plants: 'plants' };

function groupsOf(S, value, a) {
  const q = plain(value);
  const exact = S.groups.findIndex(g => plain(g) === q);
  if (exact >= 0) return [exact];
  if (KINGDOM_WORDS[q]) return kingdomGroups(S, KINGDOM_WORDS[q], a);
  const some = S.groups.flatMap((g, i) => (plain(g).includes(q) ? [i] : []));
  return some.length ? some : [one('group', value, S.groups, S.groups, a)];
}

// States by an earlier name, as older papers and records give them.
const STATE_NAMES_BEFORE = { orissa: 'Odisha', pondicherry: 'Puducherry', uttaranchal: 'Uttarakhand' };

function stateOf(S, value, a) {
  const i = S.states.findIndex(s => s.code === String(value));
  if (i >= 0) return i;
  const now = STATE_NAMES_BEFORE[plain(value)];
  if (now && S.states.some(s => s.name === now)) { readAs(a, value, now); return S.states.findIndex(s => s.name === now); }
  const names = S.states.map(s => s.name);
  return one('state', value, names, names, a);
}

/** A province code (5B), a province (Western Ghats: Mountains) or a zone (Western Ghats): the province bits. */
function regionBits(S, value, a) {
  const q = plain(value);
  let bits = S.provinces.flatMap(([code, prov, zone], i) =>
    (plain(code) === q || plain(prov) === q || plain(zone) === q ? [i] : []));
  if (bits.length) return bits;
  // Eastern Ghats is one letter from Western Ghats, but it is a real place WII has no unit for: say so.
  const eastern = /eastern ghats/.test(q);
  const names = [...new Set(S.provinces.flatMap(([, prov, zone]) => [prov, zone]))], at = eastern ? [] : nearest(value, names);
  if (at.length === 1) {
    readAs(a, value, names[at[0]]);
    bits = S.provinces.flatMap(([, prov, zone], i) => (prov === names[at[0]] || zone === names[at[0]] ? [i] : []));
    return bits;
  }
  const hint = eastern ? ' There is no Eastern Ghats unit in the WII classification: its nearest is 6C, Deccan Peninsula: Eastern Highlands.' : '';
  throw new ToolError(`Unknown region "${value}".${hint} Valid zones: ${[...new Set(S.provinces.map(p => p[2]))].join(', ')}; or a province code (${S.provinces.map(p => p[0]).join(', ')}). See the resource yellide://regions.`);
}

function iucnSet(S, values) {
  const out = [];
  for (const v of [].concat(values)) {
    const c = String(v).toUpperCase();
    if (c === 'THREATENED') S.threatened.forEach(t => out.push(S.iucn.indexOf(t)));
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

/** The filter arguments of count_species and list_species, as one test of an index row. dist: inDistrict; place:
 *  placeOf (a place's own latest years for recorded_since). */
function filter(S, ix, a, dist = null, place = null) {
  const tests = [], { col, nul } = ix;
  if (dist) tests.push(i => dist.at.has(i));
  if (a.group != null) { const t = table(256, groupsOf(S, a.group, a)), g = col.group; tests.push(i => t[g[i]] === 1); }
  if (a.kingdom != null) { const t = table(256, kingdomGroups(S, a.kingdom, a)), g = col.group; tests.push(i => t[g[i]] === 1); }
  // With a district, the state only tells which district of that name.
  if (a.state != null && !dist) {
    const b = stateOf(S, a.state, a), m = b < 32 ? col.states_lo : col.states_hi, k = b % 32;
    tests.push(i => ((m[i] >>> k) & 1) === 1);
  }
  if (a.region != null) {
    let mask = 0;
    for (const b of regionBits(S, a.region, a)) mask |= 1 << b;
    const p = col.provinces, none = nul.provinces;
    tests.push(i => p[i] !== none && (p[i] & mask) !== 0);
  }
  if (a.iucn != null) { const t = table(256, iucnSet(S, a.iucn)), c = col.iucn; tests.push(i => t[c[i]] === 1); }
  if (a.endemic != null) {
    const b = model(S).endBit, want = a.endemic ? 1 : 0, l = col.labels;
    tests.push(i => ((l[i] >>> b) & 1) === want);
  }
  if (a.order != null) {
    const o = one('order', a.order, S.orders, ['an order name such as Squamata, Anura, Lepidoptera or Orchidales (Latin)'], a), c = col.order;
    tests.push(i => c[i] === o);
  }
  if (a.suborder != null) {
    const name = SUBORDER_WORDS[plain(a.suborder)] || a.suborder;
    const s = S.suborders.findIndex(x => plain(x) === plain(name)), c = col.suborder;
    if (s < 0) oneOf('suborder', a.suborder, ['Serpentes (snakes)', 'Sauria (lizards)']);
    tests.push(i => c[i] === s);
  }
  if (a.family != null) {
    const f = one('family', a.family, ix.families, ['a family name in Latin, such as Elapidae or Orchidaceae'], a), c = col.family;
    tests.push(i => c[i] === f);
  }
  if (a.open_record != null) { const want = a.open_record ? 1 : 0, c = col.status; tests.push(i => (c[i] === 1 ? 1 : 0) === want); }
  // 0 means null for the years, so "since" leaves out species with no year.
  // In a district, the latest record there.
  if (a.recorded_since != null) {
    const y = year('recorded_since', a.recorded_since), c = col.last_year;
    const last = place?.last ?? (dist && (i => dist.at.get(i).latest_year));
    tests.push(last ? i => last(i) >= y : i => c[i] >= y);
  }
  if (a.counted != null) {
    if (!place) throw new ToolError('counted needs a state or a district.');
    const want = !!a.counted;
    tests.push(i => (place.why(i).length === 0) === want);
  }
  if (a.described_since != null) { const y = year('described_since', a.described_since), c = col.described; tests.push(i => c[i] >= y); }
  const k = tests.length;
  return i => { for (let t = 0; t < k; t++) if (!tests[t](i)) return false; return true; };
}

/** Groups where no source marks any species as endemic (computed once per index). */
function unmarked(S, ix) {
  if (!ix.unmarked) {
    const end = model(S).endBit, marked = new Set();
    const { labels, group } = ix.col;
    for (let i = 0; i < ix.n; i++) if ((labels[i] >>> end) & 1) marked.add(group[i]);
    ix.unmarked = S.groups.filter((_, g) => !marked.has(g));
  }
  return ix.unmarked;
}

function filterNote(S, ix, a) {
  const notes = [...(a[READ] || [])];
  if (a.district != null) notes.push(DISTRICT_NOTE, RESPECT_NOTE);
  if (a.district != null || a.state != null) notes.push(WILD_NOTE);
  if (a.endemic != null) {
    notes.push('Endemic marks come from the sources that give them (Kew WCVP for plants, ZSI and other checklists for some animal groups), each for the species under its own name (not a synonym\'s or a subspecies\' mark). '
      + `These groups have no endemic mark yet: ${unmarked(S, ix).join('; ')}. There, 0 endemic means not marked, not that none is endemic.`);
  }
  if (a.state != null && a.district == null) notes.push('A species is in a state when it has an open record placed there that no record keeper marks as planted, kept or introduced.');
  if (a.state != null && a.region != null && a.district == null) {
    notes.push('With a state and a region: species with records in the state and records in the region, not always in the part where they meet.');
  }
  if (a.region != null) notes.push('A species is in a region when a GBIF record of it is placed there (WII biogeographic provinces).');
  if (a.recorded_since != null) {
    notes.push(a.district != null ? 'Recorded since: the latest GBIF record placed in the district.'
      : a.state != null ? 'Recorded since: the latest open record placed in the state.' : 'Recorded since: the latest open record placed in any state of India.');
  }
  return notes.join(' ') || undefined;
}

// ---------------------------------------------------------------- tools

const FILTERS = {
  group: { type: 'string', description: 'A group of the list, or a word of it: "Birds", "butterflies", "mammals" (all mammal groups), "orchids"; "animals" and "plants" mean the kingdom. See yellide://groups.' },
  kingdom: { type: 'string', enum: KINGDOMS, description: 'animals, plants (with mosses and liverworts), fungi (with lichens) or other (algae, diatoms and the rest). See yellide://groups.' },
  state: { type: 'string', description: 'A state or union territory of India: "Karnataka". See yellide://states.' },
  district: { anyOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' }, maxItems: 50 }], description: 'A district (LGD): its name, "Wayanad", or its LGD code; or a list of districts for an area that is made of districts (the Mahanadi delta: ["Cuttack", "Jagatsinghapur", "Kendrapara", "Puri"]), where each species counts once. Give the state too when two states have the name. See yellide://districts.' },
  region: { type: 'string', description: 'A WII biogeographic zone ("Western Ghats", "Himalaya", "North-East", "Islands"), a province ("Western Ghats: Mountains") or a province code ("5B"). See yellide://regions.' },
  iucn: { type: 'array', items: { type: 'string' }, description: 'IUCN Red List categories: CR, EN, VU, NT, LC, DD, NE (not assessed), or "threatened" (CR, EN, VU).' },
  endemic: { type: 'boolean', description: 'true: only species a source marks as endemic to India; false: only species not marked. Some groups have no marks yet (the answer names them).' },
  order: { type: 'string', description: 'An order (Latin): "Squamata", "Anura" (frogs), "Lepidoptera".' },
  suborder: { type: 'string', description: 'For order Squamata: "snakes" (Serpentes) or "lizards" (Sauria).' },
  family: { type: 'string', description: 'A family (Latin): "Elapidae", "Orchidaceae".' },
  open_record: { type: 'boolean', description: 'true: species with an open record from India; false: species known only from checklists and papers.' },
  recorded_since: { type: 'integer', description: 'Species with an open record placed in India in this year or later; with a state, placed in the state; with a district, a GBIF record placed in the district.' },
  described_since: { type: 'integer', description: 'Species described in this year or later.' },
  counted: { type: 'boolean', description: 'With a state or a district: true gives only the species that count_species\' headline threatened and endemic counts count there (a dated record there in the last 10 years and no not-native flag); with iucn: ["threatened"] it lists exactly the headline threatened species. false: the others.' },
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
    description: 'How many species of India: documented, with an open record, threatened (IUCN CR, EN, VU), recorded in the last 10 years, endemic, per IUCN category and per kingdom (by_kingdom: animals, plants, fungi, other). For a state or district, threatened and endemic count only species with a dated record there in the last 10 years and no not-native flag (quote these); threatened_all_time and endemic_all_time count all, undated_only the species with no dated record there, not_native the species Kew does not give as native there or GRIIS India lists as introduced, and not_wild those the record keepers mark as planted, kept or introduced. All filters are optional and combine: "how many butterflies in India", "threatened birds in Kerala", "endemic frogs of the Western Ghats", "plants of Shivamogga" (kingdom: plants).',
    inputSchema: { type: 'object', properties: FILTERS },
    run: countSpecies,
  },
  {
    name: 'list_species', title: 'List species',
    description: 'List species of India with optional filters that combine: "critically endangered species in India", "endangered animals in Karnataka" (kingdom: animals), "snakes of the Western Ghats", "birds of Goa recorded since 2020". For a state or a district the list keeps every species with a record there, old and undated ones too (in_district or in_state gives the latest year there; counted says if count_species\' headline threatened and endemic counts count it, not_counted why not; pass counted: true for exactly that set, recorded_since for recent records); kew_not_native: true marks a plant Kew does not give as native there, introduced_in_india: true a species GRIIS India lists; not_wild counts the species the record keepers mark as planted, kept or introduced. Rows by group, then Latin name; up to 100 per page, with the total and a cursor for the next page.',
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
  const M = model(S), F = M.search, rows = f?.rows || [];
  // As written; else, for a name with a spelling mistake, the names whose start is nearest to it.
  let hits = rows.filter(r => nameMatches(r[F.name], q, r.length > F.latin)), readAsNote;
  if (!hits.length && slack(q.length)) {
    const near = rows.map(r => editDistance(q, plain(r[F.name]).slice(0, q.length)));
    const best = Math.min(...near);
    if (best <= slack(q.length)) {
      hits = rows.filter((_, i) => near[i] === best);
      readAsNote = `No name starts with "${a.name}": these are the nearest names.`;
    }
  }
  for (const r of hits) {
    const common = r.length > F.latin, latin = common ? r[F.latin] : r[F.name];
    const id = r[F.key] || 'n:' + latin;
    const s = by.get(id) || { key: r[F.key] || null, name: latin, english: null, group: S.groups[r[F.group]],
      iucn: S.iucn[r[F.iucn]], status: M.status(r[F.status]), described: r[F.year], url: url(r[F.key], latin), exact: false };
    if (common && !s.english) s.english = r[F.name];
    s.exact ||= plain(r[F.name]) === q;
    by.set(id, s);
  }
  const species = [...by.values()].sort((x, y) => y.exact - x.exact).slice(0, FIND_MAX).map(({ exact, ...s }) => s);
  // A Latin name's English name is in the search file of its own first letters: take it from en/ by key.
  const missing = species.filter(s => s.key && !s.english);
  const en = await englishOf(path => shard(env, path), '', S, missing.map(s => s.key));
  for (const s of missing) s.english = en.get(s.key) || null;
  return { species, ...(readAsNote ? { read_as: readAsNote } : {}) };
}

async function getSpecies(env, S, a) {
  const key = String(a.key || '');
  const sh = shardOf(key);
  const [sp, pics] = await Promise.all([shard(env, `sp/${sh}.json`), shard(env, `pic/${sh}.json`)]);
  const r = sp?.[key];
  if (!r) throw new ToolError(`No species with key "${key}". Use find_species to get a key.`);
  const M = model(S);
  const { name, group: gi, sources, status, iucn, labels, states, taxon, waiting_india: nIndia, year, authority, paper,
    iucn_year: iucnYear, iucn_doi: iucnDoi, partners, interactions_india: interIndia, types, photos, barcode, local_names: local,
    iucn_trend: iucnTrend, family, order, suborder, provinces } = M.read('sp', r);
  const pic = pics?.[key] ? M.read('pic', pics[key]) : null;
  const place = S.waiting?.places?.india;
  const prov = new Map(S.provinces.map(p => [p[0], p[1]]));
  return {
    key, name, english: pic?.english || null, group: S.groups[gi], family: family || null, order: order || null, suborder: suborder || null,
    status: M.status(status), open_record: status === 1,
    iucn: { category: S.iucn[iucn], year: iucnYear ?? null, doi: iucnDoi ?? null, trend: iucnTrend ?? null },
    endemic: M.endemic(labels),
    sources: S.sources.filter((_, i) => Math.floor(sources / 2 ** i) % 2 === 1),
    states_with_open_record: S.states.filter((_, i) => Math.floor(states / 2 ** i) % 2 === 1).map(s => s.name),
    regions: provinces ? provinces.map(c => `${c} ${prov.get(c) ?? ''}`.trim()) : null,
    described: { year: year ?? null, authority: authority ?? null },
    paper: paper ? { journal: paper[1] || null, link: paper[2] || null, records_after: paper[3] ?? null } : null,
    evidence: { type_specimen_records_from_india: types ?? null, photo_records_from_india: photos ?? null,
      dna_barcode: ['none', 'yes, not from India', 'yes, from India'][barcode] ?? null },
    interactions: partners == null ? null : { partner_species: partners, recorded_in_india: Boolean(interIndia) },
    names_in_indian_languages: local || null,
    photo: pic ? { url: pic.url, page: pic.page, credit: [pic.by, pic.licence, pic.source].filter(Boolean).join(', ') } : null,
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

/** Every species on the list that passes the filters `a` (as list_species takes them: group, state, region...), for
 *  the place pages (lib/place_page.js): [{key, name, english, gi, iucn, endemic, open}], with the summary, the week
 *  and the groups that have no endemic mark. */
export async function speciesWhere(env, a) {
  const S = await file(env, 'summary.json'), ix = await index(env), dist = await inDistrict(env, S, ix, a);
  const ok = filter(S, ix, a, dist), { col } = ix, end = model(S).endBit;
  const rows = [];
  for (let i = 0; i < ix.n; i++) {
    if (!ok(i)) continue;
    const { key, name, english } = ix.names(i);
    rows.push({ key, name, english, gi: col.group[i], iucn: S.iucn[col.iucn[i]], endemic: ((col.labels[i] >>> end) & 1) === 1,
      open: col.status[i] === 1, ...(dist ? { latest: dist.at.get(i).latest_year } : {}) });
  }
  return { S, rows, week: memo.week, unmarked: unmarked(S, ix) };
}

/** Species per group for India, each state (open record placed there) and each WII zone (GBIF record placed there),
 *  in one pass, for the place hubs and the sitemap: {S, india: [n per group], states: {code: [...]}, zones: {zone: [...]}}. */
export async function placeCounts(env) {
  const S = await file(env, 'summary.json'), ix = await index(env);
  return { ...(await kept(await current(env), '@places', async () => countPlaces(S, ix))), districts: await districts(env, S), S, week: memo.week };
}

function countPlaces(S, ix) {
  const { col, nul } = ix, G = S.groups.length;
  const zero = () => new Array(G).fill(0);
  const india = zero(), states = Object.fromEntries(S.states.map(s => [s.code, zero()]));
  const zoneOfBit = S.provinces.map(p => p[2]), zones = Object.fromEntries([...new Set(zoneOfBit)].map(z => [z, zero()]));
  for (let i = 0; i < ix.n; i++) {
    const g = col.group[i];
    india[g]++;
    for (let b = 0; b < S.states.length; b++) {
      const m = b < 32 ? col.states_lo[i] : col.states_hi[i];
      if (((m >>> (b % 32)) & 1) === 1) states[S.states[b].code][g]++;
    }
    const p = col.provinces[i];
    if (p === nul.provinces || !p) continue;
    const seen = new Set();
    for (let b = 0; b < zoneOfBit.length; b++) if ((p >>> b) & 1) seen.add(zoneOfBit[b]);
    for (const z of seen) zones[z][g]++;
  }
  return { india, states, zones };
}

/** GRIIS India lists the species as introduced in India (label int): a test of an index row. */
const introduced = (S, ix) => {
  const b = model(S).intBit, l = ix.col.labels;
  return b < 0 ? () => false : i => ((l[i] >>> b) & 1) === 1;
};

/** A place's row: whether count_species' headline threatened and endemic counts count it, and why not. */
const counted = why => (why.length ? { counted: false, not_counted: why } : { counted: true });

/** A place's list keeps every species (list_species): what to read in it. */
const LIST_NOTE = 'This list has every species with a record in the place, old and undated ones too: read latest_year in in_district or '
  + 'in_state (null: no year). Pass recorded_since (for example 2016) for recent records only. kew_not_native and introduced_in_india mark '
  + 'species that may be planted or introduced there: say so. counted: true marks the species that count_species\' headline threatened '
  + 'and endemic counts count (a dated record there in the last 10 years and no not-native flag); not_counted gives why not (undated, '
  + 'before_<year>, not_native). Pass counted: true for exactly that set: with iucn ["threatened"] its total is the headline threatened count.';

/** What a model should quote for a place (count_species). */
const countNote = since => `For a state or a district, threatened and endemic count only the species with a dated record there since ${since} `
  + 'and no flag as not native there (kew_not_native, introduced_in_india): quote these. threatened_all_time and endemic_all_time count every listed '
  + 'species, with old and undated records (often a museum specimen labelled with a city). undated_only counts the species whose records there have '
  + 'no year; not_native counts the flagged species.';

async function countSpecies(env, S, a) {
  const ix = await index(env), dist = await inDistrict(env, S, ix, a), place = await placeOf(env, S, ix, a, dist);
  const ok = filter(S, ix, a, dist, place), { status, iucn, labels } = ix.col;
  const last = place ? place.last : i => ix.val('last_year', i);
  const thr = table(256, S.threatened.map(c => S.iucn.indexOf(c))), end = model(S).endBit;
  const since = S.recent_from, byIucn = new Array(S.iucn.length).fill(0);
  const intro = introduced(S, ix), kew = place?.kew;
  // Per kingdom: [documented, open, threatened, recent, endemic, threatened all time, endemic all time]. In a place the
  // headline threatened and endemic are species with a dated record there since recent_from and no not-native flag.
  const kOf = S.groups.map(g => KINGDOMS.indexOf(kingdomOf(g))), per = KINGDOMS.map(() => [0, 0, 0, 0, 0, 0, 0]);
  const apart = { undated: 0, nn: 0, nnThr: 0, nnEnd: 0, kew: 0, intro: 0 };
  for (let i = 0; i < ix.n; i++) {
    if (!ok(i)) continue;
    const c = per[kOf[ix.col.group[i]]], y = last(i), t = thr[iucn[i]], e = (labels[i] >>> end) & 1;
    const recent = y != null && y >= since, k = !!kew?.has(i), n = place ? intro(i) : false, nn = k || n;
    const head = !place || place.why(i).length === 0;
    c[0]++;
    if (status[i] === 1) c[1]++;
    byIucn[iucn[i]]++;
    if (head) { c[2] += t; c[4] += e; }
    if (recent) c[3]++;
    c[5] += t; c[6] += e;
    if (!place) continue;
    if (y == null) apart.undated++;
    if (nn) { apart.nn++; apart.nnThr += t; apart.nnEnd += e; }
    apart.kew += k; apart.intro += n;
  }
  const named = ([documented, open, threatened, recent, endemic, thrAll, endAll]) => (place
    ? { documented, open_record: open, threatened, threatened_all_time: thrAll, [`recorded_since_${since}`]: recent, endemic, endemic_all_time: endAll }
    : { documented, open_record: open, threatened, [`recorded_since_${since}`]: recent, endemic });
  return {
    counts: named(per.reduce((t, c) => t.map((v, j) => v + c[j]), [0, 0, 0, 0, 0, 0, 0])),
    by_kingdom: Object.fromEntries(KINGDOMS.map((k, j) => [k, named(per[j])])),
    ...(place ? {
      undated_only: apart.undated,
      not_native: { species: apart.nn, threatened: apart.nnThr, endemic: apart.nnEnd, kew_not_native: apart.kew, introduced_in_india: apart.intro },
      not_wild: place.not_wild,
    } : {}),
    by_iucn: Object.fromEntries(S.iucn.flatMap((k, i) => (byIucn[i] ? [[k, byIucn[i]]] : []))),
    note: [filterNote(S, ix, a), place ? countNote(since) : null].filter(Boolean).join(' ') || undefined,
  };
}

async function listSpecies(env, S, a) {
  const ix = await index(env), dist = await inDistrict(env, S, ix, a), place = await placeOf(env, S, ix, a, dist);
  const ok = filter(S, ix, a, dist, place), { col, val } = ix, { limit, from } = pageOf(a);
  const end = model(S).endBit, intro = introduced(S, ix);
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
      latest_record_year: val('last_year', i), described: val('described', i), url: url(key, name),
      ...(dist ? { in_district: dist.at.get(i) } : {}), ...(place?.inState ? { in_state: { latest_year: place.last(i) } } : {}),
      ...(place?.kew.has(i) ? { kew_not_native: true } : {}), ...(intro(i) ? { introduced_in_india: true } : {}),
      ...(place ? counted(place.why(i)) : {}) });
  }
  const listNote = place ? LIST_NOTE : null;
  return { total, species, next_cursor: next, ...(place ? { not_wild: place.not_wild } : {}),
    note: [filterNote(S, ix, a), listNote].filter(Boolean).join(' ') || undefined };
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
  { uri: 'yellide://groups', name: 'groups', title: 'Groups of the list (their kingdoms: yellide://kingdoms)', mimeType: 'application/json', text: S => JSON.stringify(S.groups) },
  {
    uri: 'yellide://kingdoms', name: 'kingdoms', title: 'Kingdoms and their groups (plants include mosses; fungi include lichens)', mimeType: 'application/json',
    text: S => JSON.stringify(Object.fromEntries(KINGDOMS.map(k => [k, S.groups.filter(g => kingdomOf(g) === k)]))),
  },
  { uri: 'yellide://states', name: 'states', title: 'States and union territories', mimeType: 'application/json', text: S => JSON.stringify(S.states.map(s => s.name)) },
  {
    uri: 'yellide://districts', name: 'districts', title: 'Districts of each state (LGD)', mimeType: 'application/json',
    text: (S, D) => {
      const by = {}, state = new Map(S.states.map(s => [s.code, s.name]));
      for (const d of D) (by[state.get(d.state) ?? d.state] ||= []).push(d.name);
      return JSON.stringify(Object.fromEntries(Object.entries(by).sort(([a], [b]) => a.localeCompare(b))
        .map(([s, ds]) => [s, ds.sort((a, b) => a.localeCompare(b))])));
    },
  },
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
      metric.client(params.clientInfo?.name);
      return reply(id, {
        protocolVersion: PROTOCOLS.includes(params.protocolVersion) ? params.protocolVersion : PROTOCOLS[0],
        capabilities: { tools: {}, resources: {} },
        serverInfo: { name: 'yellide', title: 'yellide: species of India', version: '1.5.0', websiteUrl: SITE },
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
      return reply(id, { contents: [{ uri: r.uri, mimeType: r.mimeType, text: r.text(S, r.uri === 'yellide://districts' ? await districts(env, S) : null) }] });
    }
    case 'tools/call': {
      const tool = TOOLS.find(t => t.name === params.name);
      if (!tool) return fail(id, -32602, `Unknown tool: ${params.name}`);
      metric.tool(tool.name);
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
  // Counted per request, written once: each tool by name, and (bots aside) the mode and the client product. Never
  // the arguments, and never the client's name as it sent it (see metrics.js mcpClient). A monitor (an uptime check,
  // a registry probe) is counted as one, and its calls are not use (mode).
  const bot = isBot(request.headers.get('user-agent'));
  let names = [], monitor = false;
  const metric = {
    tool: name => { names.push(['mcp', name]); if (!bot) names.push(['mode', 'mcp']); },
    client: name => {
      const product = mcpClient(name);
      monitor ||= product === 'monitor';
      if (!bot) names.push(['mcp_client', product]);
    },
  };
  let out;
  try {
    out = Array.isArray(body)
      ? (await Promise.all(body.map(m => answer(m, env, metric)))).filter(Boolean)
      : await answer(body, env, metric);
  } catch (e) {
    return json(fail(body?.id, -32603, `Internal error: ${e.message}`), 500);
  }
  if (monitor) names = names.filter(([dim]) => dim !== 'mode');
  if (names.length && env.DB) waitUntil(record(env.DB, new Date().toISOString().slice(0, 10), names));
  if (out == null || (Array.isArray(out) && !out.length)) return new Response(null, { status: 202, headers: CORS });
  return json(out);
}
