// The species page's pure parts: the seven gaps for one species, as a pyramid with the group's share in each block and
// as a small glyph; the partners (GloBI) as a tree, a branch per kind of link; the relatives in its family; the map
// fill. species.js draws and wires them. A radial layout was tried first: with 30 partners per kind the names collided.

import { esc, fmt } from './common.js?v=9455fd8cc8';

// Kinds of link from the species' own side (pipeline/master.py web_files). Hues in this order validated for CVD and normal vision on
// white; two are under 3:1, so every sector has a text label and the page has a table view.
export const KINDS = [
  { k: 'eats', label: 'Eats', color: '#1baf7a' },
  { k: 'eaten', label: 'Eaten by', color: '#eb6834' },
  { k: 'flowers', label: 'Pollination', color: '#6250d6' },
  { k: 'lives', label: 'Lives on or in', color: '#e87ba4' },
  { k: 'hosts', label: 'Lives on it', color: '#2a78d6' },
  { k: 'other', label: 'Other links', color: '#8A9690' },
];
export const VERBS = { eats: 'eats', preysOn: 'preys on', kills: 'kills', pollinates: 'pollinates', visitsFlowersOf: 'visits flowers of',
  visits: 'visits', dispersesSeedsOf: 'disperses seeds of', hasDispersalVector: 'seeds dispersed by', hasHost: 'lives on',
  parasiteOf: 'parasite of', pathogenOf: 'pathogen of', ectoparasiteOf: 'lives on', endoparasiteOf: 'lives in',
  parasitoidOf: 'parasitoid of', hasVector: 'carried by', interactsWith: 'interacts with', coOccursWith: 'found with',
  symbiontOf: 'symbiont of', mutualistOf: 'mutualist of', adjacentTo: 'found next to', hasRoost: 'roosts in',
  coRoostsWith: 'roosts with', epiphyteOf: 'grows on', laysEggsOn: 'lays eggs on' };

const NICHE_PLACES = 10;

const KNOWN_TRENDS = new Set(['Increasing', 'Stable', 'Decreasing']);   // IUCN's trends; "Unknown" is not known

/** The seven gaps for one species: [{term, plain, state: known | part | gap | na, text}]. f: what the species file
 * gives (undefined: this list does not measure it); S: the list's summary. */
export function gapStates(f, S) {
  const since = S.recent_from;
  const g = (term, plain, state, text) => ({ term, plain, state, text });
  return [
    g('Linnean', 'Which species exist', f.year ? 'known' : 'gap', f.year ? `Described in ${f.year}.` : 'The year it was described is not known.'),
    g('Wallacean', 'Where it lives', f.latest >= since ? 'known' : f.latest ? 'part' : 'gap',
      f.latest >= since ? `A placed record since ${since} (latest ${f.latest}).` : f.latest ? `Placed records, the latest in ${f.latest}.` : 'No record placed in a district.'),
    f.trend == null ? g('Prestonian', 'How many there are', 'na', 'Not assessed by IUCN, and not in State of India’s Birds.')
      : g('Prestonian', 'How many there are', f.trend ? 'known' : 'gap', f.trend
        ? (KNOWN_TRENDS.has(f.iucnTrend) ? `Population ${f.iucnTrend.toLowerCase()} (IUCN Red List).` : 'A known population trend (State of India’s Birds).')
        : f.iucnTrend ? 'Assessed by IUCN, but the population trend is not known.' : 'No known population trend.'),
    f.barcode === undefined && !f.dna ? g('Darwinian', 'How it is related', 'na', 'Not measured in this list.')
      : g('Darwinian', 'How it is related', f.dna || f.barcode === 2 ? 'known' : f.barcode === 1 ? 'part' : 'gap',
        f.dna ? 'A DNA sequence or sample from India.' : f.barcode === 2 ? 'A DNA barcode from India (BOLD).' : f.barcode === 1 ? 'A DNA barcode, but not from India.' : 'No DNA barcode.'),
    f.traits === undefined || S.traits == null ? g('Raunkiæran', 'What it is like', 'na', 'Not measured in this list.')
      : g('Raunkiæran', 'What it is like', f.traits ? 'known' : 'gap', f.traits ? 'A record with a life stage, a sex, or flowers or fruits.' : 'No record with a trait.'),
    f.precise === undefined || S.niche == null ? g('Hutchinsonian', 'What conditions it needs', 'na', 'Not measured in this list.')
      : g('Hutchinsonian', 'What conditions it needs', f.precise >= NICHE_PLACES ? 'known' : 'gap',
        `${fmt(f.precise || 0)} places with an exact record (${NICHE_PLACES} or more relate it to climate maps).`),
    g('Eltonian', 'How it interacts', f.interactionsIndia ? 'known' : f.partners ? 'part' : 'gap',
      f.interactionsIndia ? 'Interactions recorded in India.' : f.partners ? 'Interactions recorded, none in India.' : 'No interaction recorded.'),
  ];
}

/** The partner tree: one branch per kind of link the species has (in KINDS order), its partners with most records
 * first, `top` of them shown at first. [{kind, label, color, total, rows: [{name, key, n, india, types, bar, shown}]}];
 * bar: records as a share of the kind's largest. */
