// The species web: one species at the centre, ringed by the seven gaps, with its partners (GloBI) around it by kind of
// link. Pure functions: the gaps for one species, the layout, and the SVG; species.js draws and wires it.

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

const R0 = 150, RINGS = [190, 240, 290, 340], PAD = 0.06;
const pol = (r, a) => [r * Math.sin(a), -r * Math.cos(a)];

/** Positions for the partners: a sector per kind of link (wider for more partners), the `cap` with most records in
 * each, out from the centre ring by ring. {sectors: [{kind, a0, a1, mid, total, more}], nodes: [{kind, name, key, n,
 * india, types, x, y, r, a, labelled}]} */
export function layout(web, { cap = 24 } = {}) {
  const kinds = KINDS.filter(k => web.n?.[k.k]);
  const shown = Object.fromEntries(kinds.map(k => [k.k, (web.p[k.k] || []).slice(0, cap)]));
  const w = kinds.map(k => Math.max(Math.sqrt(shown[k.k].length), 1.2));
  const total = w.reduce((a, b) => a + b, 0), span = 2 * Math.PI - PAD * kinds.length;
  const sectors = [], nodes = [];
  let a0 = -Math.PI * 0.6;
  kinds.forEach((k, ki) => {
    const width = span * w[ki] / total, list = shown[k.k];
    const per = Math.max(3, Math.ceil(list.length / RINGS.length));
    list.forEach(([name, key, n, india, types], i) => {
      const ring = Math.min(Math.floor(i / per), RINGS.length - 1);
      const inRing = list.slice(ring * per, ring * per + per).length, j = i - ring * per;
      const a = a0 + width * (0.08 + 0.84 * (inRing === 1 ? 0.5 : (j + 0.5) / inRing));
      const [x, y] = pol(RINGS[ring], a);
      nodes.push({ kind: k.k, name, key, n, india: india > 0, types, x, y, a, r: 3.5 + 2.6 * Math.log10(n + 1), labelled: i < 2 });
    });
    sectors.push({ kind: k.k, a0, a1: a0 + width, mid: a0 + width / 2, total: web.n[k.k], more: web.n[k.k] - list.length });
    a0 += width + PAD;
  });
  return { sectors, nodes };
}

const arc = (r1, r2, b0, b1) => {
  const [x0, y0] = pol(r2, b0), [x1, y1] = pol(r2, b1), [x2, y2] = pol(r1, b1), [x3, y3] = pol(r1, b0);
  return `M${x0},${y0}A${r2},${r2} 0 0 1 ${x1},${y1}L${x2},${y2}A${r1},${r1} 0 0 0 ${x3},${y3}Z`;
};
const f1 = v => v.toFixed(1);
const short = s => (s.length > 24 ? `${s.slice(0, 23)}…` : s);

/** The SVG: partners (each a focusable button with data-i, its index in L.nodes), sector labels, the gap ring and
 * the name at the centre. */
export function webSVG(L, gaps, name) {
  const kind = Object.fromEntries(KINDS.map(k => [k.k, k]));
  let lines = '', dots = '', text = '';
  L.nodes.forEach((n, i) => {
    const c = kind[n.kind].color, [lx, ly] = pol(R0 + 4, n.a);
    lines += `<line x1="${f1(lx)}" y1="${f1(ly)}" x2="${f1(n.x)}" y2="${f1(n.y)}" stroke="${c}" stroke-opacity=".3"/>`;
    dots += `<g class="wn" data-i="${i}" tabindex="0" role="button" aria-label="${esc(n.name)}: ${esc(kind[n.kind].label)}">`
      + `<circle class="hit" cx="${f1(n.x)}" cy="${f1(n.y)}" r="${f1(n.r + 7)}" fill="transparent"/>`
      + `<circle cx="${f1(n.x)}" cy="${f1(n.y)}" r="${f1(n.r)}" fill="${n.india ? c : '#fff'}" stroke="${c}" stroke-width="2"/></g>`;
    if (n.labelled) {
      const [tx, ty] = pol(Math.hypot(n.x, n.y) + n.r + 9, n.a), right = Math.sin(n.a) >= 0;
      text += `<text x="${f1(tx)}" y="${f1(ty + 5)}" text-anchor="${right ? 'start' : 'end'}" class="wl">${esc(short(n.name))}</text>`;
    }
  });
  for (const s of L.sectors) {
    const [x, y] = pol(388, s.mid), side = Math.sin(s.mid), anchor = side > 0.1 ? 'start' : side < -0.1 ? 'end' : 'middle';
    text += `<text x="${f1(x)}" y="${f1(y)}" text-anchor="${anchor}" class="ws">${esc(kind[s.kind].label)}</text>`
      + `<text x="${f1(x)}" y="${f1(y + 22)}" text-anchor="${anchor}" class="wm">${s.more > 0 ? `${fmt(s.total)} species, ${fmt(s.total - s.more)} shown` : `${fmt(s.total)} species`}</text>`;
  }
  let ring = '';
  gaps.forEach((g, i) => {
    const b0 = i * 2 * Math.PI / 7 + 0.04, b1 = (i + 1) * 2 * Math.PI / 7 - 0.04, [tx, ty] = pol(R0 - 6, (b0 + b1) / 2);
    ring += `<path class="g-${g.state}" d="${arc(R0 - 46, R0 - 22, b0, b1)}"><title>${esc(g.term)}: ${esc(g.text)}</title></path>`
      + `<text x="${f1(tx)}" y="${f1(ty + 5)}" text-anchor="middle" class="wg">${esc(g.term.slice(0, 4))}</text>`;
  });
  const [genus, ...rest] = name.split(' ');
  return `<svg viewBox="-560 -450 1120 900" role="img" aria-label="${esc(name)}: its partner species by kind of link, around the seven gaps">`
    + `<g>${lines}</g><g>${dots}</g><g>${text}</g><g>${ring}</g>`
    + `<circle r="${R0 - 52}" fill="#fff" stroke="var(--line)"/>`
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
