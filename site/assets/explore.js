// Front page: India map, groups and search over the master species list (layers/master/<period>/).
// Three views: an open record, waiting for a name, IUCN. Groups and states are wired both ways; the URL keeps the state.
// With no filter the figures come from summary.json; with filters (year described, sources, status, IUCN,
// labels) they are counted from the group files, so the map, cards and list always show the same species.

import { getJSON, snapshot, fmt, esc, $, bit, tags, showLoadError } from './common.js';
import { drawMap, legendHTML } from './map.js';
import { fixSection } from './fix.js';
import { MEASURES, series, tile } from './trend.js';

// Top-level groups for the cards, built from the 28 pipeline groups by name.
const CATS = [
  ['insects', 'Insects', g => g.startsWith('Insects:')],
  ['plants', 'Flowering plants and ferns', g => g.startsWith('Plants:')],
  ['fungi', 'Fungi and lichens', g => g === 'Fungi' || g === 'Lichens'],
  ['mosses', 'Mosses, liverworts and algae', g => g === 'Mosses & liverworts' || g === 'Algae & diatoms'],
  ['fish', 'Fish', g => g === 'Fish'],
  ['inverts', 'Molluscs, spiders and crabs', g => ['Molluscs', 'Spiders & other arachnids', 'Crabs, shrimps & kin'].includes(g)],
  ['herps', 'Amphibians and reptiles', g => g === 'Amphibians' || g === 'Reptiles'],
  ['birds', 'Birds', g => g === 'Birds'],
  ['mammals', 'Mammals', g => g.startsWith('Mammals')],
  ['other', 'Other', g => g === 'Other'],
];
// Status of a species: on the list with no open record, with an open record, or named only in observations that wait.
const STATUS = ['No open record yet', 'Open record', 'Not on the list: waits for a name'];
const THREAT = new Set(['CR', 'EN', 'VU']);
const VIEW_TEXT = {
  observed: { card: 'share with an open record', unit: 'species with an open record' },
  waiting: { card: 'species that wait for a name', unit: 'species that wait for a name' },
  iucn: { card: 'threatened species', unit: 'threatened species with an open record' },
};
const PAGE = 50;
const IDENTIFY = 'https://www.inaturalist.org/observations/identify';
// iNaturalist iconic groups for each card, for observations named only above genus.
const CARD_ICONIC = { insects: ['Insecta'], plants: ['Plantae'], fungi: ['Fungi'], mosses: ['Chromista', 'Protozoa'], fish: ['Actinopterygii'],
  inverts: ['Mollusca', 'Arachnida'], herps: ['Amphibia', 'Reptilia'], birds: ['Aves'], mammals: ['Mammalia'], other: ['Animalia'] };
const ICONIC_NAME = { Insecta: 'Insects', Plantae: 'Plants', Fungi: 'Fungi', Chromista: 'Algae, diatoms and kin', Protozoa: 'Protozoa',
  Actinopterygii: 'Ray-finned fish', Mollusca: 'Molluscs', Arachnida: 'Spiders and kin', Amphibia: 'Amphibians', Reptilia: 'Reptiles',
  Aves: 'Birds', Mammalia: 'Mammals', Animalia: 'Other animals' };

// "described=2007-" or "1900-1950" or "-1900" in the address: a range of years described.
function parseYears(v) {
  const m = /^(\d{4})?-(\d{4})?$/.exec(v || '');
  return m ? { from: m[1] ? +m[1] : null, to: m[2] ? +m[2] : null } : { from: null, to: null };
}

