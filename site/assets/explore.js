// Front page: India map, groups and search over the master species list (layers/master/<month>/).
// Three views: observed, identified, IUCN. Groups and states are wired both ways; the URL keeps the state.

import { getJSON, snapshot, fmt, esc, $, showLoadError } from './common.js';
import { drawMap, legendHTML } from './map.js';

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
const STATUS = ['Listed only', 'Observed', 'Identified'];
const THREAT = new Set(['CR', 'EN', 'VU']);
const VIEW_TEXT = {
  observed: { card: 'share observed', unit: 'species observed' },
  identified: { card: 'share identified', unit: 'species identified' },
  iucn: { card: 'threatened species', unit: 'threatened species observed' },
};
const PAGE = 50;

try {
  const latest = await getJSON('layers/master/latest.json');
  const base = latest.base;
  const [S, boundaries] = await Promise.all([getJSON(base + 'summary.json'), snapshot().then(s => s.boundaries())]);
  const stIndex = new Map(S.states.map((s, i) => [String(s.code), i]));
  const stName = new Map(S.states.map(s => [String(s.code), s.name]));
  const cats = CATS.map(([key, name, test]) => ({ key, name, gis: S.groups.map((g, i) => (test(g) ? i : -1)).filter(i => i >= 0) }))
    .filter(c => c.gis.length);
  const allGis = S.groups.map((_, i) => i);
  const threatIdx = S.iucn.map((c, i) => (THREAT.has(c) ? i : -1)).filter(i => i >= 0);

  // State held in the URL so a view can be shared.
  const url = new URL(location.href);
  const st = {
    view: ['observed', 'identified', 'iucn'].includes(url.searchParams.get('view')) ? url.searchParams.get('view') : 'observed',
    cat: cats.some(c => c.key === url.searchParams.get('group')) ? url.searchParams.get('group') : null,
    state: stIndex.has(url.searchParams.get('state') || '') ? url.searchParams.get('state') : null,
    filters: { sources: new Set(), status: new Set(), iucn: new Set(), labels: new Set() },
  };
  const saveURL = () => {
    const u = new URL(location.href);
    for (const [k, v] of [['view', st.view === 'observed' ? null : st.view], ['group', st.cat], ['state', st.state]]) {
      if (v) u.searchParams.set(k, v); else u.searchParams.delete(k);
    }
    history.replaceState(null, '', u);
  };

  // Figures for a set of groups at India level or in one state.
  function fig(gis, state) {
    let doc = 0, obs = 0, id = 0, thr = 0, assessed = 0, thrObs = 0;
    for (const gi of gis) {
      const [d, o, i, iu, to] = S.india[gi];
      if (state == null) {
        doc += d; obs += o; id += i; thrObs += to;
        thr += threatIdx.reduce((a, k) => a + iu[k], 0);
        assessed += iu.reduce((a, n, k) => a + (S.iucn[k] === 'NE' ? 0 : n), 0);
      } else {
        const v = S.by_state[state]?.[gi] || [0, 0, 0];
        obs += v[0]; id += v[1]; thrObs += v[2];
      }
    }
    return { doc, obs, id, thr, assessed, thrObs };
  }
  const pct = (a, b) => (b ? `${((100 * a) / b).toFixed(a && a / b < 0.1 ? 1 : 0)}%` : '–');
  const catOf = key => cats.find(c => c.key === key);
  const gisNow = () => (st.cat ? catOf(st.cat).gis : allGis);

  // Value shown on the map and in the cards, by view.
  function value(f, india) {
    if (st.view === 'observed') return india ? { big: pct(f.obs, f.doc), line: `${fmt(f.obs)} of ${fmt(f.doc)} species observed`, n: f.obs } : { big: fmt(f.obs), line: 'species observed', n: f.obs };
    if (st.view === 'identified') return india ? { big: pct(f.id, f.doc), line: `${fmt(f.id)} of ${fmt(f.doc)} species identified`, n: f.id } : { big: fmt(f.id), line: `of ${fmt(f.obs)} observed species identified (${pct(f.id, f.obs)})`, n: f.id };
    return india ? { big: fmt(f.thr), line: `threatened (CR, EN, VU) · ${fmt(f.assessed)} of ${fmt(f.doc)} assessed`, n: f.thr } : { big: fmt(f.thrObs), line: 'threatened species observed here', n: f.thrObs };
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
  }

  function paintCards() {
    const place = st.state ? stName.get(st.state) : 'India';
    $('#cards-title').textContent = `Groups in ${place}`;
    $('#cards-sub').textContent = st.state ? VIEW_TEXT[st.view].unit : VIEW_TEXT[st.view].card;
    const rows = [{ key: null, name: 'All groups', gis: allGis }, ...cats];
    $('#cards').innerHTML = rows.map(c => {
      const v = value(fig(c.gis, st.state), !st.state), f = fig(c.gis, null);
      const share = st.view === 'iucn' ? (f.doc ? f.thr / f.doc : 0) : (f.doc ? (st.view === 'observed' ? f.obs : f.id) / f.doc : 0);
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
    $('#crumb').textContent = `${st.state ? `India / ${stName.get(st.state)}` : 'India'} · ${c ? c.name : 'All groups'}`;
    $('#pq').textContent = india ? fmt(st.view === 'observed' ? f.obs : st.view === 'identified' ? f.id : f.thr) : v.big;
    $('#psub').textContent = india
      ? (st.view === 'iucn' ? `threatened species (CR, EN, VU) of ${fmt(f.doc)} documented. ${fmt(f.assessed)} are assessed by IUCN.`
        : `of ${fmt(f.doc)} documented species are ${st.view} (${pct(st.view === 'observed' ? f.obs : f.id, f.doc)}).`)
      : `${v.line}.`;
    $('#sel-actions').hidden = !st.state;
    document.querySelectorAll('.views [data-view]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.view === st.view)));
  }

  // Species list for the chosen group, filtered by state, view and the filter chips.
  let shown = PAGE;
  const groupFile = gi => getJSON(`${base}g/${gi}.json`);
  const bit = (mask, i) => Math.floor(mask / 2 ** i) % 2 === 1;   // masks can pass 32 bits
  function passes(r, f) {
    const [, , src, status, iucn, labels] = r;
    if (f.sources.size && ![...f.sources].some(i => bit(src, i))) return false;
    if (f.status.size && !f.status.has(status)) return false;
    if (f.iucn.size && !f.iucn.has(iucn)) return false;
    if (f.labels.size && ![...f.labels].every(i => bit(labels, i))) return false;
    return true;
  }
  const tags = (mask, names) => names.map((n, i) => (bit(mask, i) ? `<span class="tag">${esc(n)}</span>` : '')).join('');
  const iucnBadge = i => `<span class="iucn i-${esc(S.iucn[i])}" title="IUCN Red List">${esc(S.iucn[i] === 'NE' ? 'Not assessed' : S.iucn[i])}</span>`;
  const speciesLink = (key, name) => (key ? `<a href="/species?key=${encodeURIComponent(key)}"><i>${esc(name)}</i></a>` : `<i>${esc(name)}</i>`);
  async function paintList() {
    const c = st.cat ? catOf(st.cat) : null;
    if (!c) { $('#list').innerHTML = '<tr><td colspan="6" class="muted">Choose a group to list its species.</td></tr>'; $('#list-sub').textContent = ''; $('#more').hidden = true; return; }
    $('#list').innerHTML = '<tr><td colspan="6" class="muted">Loading…</td></tr>';
    const parts = await Promise.all(c.gis.map(gi => groupFile(gi).then(d => d.rows.map(r => [...r, gi]))));
    const si = st.state ? stIndex.get(st.state) : null;
    const rows = parts.flat().filter(r => {
      if (si != null) {
        const inState = bit(r[6], si);
        if (!inState) return false;
        if (st.view === 'identified' && !bit(r[7], si)) return false;
      } else if (st.view === 'observed' && r[3] < 1) return false;
      else if (st.view === 'identified' && r[3] < 2) return false;
      if (st.view === 'iucn' && !THREAT.has(S.iucn[r[4]])) return false;
      return passes(r, st.filters);
    }).sort((a, b) => a[1].localeCompare(b[1]));
    $('#list-sub').textContent = `${fmt(rows.length)} species · ${c.name}${st.state ? ` · ${stName.get(st.state)}` : ''}`;
    $('#list').innerHTML = rows.slice(0, shown).map(r => `<tr>
        <td>${speciesLink(r[0], r[1])}</td><td>${esc(S.groups[r[8]])}</td><td>${STATUS[r[3]]}</td>
        <td>${iucnBadge(r[4])}</td><td>${tags(r[2], S.sources)}</td><td>${tags(r[5], S.labels.map(l => l.name))}</td></tr>`).join('')
      || '<tr><td colspan="6" class="muted">No species match.</td></tr>';
    $('#more').hidden = rows.length <= shown;
  }

  function paint() { saveURL(); paintCards(); paintHead(); paintMap(); paintList(); }
  function setState(code) { st.state = code; shown = PAGE; paint(); }

  // Events.
  document.querySelector('.views').addEventListener('click', e => {
    const b = e.target.closest('[data-view]'); if (!b) return;
    st.view = b.dataset.view; shown = PAGE; paint();
  });
  $('#cards').addEventListener('click', e => {
    const b = e.target.closest('.gcard'); if (!b) return;
    st.cat = b.dataset.cat || null; shown = PAGE; paint();
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
  $('#fgroups').innerHTML = fdefs.map(([k, title, opts]) => `<fieldset><legend>${esc(title)}</legend>${opts.map(([i, n]) =>
    `<label class="chip"><input type="checkbox" data-f="${k}" value="${i}"><span>${esc(n)}</span></label>`).join('')}</fieldset>`).join('');
  $('#fgroups').addEventListener('change', e => {
    const x = e.target; if (!x.dataset.f) return;
    const set = st.filters[x.dataset.f]; x.checked ? set.add(+x.value) : set.delete(+x.value);
    const n = Object.values(st.filters).reduce((a, s) => a + s.size, 0);
    $('#fcount').textContent = n ? `(${n})` : '';
    shown = PAGE; paintList(); runSearch();
  });
  $('#fclear').addEventListener('click', () => {
    for (const s of Object.values(st.filters)) s.clear();
    for (const x of document.querySelectorAll('#fgroups input')) x.checked = false;
    $('#fcount').textContent = ''; paintList(); runSearch();
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
    for (const c of cats) if (c.name.toLowerCase().includes(q)) hits.push({ html: esc(c.name), kind: 'Group', go: () => { st.cat = c.key; paint(); } });
    for (const r of pl.rows) {
      if (hits.length > 6) break;
      if (r[0].toLowerCase().startsWith(q)) hits.push({ html: esc(r[0]), kind: r[1] === 'state' ? 'State' : `District, ${esc(stName.get(String(r[3])) || '')}`, go: () => setState(String(r[1] === 'state' ? r[2] : r[3])) });
    }
    for (const r of sp.rows) {
      if (hits.length > 12) break;
      if (r[0].toLowerCase().startsWith(q) && passes([r[1], r[0], r[5], r[3], r[4], r[6]], st.filters)) {
        hits.push({ html: `<i>${esc(r[0])}</i> ${iucnBadge(r[4])}`, kind: `${STATUS[r[3]]} · ${esc(S.groups[r[2]])}`, go: () => { if (r[1]) location.href = `/species?key=${encodeURIComponent(r[1])}`; } });
      }
    }
    box.innerHTML = hits.map((h, i) => `<button type="button" role="option" data-i="${i}"><span>${h.html}</span><span class="muted">${h.kind}</span></button>`).join('')
      || '<div class="muted none">No match. Check the spelling, or clear the filters.</div>';
    box.hidden = false;
    box.onclick = e => { const b = e.target.closest('[data-i]'); if (!b) return; box.hidden = true; $('#q').value = ''; hits[+b.dataset.i].go(); };
  }
  $('#q').addEventListener('input', runSearch);
  $('#q').addEventListener('keydown', e => { if (e.key === 'Escape') $('#hits').hidden = true; });
  document.addEventListener('pointerdown', e => { if (!e.target.closest('.search')) $('#hits').hidden = true; });

  if (S.notes?.length) $('#source').insertAdjacentHTML('beforeend', `<div class="muted" style="margin-top:6px">${S.notes.map(esc).join(' ')}</div>`);
  paint();
} catch (err) {
  showLoadError(err);
}
