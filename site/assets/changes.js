// What changed since the previous weekly list, from the master list (layers/master/<period>/changes.json).

import { getJSON, fmt, esc, $, showLoadError, periodName } from './common.js';

const KINDS = [
  ['identified', 'Identified in India', 'First identification in India', 'var(--accent)'],
  ['state', 'Identified in a new state', 'First identification in a state', 'var(--blue)'],
  ['observed', 'Observed', 'First observation', 'var(--q3)'],
  ['documented', 'Added to the list', 'Added to the list', 'var(--ink-2)'],
  ['dropped', 'Off the list', 'No longer on the list', '#6B7771'],
];
const KIND = Object.fromEntries(KINDS.map(([k, chip, label, dot]) => [k, { chip, label, dot }]));
const PAGE = 50;

try {
  const latest = await getJSON('layers/master/latest.json');
  const [S, ch] = await Promise.all([getJSON(latest.base + 'summary.json'), getJSON(latest.base + 'changes.json').catch(() => ({ from: null }))]);
  const stName = new Map(S.states.map(s => [Number(s.code), s.name]));
  $('#runline').textContent = `Master list · ${periodName(ch.to || S.period || S.month)}${ch.from ? ` compared with ${periodName(ch.from)}` : ''}`;

  if (!ch.from) {
    $('#baseline').hidden = false;
  } else {
    $('#feed').hidden = false;
    const rows = ch.rows.map(([kind, key, name, gi, states, sources]) => ({ kind, key, name, gi, states, sources }));
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
      return 'No longer on the list. The name changed, or a source merged it with another species.';
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
