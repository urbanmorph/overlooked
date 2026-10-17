import { snapshot, fmt, esc, $, monthName, showDevBanner, sourceLine, showLoadError } from './common.js';
import { drawMap, legendHTML } from './map.js';

try {
const snap = await snapshot();
const summaryP = snap.summary();
const mapP = Promise.all([snap.boundaries(), snap.stats()]);

const s = await summaryP;
showDevBanner(s);
const k = document.querySelectorAll('#kpis b');
k[0].textContent = fmt(s.quiet_species['1980']);
k[1].innerHTML = `${fmt(s.districts_with_quiet['1980'])} <small>of ${fmt(s.districts_total)}</small>`;
k[2].textContent = fmt(s.species);
k[3].textContent = fmt(s.records);

$('#snap').innerHTML = `<b>This snapshot</b>
  <div>Built ${esc(monthName(s.built))}</div>
  <div>GBIF ${(s.dois || []).map(d => `<a class="mono" href="https://doi.org/${esc(d)}">doi:${esc(d)}</a>`).join(', ')}</div>
  <div>Names: ${s.col_release ? 'Catalogue of Life ' + esc(s.col_release) : 'Catalogue of Life, as used by GBIF'}</div>`;
$('#source').innerHTML = sourceLine(s);

// Groups: bars of the share quiet since 1980, largest groups first.
const rows = s.groups.map((g, i) => ({ g, n: s.group_species[i], q: s.group_quiet_1980[i] }))
  .filter(r => r.n >= 100).sort((a, b) => b.q / b.n - a.q / a.n).slice(0, 12);
$('#gbars').innerHTML = rows.map(r => {
  const pct = (100 * r.q) / r.n;
  return `<div><span>${esc(r.g)}</span><span class="bar" title="${fmt(r.q)} of ${fmt(r.n)} species"><i style="width:${pct.toFixed(1)}%"></i></span><span>${pct.toFixed(0)}%</span></div>`;
}).join('');

const sel = $('#group');
sel.insertAdjacentHTML('beforeend', s.groups.map((g, i) => `<option value="${i}">${esc(g)}</option>`).join(''));

const [boundaries, stats] = await mapP;
const map = drawMap($('#map'), boundaries, {
  label: 'Map of India: number of species not recorded since 1980 in each district',
  onPick: d => { location.href = `/ledger?district=${d.id}`; },
});

function paint() {
  const gi = +sel.value + 1; // 0 = all groups
  const vals = new Map();
  for (const d of boundaries.districts) {
    const st = stats.districts[d.id];
    vals.set(d.id, st && st.s[gi] ? st.q[0][gi] : null);
  }
  const breaks = map.paint(vals, (id, v) => {
    const st = stats.districts[id];
    return v == null ? 'No public records' : `${fmt(v)} of ${fmt(st.s[gi])} species not recorded since 1980`;
  });
  $('#legend').innerHTML = legendHTML(breaks, 'Species not recorded since 1980');
}
sel.addEventListener('change', paint);
paint();
} catch (err) {
  showLoadError(err);
}
