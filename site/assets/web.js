// The species web: the species ringed by its seven gaps, with its partners (GloBI) as a tree, a branch per kind of
// link. Pure functions: the gaps for one species, the tree, the ring; species.js draws and wires them. A radial layout
// was tried first: with 30 partners per kind the names collided.

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

/** The seven gaps for one species: [{term, plain, state: known | part | gap | na, text}]. f: what the species file
 * gives (undefined: this list does not measure it); S: the list's summary. */
export function gapStates(f, S) {
  const since = S.recent_from;
  const g = (term, plain, state, text) => ({ term, plain, state, text });
  return [
    g('Linnean', 'Which species exist', f.year ? 'known' : 'gap', f.year ? `Described in ${f.year}.` : 'The year it was described is not known.'),
    g('Wallacean', 'Where it lives', f.latest >= since ? 'known' : f.latest ? 'part' : 'gap',
      f.latest >= since ? `A placed record since ${since} (latest ${f.latest}).` : f.latest ? `Placed records, the latest in ${f.latest}.` : 'No record placed in a district.'),
    f.trend == null ? g('Prestonian', 'How many there are', 'na', 'Not measured for this group (only birds have open trends).')
      : g('Prestonian', 'How many there are', f.trend ? 'known' : 'gap', f.trend ? 'A known population trend (State of India’s Birds).' : 'No known population trend.'),
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

const pol = (r, a) => [r * Math.sin(a), -r * Math.cos(a)];
const arc = (r1, r2, b0, b1) => {
  const [x0, y0] = pol(r2, b0), [x1, y1] = pol(r2, b1), [x2, y2] = pol(r1, b1), [x3, y3] = pol(r1, b0);
  return `M${x0.toFixed(1)},${y0.toFixed(1)}A${r2},${r2} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)}L${x2.toFixed(1)},${y2.toFixed(1)}A${r1},${r1} 0 0 0 ${x3.toFixed(1)},${y3.toFixed(1)}Z`;
};

/** The species ringed by its seven gaps: a segment per gap (class g-<state>, with its text as a title), the
 * first four letters of each gap beside it, and the name at the centre. */
export function ringSVG(gaps, name) {
  const n = gaps.length;
  const ring = gaps.map((g, i) => {
    const b0 = i * 2 * Math.PI / n + 0.05, b1 = (i + 1) * 2 * Math.PI / n - 0.05, [tx, ty] = pol(122, (b0 + b1) / 2);
    return `<path class="g-${g.state}" d="${arc(80, 104, b0, b1)}"><title>${esc(g.term)}: ${esc(g.text)}</title></path>`
      + `<text x="${tx.toFixed(1)}" y="${(ty + 5).toFixed(1)}" text-anchor="middle" class="wg">${esc(g.term.slice(0, 4))}</text>`;
  }).join('');
  const [genus, ...rest] = name.split(' ');
  return `<svg viewBox="-150 -150 300 300" role="img" aria-label="${esc(name)} and the seven gaps">${ring}`
    + `<text y="-4" text-anchor="middle" class="wc">${esc(genus)}</text><text y="20" text-anchor="middle" class="wc">${esc(rest.join(' '))}</text></svg>`;
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