try {
  const latest = await getJSON('layers/master/latest.json');
  const base = latest.base;
  getJSON(base + 'history.json').then(H => {   // This week: the totals and their change, each a link to its chart
    if (H?.lists?.length) $('#week').innerHTML = MEASURES.map(m => tile(m, series(H, m.key), { href: `/changes?m=${m.key}` })).join('');
  }).catch(() => {});
  const snap = await snapshot();
  const [S, boundaries] = await Promise.all([getJSON(base + 'summary.json'), snap.boundaries()]);
  const fix = fixSection(snap);
  const stIndex = new Map(S.states.map((s, i) => [String(s.code), i]));
  const stName = new Map(S.states.map(s => [String(s.code), s.name]));
  const cats = CATS.map(([key, name, test]) => ({ key, name, gis: S.groups.map((g, i) => (test(g) ? i : -1)).filter(i => i >= 0) }))
    .filter(c => c.gis.length);
  const allGis = S.groups.map((_, i) => i);
  const threatIdx = S.iucn.map((c, i) => (THREAT.has(c) ? i : -1)).filter(i => i >= 0);

  // State held in the URL so a view can be shared.
  const url = new URL(location.href);
  const asked = url.searchParams.get('view') === 'identified' ? 'waiting' : url.searchParams.get('view');  // old links
  const st = {
    view: ['observed', 'waiting', 'iucn'].includes(asked) ? asked : 'observed',
    list: ['genus', 'coarse'].includes(url.searchParams.get('list')) ? url.searchParams.get('list') : 'wait',
    cat: cats.some(c => c.key === url.searchParams.get('group')) ? url.searchParams.get('group') : null,
    state: stIndex.has(url.searchParams.get('state') || '') ? url.searchParams.get('state') : null,
    filters: { sources: new Set(), status: new Set(), iucn: new Set(), labels: new Set() },
    years: parseYears(url.searchParams.get('described')),
    district: null,   // a district chosen in search: outlined on the map; the figures stay those of its state
    pick: null,       // a name chosen in search that has no species page: listed first in its group
  };
  const saveURL = () => {
    const u = new URL(location.href);
    const described = st.years.from || st.years.to ? `${st.years.from ?? ''}-${st.years.to ?? ''}` : null;
    for (const [k, v] of [['view', st.view === 'observed' ? null : st.view], ['list', st.view === 'waiting' && st.list !== 'wait' ? st.list : null], ['group', st.cat], ['state', st.state], ['described', described]]) {
      if (v) u.searchParams.set(k, v); else u.searchParams.delete(k);
    }
    history.replaceState(null, '', u);
  };

  // Figures for a set of groups at India level or in one state, from A (summary.json, or counted for the filters).
  function fig(gis, state) {
    let doc = 0, obs = 0, thr = 0, assessed = 0, thrObs = 0;
    for (const gi of gis) {
      const [d, o, iu, to] = A.india[gi];
      if (state == null) {
        doc += d; obs += o; thrObs += to;
        thr += threatIdx.reduce((a, k) => a + iu[k], 0);
        assessed += iu.reduce((a, n, k) => a + (S.iucn[k] === 'NE' ? 0 : n), 0);
      } else {
        const v = A.by_state[state]?.[gi] || [0, 0];
        obs += v[0]; thrObs += v[1];
      }
    }
    return { doc, obs, thr, assessed, thrObs, wait: waitFig(gis, state) };
  }
  // iNaturalist observations that wait for a name: [species, observations, species with no open record here].
  const W = S.waiting || { india: [], by_state: {}, places: {} };
  // Sum per-group figures [a, b, ...] over groups, for India or one state.
  const sumOver = (india, byState, width) => (gis, state) => {
    const src = (state == null ? india : byState?.[state]) || [];
    return gis.reduce((a, gi) => a.map((x, k) => x + ((src[gi] || [])[k] || 0)), Array(width).fill(0));
  };
  const waitFig = (gis, state) => sumOver(A.wait.india, A.wait.by_state, 3)(gis, state);
  // Observations named only to genus [genera, observations], and only above genus (per iNaturalist iconic group).
  const genusFig = sumOver(W.genus?.india, W.genus?.by_state, 2);
  const coarseRows = (key, state) => {
    const counts = (state == null ? W.coarse?.india : W.coarse?.by_state[state]) || {};
    return (key ? CARD_ICONIC[key] || [] : Object.keys(counts)).map(g => [g, counts[g] || 0]).filter(([, n]) => n);
  };
  // Figures for no filter come from summary.json; with filters, counted() builds the same shape from the group files.
  const BASE = { india: S.india, by_state: S.by_state, wait: { india: W.india, by_state: W.by_state } };
  let A = BASE;
  const filtered = () => !!(st.years.from || st.years.to) || Object.values(st.filters).some(s => s.size);
  function filterText() {
    const y = st.years, n = Object.values(st.filters).reduce((a, s) => a + s.size, 0);
    const years = y.from && y.to ? `described ${y.from} to ${y.to}` : y.from ? `described ${y.from} or later` : y.to ? `described up to ${y.to}` : '';
    return [years, n ? `${n} filter${n === 1 ? '' : 's'}` : ''].filter(Boolean).map(t => ` · ${t}`).join('');
  }
  async function counted() {
    const nIucn = S.iucn.length, codes = S.states.map(s => String(s.code));
    const india = S.groups.map(() => [0, 0, Array(nIucn).fill(0), 0]), byState = {}, wIndia = S.groups.map(() => [0, 0, 0]), wState = {};
    const cell = (o, code, w) => (o[code] ||= S.groups.map(() => Array(w).fill(0)));
    const [g, w] = await Promise.all([Promise.all(allGis.map(groupRows)), Promise.all(allGis.map(waitRows))]);
    for (const r of g.flat()) {
      if (!passes(r)) continue;
      const gi = r[G], row = india[gi], threat = THREAT.has(S.iucn[r[4]]);
      row[0]++; row[1] += r[3] === 1; row[2][r[4]]++; row[3] += threat && r[3] === 1;
      for (let i = 0; i < codes.length; i++) {
        if (!bit(r[6], i)) continue;
        const v = cell(byState, codes[i], 2)[gi];
        v[0]++; v[1] += threat;
      }
    }
    for (const [r, , nIndia, states] of w.flat()) {
      if (!passes(r)) continue;
      const gi = r[G];
      if (nIndia) { const v = wIndia[gi]; v[0]++; v[1] += nIndia; v[2] += r[3] !== 1; }
      for (const [i, k] of states) { const v = cell(wState, codes[i], 3)[gi]; v[0]++; v[1] += k; v[2] += !bit(r[6], i); }
    }
    return { india, by_state: byState, wait: { india: wIndia, by_state: wState } };
  }
  const pct = (a, b) => (b ? `${((100 * a) / b).toFixed(a && a / b < 0.1 ? 1 : 0)}%` : '–');
  const catOf = key => cats.find(c => c.key === key);
  const catOfGi = gi => cats.find(c => c.gis.includes(gi));
  const gisNow = () => (st.cat ? catOf(st.cat).gis : allGis);

  // Value shown on the map and in the cards, by view.
  function value(f, india) {
    if (st.view === 'observed') return india ? { big: pct(f.obs, f.doc), line: `${fmt(f.obs)} of ${fmt(f.doc)} species have an open record`, n: f.obs } : { big: fmt(f.obs), line: 'species with an open record', n: f.obs };
    if (st.view === 'waiting') return { big: fmt(f.wait[0]), line: `species wait for a name · ${fmt(f.wait[1])} observations`, n: f.wait[0] };
    return india ? { big: fmt(f.thr), line: `threatened (CR, EN, VU) · ${fmt(f.assessed)} of ${fmt(f.doc)} assessed`, n: f.thr } : { big: fmt(f.thrObs), line: 'threatened species with an open record here', n: f.thrObs };
  }

  // Map: districts shaded by their state's figure.
  const map = drawMap($('#map'), boundaries, {
    label: 'Map of India by state', pickLabel: 'Choose this state',
    onPick: d => setState(String(d.state_lgd) === st.state ? null : String(d.state_lgd)),
  });
  function paintMap() {
    const gis = gisNow(), vals = new Map(), byState = new Map();
    for (const code of stIndex.keys()) byState.set(code, value(fig(gis, code), false).n);
    for (const d of boundaries.districts) vals.set(d.id, byState.has(String(d.state_lgd)) ? byState.get(String(d.state_lgd)) : null);
    document.querySelector('.ex-map').dataset.view = st.view;
    const breaks = map.paint(vals, id => {
      const s = String(map.info.get(id).state_lgd);
      return byState.has(s) ? `${fmt(byState.get(s))} ${VIEW_TEXT[st.view].unit} in the state` : 'No data';
    });
    $('#legend').innerHTML = legendHTML(breaks, `${VIEW_TEXT[st.view].unit[0].toUpperCase()}${VIEW_TEXT[st.view].unit.slice(1)}, by state`);
    map.focusState(st.state == null ? null : +st.state);
    map.select(st.district);
  }

  function paintCards() {
    const place = st.state ? stName.get(st.state) : 'India';
    $('#cards-title').textContent = `Groups in ${place}`;
    $('#cards-sub').textContent = st.state ? VIEW_TEXT[st.view].unit : VIEW_TEXT[st.view].card;
    const rows = [{ key: null, name: 'All groups', gis: allGis }, ...cats];
    $('#cards').innerHTML = rows.map(c => {
      const here = fig(c.gis, st.state), v = value(here, !st.state), f = fig(c.gis, null);
      // The bar: the share with an open record, the share threatened, or the share of waiting species for which one
      // confirmation gives the first open record here.
      const share = st.view === 'iucn' ? (f.doc ? f.thr / f.doc : 0) : st.view === 'waiting' ? (here.wait[0] ? here.wait[2] / here.wait[0] : 0)
        : (f.doc ? f.obs / f.doc : 0);
      return `<button type="button" class="gcard" data-cat="${c.key ?? ''}" aria-pressed="${(c.key ?? null) === st.cat}">
        <span class="gtop"><b>${esc(c.name)}</b><span class="mono">${v.big}</span></span>
        <span class="gline">${esc(v.line)}</span>
        <span class="gbar" aria-hidden="true"><i style="width:${Math.min(100, 100 * share).toFixed(1)}%"></i></span>
      </button>`;
    }).join('');
  }

  function paintHead() {
    const c = st.cat ? catOf(st.cat) : null, gis = gisNow(), f = fig(gis, st.state), india = !st.state;
    const v = value(f, india);
    const district = st.district && map.info.get(st.district)?.name;
    $('#crumb').textContent = `${st.state ? `India / ${stName.get(st.state)}${district ? ` / ${district}` : ''}` : 'India'} · ${c ? c.name : 'All groups'}${filterText()}`;
    $('#pq').textContent = india ? fmt(st.view === 'observed' ? f.obs : st.view === 'waiting' ? f.wait[0] : f.thr) : v.big;
    const districtNote = district ? ` The figures are for all of ${stName.get(st.state)}: the list counts species by state, not by district.` : '';
    $('#psub').textContent = st.view === 'waiting' ? `species named in observations that wait for a name on iNaturalist.${districtNote}`
      : india
      ? (st.view === 'iucn' ? `threatened species (CR, EN, VU) of ${fmt(f.doc)} documented. ${fmt(f.assessed)} ${f.assessed === 1 ? "is" : "are"} assessed by IUCN.`
        : `of ${fmt(f.doc)} documented species have an open record you can check online (${pct(f.obs, f.doc)}). The rest are known from checklists and papers.`)
      : `${v.line}.${districtNote}`;
    const w = f.wait, place = st.state ? stName.get(st.state) : 'India';
    const genus = genusFig(gis, st.state)[1], coarse = coarseRows(st.cat, st.state).reduce((a, [, n]) => a + n, 0);
    $('#pwait').hidden = st.view !== 'waiting' || !w[0];
    $('#pwait').innerHTML = `<b>${fmt(w[1])}</b> observations of <b>${fmt(w[0])}</b> species wait for a name on iNaturalist. `
      + `For <b>${fmt(w[2])}</b> of these species, one confirmation gives the first open record in ${esc(place)}.`
      + ((genus || coarse) && !filtered()
        ? ` A further <b>${fmt(genus)}</b> are named only to genus, and <b>${fmt(coarse)}</b> only to a family or a higher level.` : '')
      + (c ? '' : ' Choose a group to see them.');
    $('#sel-actions').hidden = !st.state;
    document.querySelectorAll('.views [data-view]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.view === st.view)));
  }

  // Species list for the chosen group, filtered by state, view and the filter chips.
  let shown = PAGE;
  // A g row: key, name, sources, status, IUCN, labels, states with an open record, year described;
  // the group index is added at G. A w row: that g row, then iNaturalist taxon, observations in India, [[state index, n]].
  const G = 8;
  const groupRows = gi => getJSON(`${base}g/${gi}.json`).then(d => d.rows.map(r => [...r, gi]));
  function passes(r, f = st.filters, y = st.years) {
    const [, , src, status, iucn, labels, , year] = r;
    if ((y.from || y.to) && (year == null || year < (y.from || 0) || year > (y.to || 9999))) return false;
    if (f.sources.size && ![...f.sources].some(i => bit(src, i))) return false;
    if (f.status.size && !f.status.has(status)) return false;
    if (f.iucn.size && !f.iucn.has(iucn)) return false;
    if (f.labels.size && ![...f.labels].every(i => bit(labels, i))) return false;
    return true;
  }
  const iucnBadge = i => `<span class="iucn i-${esc(S.iucn[i])}" title="IUCN Red List">${esc(S.iucn[i] === 'NE' ? 'Not assessed' : S.iucn[i])}</span>`;
  const speciesLink = (key, name) => (key ? `<a href="/species?key=${encodeURIComponent(key)}"><i>${esc(name)}</i></a>` : `<i>${esc(name)}</i>`);
  const HEAD_ALL = '<tr><th>Species</th><th>Group</th><th>Described</th><th>Status</th><th>IUCN</th><th>Sources</th><th>Labels</th></tr>';
  const HEAD_WAIT = '<tr><th>Species</th><th>Group</th><th>Why it matters</th><th>IUCN</th><th>Waiting</th><th>Help</th></tr>';
  const HEAD_GENUS = '<tr><th>Genus</th><th>Group</th><th>Why it matters</th><th>Species in India</th><th>Waiting</th><th>Help</th></tr>';
  const HEAD_COARSE = '<tr><th>Group</th><th></th><th></th><th></th><th>Waiting</th><th>Help</th></tr>';
  const waitRows = gi => getJSON(`${base}w/${gi}.json`).catch(() => ({ rows: [] }))
    .then(d => d.rows.map(x => [[...x.slice(0, G), gi], ...x.slice(G)]));
  const endBit = S.labels.findIndex(l => l.code === 'end');

  // Species with observations that wait for a name, most useful first.
  let listSeq = 0;
  async function paintWait(c, my) {
    const si = st.state ? stIndex.get(st.state) : null, place = st.state ? stName.get(st.state) : 'India';
    const w = await Promise.all(c.gis.map(gi => waitRows(gi)));
    if (my !== listSeq) return;
    const pid = placeId(), rows = [];
    for (const [r, taxon, nIndia, states] of w.flat()) {
      if (!passes(r)) continue;
      const n = waitingIn(nIndia, states, si);
      if (!n) continue;
      // never: no open record in India (not on the list at all, or known from checklists only); first: none here.
      const first = si == null ? r[3] !== 1 : !bit(r[6], si), never = r[3] !== 1, unlisted = r[3] === 2;
      const threat = THREAT.has(S.iucn[r[4]]), endemic = endBit >= 0 && bit(r[5], endBit);
      rows.push({ r, n, taxon, first, never, unlisted, threat, endemic, score: unlisted * 16 + never * 8 + first * 4 + threat * 2 + endemic });
    }
    rows.sort((a, b) => b.score - a.score || b.n - a.n || a.r[1].localeCompare(b.r[1]));
    $('#list-sub').textContent = `${fmt(rows.length)} species wait for a name · ${c.name}${st.state ? ` · ${place}` : ''}`;
    $('#list').innerHTML = rows.slice(0, shown).map(({ r, n, taxon, first, never, unlisted, threat, endemic }) => {
      const why = [unlisted ? '<span class="why first">Not on the India list yet</span>'
        : never ? '<span class="why first">No open record in India yet</span>'
        : first ? `<span class="why first">First open record in ${esc(place)}</span>` : '',
        threat ? '<span class="why">Threatened</span>' : '', endemic ? '<span class="why">Endemic to India</span>' : ''].join('');
      const link = idLink(identifyURL(pid, `taxon_id=${encodeURIComponent(taxon)}`));
      return `<tr><td>${speciesLink(r[0], r[1])}<div class="wm">${why}${iucnBadge(r[4])}<br><span class="mono">${fmt(n)}</span> waiting · ${link}</div></td>
        <td>${esc(S.groups[r[G]])}</td><td>${why || '<span class="muted">–</span>'}</td>
        <td>${iucnBadge(r[4])}</td><td class="mono">${fmt(n)}</td><td>${link}</td></tr>`;
    }).join('') || '<tr><td colspan="6" class="muted">No species wait for a name here.</td></tr>';
    $('#more').hidden = rows.length <= shown;
  }

  const waitingIn = (nIndia, states, si) => (si == null ? nIndia : (states.find(x => x[0] === si) || [0, 0])[1]);
  const identifyURL = (pid, extra) => `${IDENTIFY}?quality_grade=needs_id&place_id=${encodeURIComponent(pid)}&${extra}`;
  const idLink = href => `<a class="idlink" href="${href}" target="_blank" rel="noopener">Identify on iNaturalist</a>`;
  const placeId = () => W.places[st.state ?? 'india'] ?? W.places.india;

  // Genera with observations named only to genus, most useful first.
  async function paintGenus(c, my) {
    const si = st.state ? stIndex.get(st.state) : null, pid = placeId();
    const w = await Promise.all(c.gis.map(gi => getJSON(`${base}wg/${gi}.json`).catch(() => ({ rows: [] })).then(d => d.rows.map(r => [...r, gi]))));
    if (my !== listSeq) return;
    const rows = [];
    for (const [genus, taxon, nIndia, states, docs, unid, threat, endemic, gi] of w.flat()) {
      const n = waitingIn(nIndia, states, si);
      if (n) rows.push({ genus, taxon, n, docs, unid, threat, endemic, gi, score: (docs === 0) * 8 + (unid > 0) * 4 + (threat > 0) * 2 + (endemic > 0) });
    }
    rows.sort((a, b) => b.score - a.score || b.n - a.n || a.genus.localeCompare(b.genus));
    $('#list-sub').textContent = `${fmt(rows.length)} genera wait for a name · ${c.name}${st.state ? ` · ${stName.get(st.state)}` : ''}`;
    $('#list').innerHTML = rows.slice(0, shown).map(r => {
      const why = [r.docs === 0 ? '<span class="why first">Genus not on the India list</span>' : '',
        r.unid ? `<span class="why${r.unid === r.docs ? ' first' : ''}">${fmt(r.unid)} of ${fmt(r.docs)} species with no open record in India</span>` : '',
        r.threat ? `<span class="why">${fmt(r.threat)} threatened</span>` : '', r.endemic ? `<span class="why">${fmt(r.endemic)} endemic</span>` : ''].join('');
      const link = idLink(identifyURL(pid, `taxon_id=${encodeURIComponent(r.taxon)}&rank=genus`));
      return `<tr><td><i>${esc(r.genus)}</i><div class="wm">${why}<br><span class="mono">${fmt(r.n)}</span> waiting · ${link}</div></td>
        <td>${esc(S.groups[r.gi])}</td><td>${why || '<span class="muted">–</span>'}</td><td class="mono">${fmt(r.docs)}</td>
        <td class="mono">${fmt(r.n)}</td><td>${link}</td></tr>`;
    }).join('') || '<tr><td colspan="6" class="muted">No genera wait for a name here.</td></tr>';
    $('#more').hidden = rows.length <= shown;
  }

  // Observations named only above genus, per iNaturalist group.
  function paintCoarse(c) {
    const pid = placeId(), rows = coarseRows(c.key, st.state);
    $('#list-sub').textContent = `${c.name}${st.state ? ` · ${stName.get(st.state)}` : ''}`;
    $('#list').innerHTML = rows.map(([g, n]) => {
      const link = idLink(identifyURL(pid, `iconic_taxa=${encodeURIComponent(g)}&lrank=subtribe`));
      return `<tr><td>${esc(ICONIC_NAME[g] || g)}<div class="wm"><span class="mono">${fmt(n)}</span> waiting · ${link}</div></td><td></td><td></td><td></td>
        <td class="mono">${fmt(n)}</td><td>${link}</td></tr>`;
    }).join('') || '<tr><td colspan="6" class="muted">None here.</td></tr>';
    $('#more').hidden = true;
  }

  async function paintList() {
    const c = st.cat ? catOf(st.cat) : null;
    const mode = st.view === 'waiting' ? st.list : 'done', wait = mode !== 'done', my = ++listSeq;
    $('#list-mode').hidden = st.view !== 'waiting';
    document.querySelectorAll('#list-mode [data-list]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.list === st.list)));
    document.querySelectorAll('.wait-help').forEach(p => { p.hidden = !c || p.dataset.for !== mode; });
    $('#list-h').textContent = mode === 'genus' ? 'Genera' : mode === 'coarse' ? 'Groups' : 'Species';
    $('#list-head').innerHTML = { wait: HEAD_WAIT, genus: HEAD_GENUS, coarse: HEAD_COARSE }[mode] || HEAD_ALL;
    $('#list').closest('table').classList.toggle('waitlist', wait);
    if (!c) { $('#list').innerHTML = '<tr><td colspan="7" class="muted">Choose a group to list its species.</td></tr>'; $('#list-sub').textContent = ''; $('#more').hidden = true; return; }
    $('#list').innerHTML = '<tr><td colspan="7" class="muted">Loading…</td></tr>';
    if (mode === 'wait') return paintWait(c, my);
    if (mode === 'genus') return paintGenus(c, my);
    if (mode === 'coarse') return paintCoarse(c);
    const parts = await Promise.all(c.gis.map(gi => groupRows(gi)));
    if (my !== listSeq) return;
    const si = st.state ? stIndex.get(st.state) : null;
    const rows = parts.flat().filter(r => {
      if (si != null) {
        if (!bit(r[6], si)) return false;
      } else if (st.view === 'observed' && r[3] !== 1) return false;
      if (st.view === 'iucn' && !THREAT.has(S.iucn[r[4]])) return false;
      return passes(r);
    }).sort((a, b) => a[1].localeCompare(b[1]));
    $('#list-sub').textContent = `${fmt(rows.length)} species · ${c.name}${st.state ? ` · ${stName.get(st.state)}` : ''}`;
    // A name chosen in search with no species page goes first, whatever the view and the state.
    const picked = st.pick && parts.flat().find(r => !r[0] && r[1] === st.pick);
    if (picked) rows.splice(0, rows.length, picked, ...rows.filter(r => r !== picked));
    $('#list').innerHTML = rows.slice(0, shown).map(r => `<tr${r === picked ? ' class="picked"' : ''}>
        <td>${speciesLink(r[0], r[1])}${r === picked ? '<div class="muted">This name does not match the Catalogue of Life yet, so it has no species page.</div>' : ''}</td><td>${esc(S.groups[r[G]])}</td><td class="mono">${r[7] ?? '<span class="muted">–</span>'}</td><td>${STATUS[r[3]]}</td>
        <td>${iucnBadge(r[4])}</td><td>${tags(r[2], S.sources)}</td><td>${tags(r[5], S.labels.map(l => l.name))}</td></tr>`).join('')
      || '<tr><td colspan="7" class="muted">No species match.</td></tr>';
    $('#more').hidden = rows.length <= shown;
  }

  let paintSeq = 0;
  async function paint() {
    saveURL();
    const my = ++paintSeq;
    if (filtered()) {
      $('#psub').textContent = 'Counting the species for these filters…';
      const a = await counted();
      if (my !== paintSeq) return;
      A = a;
    } else A = BASE;
    paintCards(); paintHead(); paintMap(); paintFix(); await paintList();
  }
  // Records to fix: GBIF counts, so they follow the state and group but not the filters.
  function paintFix() {
    const c = st.cat ? catOf(st.cat) : null, names = c && new Set(c.gis.map(gi => S.groups[gi]));
    fix.then(f => f.paint(st.state, names && (g => names.has(g)), st.state ? stName.get(st.state) : 'India', c ? c.name : 'All groups'));
  }
  function setState(code, district = null) { st.state = code; st.district = district; shown = PAGE; return paint(); }
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const bringIntoView = (el, block = 'center') => el?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block });

  // Events.
  document.querySelector('.views').addEventListener('click', e => {
    const b = e.target.closest('[data-view]'); if (!b) return;
    st.view = b.dataset.view; shown = PAGE; paint();
  });
  $('#cards').addEventListener('click', e => {
    const b = e.target.closest('.gcard'); if (!b) return;
    st.cat = b.dataset.cat || null; st.pick = null; shown = PAGE; paint();
  });
  $('#list-mode').addEventListener('click', e => {
    const b = e.target.closest('[data-list]'); if (!b) return;
    st.list = b.dataset.list; shown = PAGE; saveURL(); paintList();
  });
  $('#clear-state').addEventListener('click', () => setState(null));
  $('#more').addEventListener('click', () => { shown += PAGE * 4; paintList(); });

  // Filters: sources, status, IUCN category and labels.
  const fdefs = [
    ['sources', 'Sources', S.sources.map((n, i) => [i, n])],
    ['status', 'Status', STATUS.map((n, i) => [i, n])],
    ['iucn', 'IUCN', S.iucn.map((n, i) => [i, n === 'NE' ? 'Not assessed' : n])],
    ['labels', 'Identification', S.labels.map((l, i) => [i, l.name, l.kind]).filter(x => x[2] === 'id')],
    ['labels', 'Other labels', S.labels.map((l, i) => [i, l.name, l.kind]).filter(x => x[2] !== 'id')],
  ];
  const D = S.described || {};
  $('#fgroups').innerHTML = `<fieldset id="fyears"><legend>Described</legend>
    <label class="yr">From <input id="y-from" type="number" inputmode="numeric" min="${D.from ?? 1753}" max="${D.to ?? ''}" placeholder="${D.from ?? 1753}"></label>
    <label class="yr">to <input id="y-to" type="number" inputmode="numeric" min="${D.from ?? 1753}" max="${D.to ?? ''}" placeholder="${D.to ?? ''}"></label>
    <span class="note">The year the species was first described.${D.unknown ? ` ${fmt(D.unknown)} species have no year in the sources and are left out when you give years.` : ''}</span>
    <span class="yr-quick">${[[2007, null, 'Since 2007'], [2000, null, 'Since 2000'], [null, 1900, 'Before 1900']].map(([f, t, l]) =>
      `<button type="button" class="b" data-from="${f ?? ''}" data-to="${t ?? ''}">${l}</button>`).join('')}</span></fieldset>`
    + fdefs.map(([k, title, opts]) => `<fieldset><legend>${esc(title)}</legend>${opts.map(([i, n]) =>
    `<label class="chip"><input type="checkbox" data-f="${k}" value="${i}"><span>${esc(n)}</span></label>`).join('')}</fieldset>`).join('');
  $('#fgroups').addEventListener('change', e => {
    const x = e.target; if (!x.dataset.f) return;
    const set = st.filters[x.dataset.f]; x.checked ? set.add(+x.value) : set.delete(+x.value);
    shown = PAGE; filtersChanged();
  });
  $('#fyears').addEventListener('change', () => {
    const from = parseInt($('#y-from').value, 10) || null, to = parseInt($('#y-to').value, 10) || null;
    st.years = from && to && from > to ? { from: to, to: from } : { from, to };
    shown = PAGE; filtersChanged();
  });
  $('#fclear').addEventListener('click', () => {
    for (const s of Object.values(st.filters)) s.clear();
    for (const x of document.querySelectorAll('#fgroups input[type=checkbox]')) x.checked = false;
    st.years = { from: null, to: null };
    filtersChanged();
  });
  function filtersChanged() {
    $('#y-from').value = st.years.from ?? ''; $('#y-to').value = st.years.to ?? '';
    const n = Object.values(st.filters).reduce((a, s) => a + s.size, 0) + (st.years.from || st.years.to ? 1 : 0);
    $('#fcount').textContent = n ? `(${n})` : '';
    paint(); runSearch();
  }
  $('#fyears').addEventListener('click', e => {
    const b = e.target.closest('[data-from]'); if (!b) return;
    st.years = { from: +b.dataset.from || null, to: +b.dataset.to || null };
    shown = PAGE; filtersChanged();
  });
  $('#fbtn').addEventListener('click', () => {
    const p = $('#filters'); p.hidden = !p.hidden; $('#fbtn').setAttribute('aria-expanded', String(!p.hidden));
  });

  // Search: groups and places from memory, species from a small file per first two letters.
  const prefix = s => { const p = s.toLowerCase().normalize('NFD').replace(/[^a-z]/g, '_').slice(0, 2); return p.length === 2 ? p : null; };
  const places = getJSON(base + 'search/places.json').catch(() => ({ rows: [] }));
  let seq = 0;
  async function runSearch() {
    const q = $('#q').value.trim().toLowerCase(), box = $('#hits'), my = ++seq;
    if (q.length < 2) { box.hidden = true; return; }
    const p = prefix(q);
    const [pl, sp] = await Promise.all([places, p ? getJSON(`${base}search/${p}.json`).catch(() => ({ rows: [] })) : { rows: [] }]);
    if (my !== seq) return;
    const hits = [];
    for (const c of cats) if (c.name.toLowerCase().includes(q)) hits.push({ html: esc(c.name), kind: 'Group', go: async () => { st.cat = c.key; st.pick = null; shown = PAGE; await paint(); bringIntoView($('#list-h'), 'start'); } });
    for (const r of pl.rows) {
      if (hits.length > 6) break;
      if (r[0].toLowerCase().startsWith(q)) hits.push({ html: esc(r[0]), kind: r[1] === 'state' ? 'State' : `District, ${esc(stName.get(String(r[3])) || '')}`, go: () => (r[1] === 'state' ? setState(String(r[2])) : setState(String(r[3]), r[2])) });
    }
    for (const r of sp.rows) {
      if (hits.length > 12) break;
      if (r[0].toLowerCase().startsWith(q) && passes([r[1], r[0], r[5], r[3], r[4], r[6], 0, r[7]])) {
        hits.push({ html: `<i>${esc(r[0])}</i> ${iucnBadge(r[4])}`, kind: `${STATUS[r[3]]} · ${esc(S.groups[r[2]])}`, go: () => (r[1] ? location.assign(`/species?key=${encodeURIComponent(r[1])}`) : showName(r[0], r[2], r[3])) });
      }
    }
    box.innerHTML = hits.map((h, i) => `<button type="button" role="option" data-i="${i}"><span>${h.html}</span><span class="muted">${h.kind}</span></button>`).join('')
      || '<div class="muted none">No match. Check the spelling, or clear the filters.</div>';
    box.hidden = false;
    box.onclick = e => { const b = e.target.closest('[data-i]'); if (!b) return; box.hidden = true; $('#q').value = ''; hits[+b.dataset.i].go(); };
  }
  // A name with no species page: open its group, list it first and bring it into view. A name not on the list
  // (status 2) is only in the lists of observations that wait.
  async function showName(name, gi, status) {
    st.cat = catOfGi(gi)?.key ?? null; st.pick = name; shown = PAGE;
    if (status === 2) { st.view = 'waiting'; st.list = 'wait'; } else if (st.view === 'waiting') st.view = 'observed';
    await paint();
    bringIntoView(document.querySelector('#list tr.picked'));
  }
  $('#q').addEventListener('input', runSearch);
  $('#q').addEventListener('keydown', e => { if (e.key === 'Escape') $('#hits').hidden = true; });
  document.addEventListener('pointerdown', e => { if (!e.target.closest('.search')) $('#hits').hidden = true; });

  if (S.notes?.length) $('footer .sources').insertAdjacentHTML('beforeend', `<div class="muted" style="margin-top:6px">${S.notes.map(esc).join(' ')}</div>`);
  filtersChanged();
} catch (err) {
  showLoadError(err);
}
