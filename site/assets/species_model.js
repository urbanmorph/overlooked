// One way to read and show a species, for every page of the site (in the browser) and for the server functions (the
// species and place pages, the agent server at /mcp). Pure: no page and no request of its own.
//
// The facts come from the list itself (pipeline/master.py site_files writes them into summary.json): the name of each
// field of the g, w, search and sp rows, the words for status and the IUCN categories, the threatened codes, the
// endemic label. Nothing here keeps its own copy, so a change in the pipeline reaches every page.

// The address of a species page: /species/<key>/<slug of its Latin name>. The key finds the species; the slug puts its
// name in the address for people and search engines, and a wrong one is corrected (functions/species/[[path]].js).
// pipeline/master.py slug() makes the same slug for the sitemaps (tests/fixtures/species_slugs.json holds both to it).
// This module imports nothing, so the server functions can import it as it is.
/** The Latin name in lower case, accents dropped, every run of other characters one hyphen. */
export const slug = name => String(name ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
  .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

/** The path of a species page; with no name, just the key (the page then corrects the address). */
export const speciesPath = (key, name) => {
  const s = slug(name);
  return `/species/${encodeURIComponent(key)}${s ? `/${s}` : ''}`;
};

export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** A species as the site shows it: the Latin name in italics, linked to its page when it has one (key), and the
 *  English name on a line under it. english: the name; null: it has none; not given: a slot that fillEnglish fills.
 *  after: HTML on the line of the Latin name (an IUCN badge). */
export const speciesName = (key, name, english, after = '') =>
  (key ? `<a href="${speciesPath(key, name)}"><i>${esc(name)}</i></a>` : `<i>${esc(name)}</i>`) + (after ? ` ${after}` : '')
  + (english ? enLine(english) : english === undefined && key ? `<span class="en" data-en="${esc(key)}"></span>` : '');

/** The same without a link, for a place that is itself a link (a row of partners): the Latin name, the English under it. */
export const speciesText = (name, english) => `<i>${esc(name)}</i>${english ? enLine(english) : ''}`;
const enLine = english => `<span class="en">${esc(english)}</span>`;

/** A species in plain text (titles, share text, answers): "English (Latin)", else the Latin name. */
export const speciesTitle = (name, english) => (english ? `${english} (${name})` : name);

/** A species inside a sentence: "English (<i>Latin</i>)", else the Latin name in italics. */
export const speciesInline = (name, english) => (english ? `${esc(english)} (<i>${esc(name)}</i>)` : `<i>${esc(name)}</i>`);

/** The IUCN Red List category as a badge (style.css .iucn .i-<cat>). */
export const iucnBadge = cat => `<span class="iucn i-${esc(cat)}" title="IUCN Red List">${esc(cat === 'NE' ? 'Not assessed' : cat)}</span>`;

/** A name as people type it: lower case, hyphens and runs of spaces as one space, no apostrophes. */
export const plainName = s => String(s ?? '').toLowerCase().replace(/['\u2019]/g, '').replace(/[-\s]+/g, ' ').trim();

/** Whether a name in the search files answers the words typed: a Latin name from its start; an English name (english
 *  true) from the start of any of its words. */
export function nameMatches(name, q, english = false) {
  const n = plainName(name), words = plainName(q);
  return n.startsWith(words) || (english && n.includes(' ' + words));
}

const orList = xs => (xs.length < 3 ? xs.join(' or ') : `${xs.slice(0, -1).join(', ')} or ${xs.at(-1)}`);

// Masks of sources, labels and states can pass 32 bits, so no bitwise operators.
const bit = (mask, i) => Math.floor(mask / 2 ** i) % 2 === 1;

/** {field: position} for a list of field names; asking for a field that is not there is an error, not undefined. */
function positions(names) {
  const at = Object.fromEntries(names.map((f, i) => [f, i]));
  return new Proxy(at, { get: (o, f) => { if (typeof f === 'string' && !(f in o)) throw new Error(`no field "${String(f)}" in this row`); return o[f]; } });
}

/** The reader of one list (its summary.json S): field positions of each row (m.g.status: the position of the status in
 *  a g row), m.read(kind, row) for a row as an object, and the list's words and rules. */
export function model(S) {
  if (!S?.fields) throw new Error('this list does not name its row fields (summary.json fields)');
  const m = Object.fromEntries(Object.entries(S.fields).map(([kind, names]) => [kind, positions(names)]));
  const threatened = new Set(S.threatened), endBit = (S.labels || []).findIndex(l => l.code === 'end');
  const threatenedIdx = (S.iucn || []).map(c => threatened.has(c));
  return {
    ...m,
    read: (kind, row) => Object.fromEntries(S.fields[kind].map((f, i) => [f, row[i]])),
    status: i => S.status[i],
    iucnName: code => S.iucn_names?.[code] ?? code,
    threatenedWords: orList((S.threatened || []).map(c => S.iucn_names?.[c] ?? c)),   // "Critically Endangered, Endangered or Vulnerable"
    threatened: code => threatened.has(code),
    threatenedAt: i => threatenedIdx[i] === true,
    endBit,
    endemic: labels => endBit >= 0 && bit(labels, endBit),
  };
}

/** FNV-1a 32-bit of the UTF-8 key: pipeline/site_data.py shard_of before its modulo. */
export function hashOf(key) {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(String(key))) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
  return h;
}

/** The shard of a key in the 512-shard files (sp, pic, web, fam, the snapshot's species): site_data.shard_of. */
export const shardOf = key => hashOf(key) % 512;

/** The English names of some species (Map key -> name), from the list's en/<shard>.json files (base: the list's
 *  folder; get: reads a JSON file). One request per shard; a shard that does not load gives no names. */
export async function englishOf(get, base, S, keys) {
  const n = S.en_shards || 64, by = new Map();
  for (const k of new Set(keys)) if (k) by.set(hashOf(k) % n, [...(by.get(hashOf(k) % n) || []), k]);
  const names = new Map();
  await Promise.all([...by].map(async ([shard, ks]) => {
    const part = await get(`${base}en/${shard}.json`).catch(() => null);
    for (const k of ks) if (part?.[k]) names.set(k, part[k]);
  }));
  return names;
}

/** Fill each English-name slot that speciesName left in root (a page part); a slot with no name goes. */
export async function fillEnglish(root, get, base, S) {
  const slots = [...root.querySelectorAll('[data-en]')];
  if (!slots.length) return;
  const names = await englishOf(get, base, S, slots.map(s => s.dataset.en));
  for (const s of slots) {
    const n = names.get(s.dataset.en);
    if (n) s.textContent = n;
    else s.remove();
  }
}