export function tree(web, { top = 8 } = {}) {
  return KINDS.filter(k => web.n?.[k.k]).map(k => {
    const list = web.p[k.k] || [], max = Math.max(1, ...list.map(r => r[2]));
    return { kind: k.k, label: k.label, color: k.color, total: web.n[k.k],
      rows: list.map(([name, key, n, india, types], i) => ({ name, key, n, india: india > 0, types, bar: n / max, shown: i < top })) };
  });
}

// The pyramid of the seven gaps (in gapStates order): Linnean at the base, then Wallacean and Darwinian, then the four
// that need a name and a map first. The glyph draws the same layers in seven small cells.
export const LAYERS = [[2, 4, 5, 6], [1, 3], [0]];

/** Per gap, the share (whole per cent) of the group's documented species where it is known; null when the list does
 * not measure it, or the summary has no counts. */
export function groupShares(S, gi) {
  const known = S.gaps_known?.[gi], of = S.india?.[gi]?.[0];
  return Array.from({ length: 7 }, (_, i) => (known && of && known[i] != null ? Math.round(100 * known[i] / of) : null));
}

/** The pyramid as HTML: a button per gap (class blk <state>, data-i its index), its plain words first and the term
 * small, with a bar for the share of the group (`group`, a plural such as "bats") where the gap is known. */
export function pyramidHTML(gaps, shares, group) {
  return LAYERS.map(layer => `<div class="lvl l${layer.length}">${layer.map(i => {
    const g = gaps[i], pct = shares[i];
    const bar = pct == null ? `<span class="grp">${esc(group)}: not measured</span>`
      : `<span class="grp"><span>${esc(group)}</span><span class="bar"><i style="width:${pct}%"></i></span><span>${pct}%</span></span>`;
    return `<button type="button" class="blk ${g.state}" data-i="${i}" aria-pressed="false"><span class="t">${esc(g.plain)}</span>`
      + `<span class="p">${esc(g.term)}</span>${bar}</button>`;
  }).join('')}</div>`).join('');
}

/** The seven gaps as a small glyph (the pyramid's layers in seven cells), for lists. */
export function glyphSVG(states, size = 26) {
  const cell = (x, y, w, i) => `<rect x="${x}" y="${y}" width="${w}" height="8.5" rx="1.5" class="g-${states[i]}"/>`;
  return `<svg class="glyph" width="${size}" height="${(size * 0.8).toFixed(1)}" viewBox="0 0 40 32" aria-hidden="true">`
    + LAYERS[0].map((i, j) => cell(1 + j * 9.75, 1, 8.25, i)).join('')
    + LAYERS[1].map((i, j) => cell(6 + j * 14.25, 12, 13, i)).join('') + cell(12, 23, 16, 0) + '</svg>';
}

/** A small version of a photo for a thumbnail: iNaturalist's square (75 px), Commons at 120 px; others as they are. */
export function thumb(url) {
  return url ? url.replace(/\/medium\.(jpe?g|png)$/i, '/square.$1').replace(/\/\d+px-([^/]+)$/, '/120px-$1') : url;
}

/** Relatives from the family file (pipeline/master.py family_files): the genus of `name` first, then the rest, each
 * by its latest record; `top` at most, this species always among them when the file has it (a name that waits is
 * not in it). {rows: [{key, name, year, last, states, gaps: [state x 7], pic}], total}. */
export function relatives(rows, key, name, S, top = 40) {
  const genus = name.split(' ')[0];
  const all = rows.map(([k, name, year, last, states, trend, dna, barcode, traits, precise, partners, interactionsIndia, pic]) => ({
    key: k, name, year, last, states, pic: thumb(pic) || null,
    gaps: gapStates({ year, latest: last, trend, dna, barcode, traits, precise, partners, interactionsIndia }, S).map(g => g.state) }));
  all.sort((a, b) => (b.name.split(' ')[0] === genus) - (a.name.split(' ')[0] === genus) || (b.last ?? 0) - (a.last ?? 0)
    || a.name.localeCompare(b.name));
  const shown = all.slice(0, top);
  const me = all.find(r => r.key === key);
  if (me && !shown.includes(me)) shown[shown.length - 1] = me;
  return { rows: shown, total: all.length };
}

/** The species map: per district {cls, first, latest, n, obs, wait}. cls: recent (a GBIF record there since `since`),
 * old (only older GBIF records there), state (an open record in its state, the district not known), none. */
export function whereFill(districts, gbifDistricts, states, since) {
  const g = new Map((gbifDistricts || []).map(([id, first, latest, n]) => [id, { first, latest, n }]));
  return new Map(districts.map(d => {
    const s = states.get(d.state_lgd) || {}, r = g.get(d.id);
    const cls = r ? (r.latest >= since ? 'recent' : 'old') : s.obs ? 'state' : 'none';
    return [d.id, { cls, first: r?.first ?? null, latest: r?.latest ?? null, n: r?.n ?? 0, obs: !!s.obs, wait: s.wait || 0 }];
  }));
}
