// What changed since the previous weekly list, from the master list (layers/master/<period>/changes.json).

import { getJSON, fmt, esc, $, showLoadError, periodName } from './common.js';
import { MEASURES, series, geometry, nearest, tile, signed } from './trend.js';

const KINDS = [
  ['identified', 'Identified in India', 'First identification in India', 'var(--accent)'],
  ['state', 'Identified in a new state', 'First identification in a state', 'var(--blue)'],
  ['observed', 'Observed', 'First observation', 'var(--q3)'],
  ['documented', 'Added to the list', 'Added to the list', 'var(--ink-2)'],
  ['dropped', 'Off the list', 'No longer on the list', '#6B7771'],
  ['iucn', 'IUCN category', 'IUCN Red List category changed', 'var(--quiet)'],
];
const KIND = Object.fromEntries(KINDS.map(([k, chip, label, dot]) => [k, { chip, label, dot }]));
const PAGE = 50;

// Totals by week: six tiles (value, change since the list before, a small line) pick the measure of one chart.
function trend(H, groups) {
  const HT = 260, R = 16, T = 12, B = 30;
  let W = 800, L = 84;
  const asked = new URL(location.href).searchParams.get('m');   // a home-page tile opens its measure
  const st = { m: MEASURES.some(x => x.key === asked) ? asked : MEASURES[0].key, g: null, i: -1 };
  $('#tgroup').insertAdjacentHTML('beforeend', groups.map((g, i) => `<option value="${i}">${esc(g)}</option>`).join(''));
  function tiles() {
    $('#ttiles').innerHTML = MEASURES.map(m => tile(m, series(H, m.key, st.g), { pressed: m.key === st.m })).join('');
  }
  function chart() {
    // Drawn at the box's own width, so the labels keep their size on a phone.
    W = Math.max(280, Math.round($('#tsvg').clientWidth || 800)); L = W < 500 ? 64 : 84;
    $('#tsvg').setAttribute('viewBox', `0 0 ${W} ${HT}`);
    const m = MEASURES.find(x => x.key === st.m), pts = series(H, st.m, st.g);
    const g = geometry(pts, { w: W - L - R, h: HT - T - B, pad: 12 });
    const x = i => L + g.xs[i], y = i => T + g.ys[i];
    const yv = v => T + 12 + (HT - T - B - 24) * (1 - (v - g.min) / (g.max - g.min));
    $('#tchart-h').textContent = m.label + (st.g == null ? '' : ` · ${groups[st.g]}`);
    $('#tchart-note').textContent = `${pts.length} ${pts.length === 1 ? 'list' : 'lists'}, from ${periodName(pts[0].period)}. The scale starts above zero so that small changes show.`;
    const ticks = [g.min + (g.max - g.min) * 0.1, (g.min + g.max) / 2, g.max - (g.max - g.min) * 0.1];
    const narrow = W < 500, labelW = narrow ? 72 : 130;
    const step = Math.max(1, Math.ceil((pts.length * labelW) / (W - L - R)));
    const dateLabel = id => {
      const d = new Date(id.length === 7 ? `${id}-01T00:00:00Z` : `${id}T00:00:00Z`);
      const o = id.length === 7 ? { month: narrow ? 'short' : 'long', year: 'numeric' } : { day: 'numeric', month: narrow ? 'short' : 'long', ...(narrow ? {} : { year: 'numeric' }) };
      return d.toLocaleDateString('en-GB', { ...o, timeZone: 'UTC' });
    };
    $('#tsvg').innerHTML = ticks.map(v => `<line class="grid" x1="${L}" x2="${W - R}" y1="${yv(v)}" y2="${yv(v)}"/>
        <text class="axis" x="${L - 8}" y="${yv(v) + 4}" text-anchor="end">${fmt(Math.round(v))}</text>`).join('')
      // Dates under the line: short on a narrow chart, only every few weeks when they would touch, the last always;
      // the first and last sit inside the chart.
      + pts.map((p, i) => [p, i]).filter(([, i]) => i === pts.length - 1 || (i % step === 0 && pts.length - 1 - i >= step))
        .map(([p, i]) => `<text class="axis" x="${x(i)}" y="${HT - 8}" text-anchor="${pts.length > 1 && i === 0 ? 'start' : pts.length > 1 && i === pts.length - 1 ? 'end' : 'middle'}">${esc(dateLabel(p.period))}</text>`).join('')
      + `<path d="${pts.map((_, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(i).toFixed(1)}`).join('')}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>`
      + pts.map((_, i) => `<circle cx="${x(i)}" cy="${y(i)}" r="4" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>`).join('')
      + `<line id="tcross" y1="${T}" y2="${HT - B}" stroke="var(--ink-2)" stroke-width="1" visibility="hidden"/>`;
    $('#ttable').innerHTML = pts.map((p, i) => `<tr><td>${esc(periodName(p.period))}</td><td class="n mono">${fmt(p.value)}</td>
        <td class="n mono">${i ? signed(p.value - pts[i - 1].value) : ''}</td></tr>`).join('');
    const svg = $('#tsvg'), tip = $('#ttip'), cross = $('#tcross');
    const show = i => {
      st.i = i;
      if (i < 0) { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); return; }
      const d = i ? pts[i].value - pts[i - 1].value : null;
      cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
      tip.innerHTML = `<b>${fmt(pts[i].value)}</b>${d == null ? '' : ` (${signed(d)})`}<br>${esc(periodName(pts[i].period))}`;
      tip.hidden = false;
      const box = svg.getBoundingClientRect(), sx = box.width / W;
      const left = Math.min(Math.max(x(i) * sx - tip.offsetWidth / 2, 0), box.width - tip.offsetWidth);
      tip.style.transform = `translate(${left}px, ${Math.max(y(i) * sx - tip.offsetHeight - 12, 0)}px)`;
    };
    svg.onpointermove = e => { const box = svg.getBoundingClientRect(); show(nearest(pts.map((_, i) => x(i)), (e.clientX - box.left) * (W / box.width))); };
    svg.onpointerleave = svg.onblur = () => show(-1);
    svg.onkeydown = e => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      show(Math.min(Math.max((st.i < 0 ? pts.length : st.i) + (e.key === 'ArrowRight' ? 1 : -1), 0), pts.length - 1));
    };
  }
  $('#ttiles').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { st.m = b.dataset.m; tiles(); chart(); } });
  $('#tgroup').addEventListener('change', e => { st.g = e.target.value === '' ? null : Number(e.target.value); tiles(); chart(); });
  $('#trend').hidden = false;
  tiles(); chart();
  let pending;
  addEventListener('resize', () => { clearTimeout(pending); pending = setTimeout(chart, 150); });
}

try {
  const latest = await getJSON('layers/master/latest.json');
  const [S, ch, H] = await Promise.all([getJSON(latest.base + 'summary.json'), getJSON(latest.base + 'changes.json').catch(() => ({ from: null })),
    getJSON(latest.base + 'history.json').catch(() => null)]);
  if (H?.lists?.length) trend(H, H.groups);
  const stName = new Map(S.states.map(s => [Number(s.code), s.name]));
  $('#runline').textContent = `Master list · ${periodName(ch.to || S.period || S.month)}${ch.from ? ` compared with ${periodName(ch.from)}` : ''}`;

  if (!ch.from) {
    $('#baseline').hidden = false;
  } else {
    $('#feed').hidden = false;
    const rows = ch.rows.map(([kind, key, name, gi, states, sources, extra]) => ({ kind, key, name, gi, states, sources, extra }));
    const tiles = [['identified', 'species identified for the first time in India'], ['state', 'species identified for the first time in a state'],
      ['observed', 'species observed for the first time'], ['documented', 'species added to the list']];
    $('#tiles').innerHTML = tiles.map(([k, t]) => `<div class="card kpi"><b>${fmt(ch.counts[k] || 0)}</b><span>${t}</span></div>`).join('');
    const w = ch.waiting;
    $('#waitline').innerHTML = w && w.before != null
      ? `Observations on iNaturalist that wait for a name: ${fmt(w.before)} last week, ${fmt(w.now)} now. <a href="/?view=identified">See the species that wait</a>.`
      : '';
    $('#state').insertAdjacentHTML('beforeend', S.states.map(s => `<option value="${esc(s.code)}">${esc(s.name)}</option>`).join(''));

    let kind = 'identified', state = null, page = 0;
    const names = list => list.map(s => stName.get(s) || s).join(', ');
    const text = r => {
      const src = r.sources.length ? ` New source: ${r.sources.join(', ')}.` : '';
      if (r.kind === 'identified') return `First identification in India${r.states.length ? `, in ${names(r.states)}` : ''}.${src}`;
      if (r.kind === 'state') return `First identification in ${names(r.states)}.${src}`;
      if (r.kind === 'observed') return `First observation. Nobody has confirmed the name yet.${src}`;
      if (r.kind === 'documented') return `Added to the list.${src}`;
      if (r.kind === 'iucn') return r.extra?.[0] ? `IUCN Red List category was ${r.extra[0]}, now ${r.extra[1]}.` : `First IUCN Red List category: ${r.extra?.[1]}.`;
      return 'No longer on the list. The name changed, a source merged it with another species, or its records are not from India.';
    };
    const link = r => (r.key ? `<a href="/species?key=${encodeURIComponent(r.key)}"><i>${esc(r.name)}</i></a>` : `<i>${esc(r.name)}</i>`);
    function render() {
      const inState = r => state == null || r.states.includes(state);
      const count = k => rows.filter(r => r.kind === k && inState(r)).length;
      const view = rows.filter(r => r.kind === kind && inState(r));
      const slice = view.slice(page * PAGE, page * PAGE + PAGE);
      $('#items').innerHTML = slice.map(r => `<li>
          <span class="dot" style="background:${KIND[r.kind].dot}"></span>
          <div><div class="kind" style="color:${KIND[r.kind].dot}">${KIND[r.kind].label}</div>
          <div>${link(r)} · ${esc(S.groups[r.gi] || '')}</div>
          <div class="note" style="margin:2px 0 0">${esc(text(r))}</div></div></li>`).join('')
        || '<li class="muted" style="padding:24px;display:block">No changes of this kind here.</li>';
      $('#pinfo').textContent = view.length ? `Showing ${fmt(page * PAGE + 1)} to ${fmt(page * PAGE + slice.length)} of ${fmt(view.length)}` : '';
      $('#prev').disabled = page === 0; $('#next').disabled = (page + 1) * PAGE >= view.length;
      // A state only applies to identifications, which carry their states.
      $('#chips').innerHTML = KINDS.filter(([k]) => state == null || k === 'identified' || k === 'state')
        .map(([k, l]) => `<button type="button" class="chip" aria-pressed="${k === kind}" data-k="${k}">${l} <span class="mono">${fmt(count(k))}</span></button>`).join('');
    }
    $('#chips').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { kind = b.dataset.k; page = 0; render(); } });
    $('#state').addEventListener('change', e => {
      state = e.target.value ? Number(e.target.value) : null; page = 0;
      const has = k => rows.some(r => r.kind === k && (state == null || r.states.includes(state)));
      if (!has(kind) || (state != null && !['identified', 'state'].includes(kind))) kind = KINDS.map(([k]) => k).find(has) || kind;
      render();
    });
    $('#prev').addEventListener('click', () => { page--; render(); });
    $('#next').addEventListener('click', () => { page++; render(); });
    render();
    $('#groups').innerHTML = ch.groups.map((g, gi) => [gi, ...g]).filter(([, a, o, i, s]) => a + o + i + s)
      .sort((a, b) => (b[3] + b[4]) - (a[3] + a[4]))
      .map(([gi, a, o, i, s]) => `<tr><td>${esc(S.groups[gi])}</td><td class="n mono">${fmt(i)}</td><td class="n mono">${fmt(s)}</td><td class="n mono">${fmt(o)}</td><td class="n mono">${fmt(a)}</td></tr>`).join('')
      || '<tr><td colspan="5" class="muted">No group changed.</td></tr>';
  }
} catch (err) {
  showLoadError(err);
}
