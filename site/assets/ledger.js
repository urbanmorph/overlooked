import { snapshot, getJSON, fmt, esc, $, showDevBanner, sourceLine, showLoadError } from './common.js';
import { drawMap, legendHTML } from './map.js';

try {
const PAGE = 50;
const snap = await snapshot();
const [summary, boundaries, stats] = await Promise.all([snap.summary(), snap.boundaries(), snap.stats()]);
showDevBanner(summary);
// Species keys are Catalogue of Life IDs (GBIF SQL downloads); the fnf development data uses GBIF keys.
const taxonURL = k => summary.taxon_ids === 'gbif' ? `https://www.gbif.org/species/${encodeURIComponent(k)}`
  : `https://www.catalogueoflife.org/data/taxon/${encodeURIComponent(k)}`;
$('#runline').textContent = `Module 01 · snapshot ${summary.run_id}`;
$('#source').innerHTML = sourceLine(summary);

const groups = summary.groups;
const years = stats.years;
const districts = boundaries.districts;
const byId = new Map(districts.map(d => [d.id, d]));
const stateNames = new Map(districts.map(d => [d.state_lgd, d.state]));

// State, from the URL first.
const url = new URLSearchParams(location.search);
const st = {
  group: url.has('group') ? +url.get('group') : -1,
  district: url.has('district') ? +url.get('district') : null,
  state: url.has('state') ? +url.get('state') : null,
  since: years.includes(+url.get('since')) ? +url.get('since') : years[0],
  q: url.get('q') || '',
  all: url.get('all') === '1',
  unsurv: url.get('unsurveyed') === '1',
  sort: 'last', dir: 1, page: 0,
};
if (st.district != null && byId.has(st.district)) st.state = byId.get(st.district).state_lgd;
else st.district = null;

// Filters.
const fGroup = $('#f-group'), fState = $('#f-state'), fDist = $('#f-district'), fSince = $('#f-since'), fQ = $('#f-q'), fAll = $('#f-all');
fGroup.insertAdjacentHTML('beforeend', groups.map((g, i) => `<option value="${i}">${esc(g)}</option>`).join(''));
fState.insertAdjacentHTML('beforeend', [...stateNames].sort((a, b) => a[1].localeCompare(b[1]))
  .map(([id, n]) => `<option value="${id}">${esc(n)}</option>`).join(''));
fSince.innerHTML = years.map(y => `<option>${y}</option>`).join('');

function fillDistricts() {
  const list = districts.filter(d => st.state == null || d.state_lgd === st.state).sort((a, b) => a.name.localeCompare(b.name));
  fDist.innerHTML = '<option value="">All districts</option>' +
    list.map(d => `<option value="${d.id}">${esc(d.name)}${st.state == null ? ', ' + esc(d.state) : ''}</option>`).join('');
  fDist.value = st.district ?? '';
}

function syncControls() {
  fGroup.value = st.group; fState.value = st.state ?? ''; fSince.value = st.since; fQ.value = st.q; fAll.checked = st.all;
  $('#f-unsurv').checked = st.unsurv;
  fillDistricts();
  $('#all-wrap').hidden = st.district == null;
}

function syncURL() {
  const p = new URLSearchParams();
  if (st.group >= 0) p.set('group', st.group);
  if (st.district != null) p.set('district', st.district); else if (st.state != null) p.set('state', st.state);
  if (st.since !== years[0]) p.set('since', st.since);
  if (st.q) p.set('q', st.q);
  if (st.all && st.district != null) p.set('all', '1');
  if (st.unsurv) p.set('unsurveyed', '1');
  history.replaceState(null, '', p.toString() ? `?${p}` : location.pathname);
}

// Map.
const map = drawMap($('#map'), boundaries, {
  label: 'Map of India: species not recorded since the year, in each district. Select a district to filter the table.',
  onPick: d => { st.district = st.district === d.id ? null : d.id; st.state = d.state_lgd; update(); },
});

function paintMap() {
  const gi = st.group + 1, yi = years.indexOf(st.since);
  const vals = new Map();
  for (const d of districts) {
    const s = stats.districts[d.id];
    vals.set(d.id, s && s.s[gi] ? s.q[yi][gi] : null);
  }
  const breaks = map.paint(vals, (id, v) => v == null ? 'No public records' :
    `${fmt(v)} of ${fmt(stats.districts[id].s[gi])} species not recorded since ${st.since}`);
  $('#legend').innerHTML = legendHTML(breaks, `Species not recorded since ${st.since}`);
  map.select(st.district);
  map.focusState(st.state);
}

// Rows for the current area.
let rows = [], view = [], loadToken = 0;
function rowsFile() {
  if (st.district != null) return snap.file(`ledger/d/${st.district}.json`);
  if (st.state != null) return snap.file(`ledger/s/${st.state}.json`);
  return snap.file('ledger/india.json');
}

async function loadRows() {
  const token = ++loadToken;
  $('#count').textContent = 'Loading species…';
  let data;
  try { data = await getJSON(rowsFile()); } catch { data = { rows: [], scope: 'all' }; }
  if (token !== loadToken) return null;
  rows = data.rows.map(r => ({ key: r[0], name: r[1], gi: r[2], family: r[3] || '', first: r[4], last: r[5], n: r[6] }));
  return data.scope;
}

// Effort for the current area: species of each group recorded since each year. A group with none is
// treated as unsurveyed there: its old records are shown apart, not counted as quiet.
function area() {
  if (st.district != null) return stats.districts[st.district] || { s: [], a: years.map(() => []) };
  if (st.state != null) return stats.states[st.state] || { s: [], a: years.map(() => []) };
  return stats.india;
}
const isOld = r => r.last != null && r.last < st.since;
// iNaturalist layer: species with an observation in India, including ones not shared with GBIF.
// flags[key] = [latest date, quality grade, open licence 1/0, observations in India]
let flags = {}, inatInfo = null;
getJSON('layers/inat/latest.json').then(l => { inatInfo = l; return l && l.quiet_flags ? getJSON(l.quiet_flags) : null; })
  .then(f => { if (f && f.snapshot === summary.run_id) { flags = f.species; refresh(); } }).catch(() => {});
const QUALITY = { research: 'research grade', needs_id: 'waits for a name', casual: 'casual' };
function inatNote(r) {
  const f = flags[r.key];
  if (!f || !f[0] || +f[0].slice(0, 4) < st.since) return '';
  return `<br><span class="tagi">iNaturalist: seen in India ${esc(f[0])} (${QUALITY[f[1]] || esc(f[1])}${f[2] ? '' : ', no open licence'})</span>`;
}
function surveyed(r) { return (area().a[years.indexOf(st.since)][r.gi + 1] || 0) > 0; }

const KEYS = { name: r => r.name, gi: r => groups[r.gi], family: r => r.family, first: r => r.first ?? 9999, last: r => r.last ?? 9999, n: r => r.n };

function filter() {
  const q = st.q.toLowerCase();
  const allMode = st.all && st.district != null;
  view = rows.filter(r => (allMode || (isOld(r) && (surveyed(r) || st.unsurv)))
    && (st.group < 0 || r.gi === st.group)
    && (!q || r.name.toLowerCase().includes(q) || r.family.toLowerCase().includes(q)));
  const key = KEYS[st.sort], dir = st.dir;
  view.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : a.name < b.name ? -1 : 1) * dir; });
}

function areaLabel() {
  if (st.district != null) { const d = byId.get(st.district); return `${d.name}, ${d.state}`; }
  if (st.state != null) return stateNames.get(st.state);
  return 'All of India';
}

function renderAside() {
  const gi = st.group + 1, yi = years.indexOf(st.since);
  const total = area().s[gi];
  const old = rows.filter(r => isOld(r) && (st.group < 0 || r.gi === st.group));
  const quiet = old.filter(surveyed);
  const unsurveyed = old.length - quiet.length;
  const before1950 = quiet.filter(r => r.last < 1950).length;
  const counts = new Map();
  for (const r of quiet) counts.set(r.gi, (counts.get(r.gi) || 0) + 1);
  const top = [...counts].sort((a, b) => b[1] - a[1]).slice(0, 6);
  const max = top.length ? top[0][1] : 1;
  const code = st.district != null && st.district > 0 ? `<div class="mono note" style="margin:2px 0 0">LGD code ${st.district}</div>` : '';
  $('#aside').innerHTML = `
    <div><div class="note" style="margin:0">Selected</div><h2 style="font-size:22px">${esc(areaLabel())}</h2>${code}</div>
    <dl class="stats" style="margin-top:16px">
      <dt>Species with public records</dt><dd>${fmt(total ?? 0)}</dd>
      <dt>No public record since ${st.since}</dt><dd class="q">${fmt(quiet.length)}</dd>
      <dt>Latest record before 1950</dt><dd>${fmt(before1950)}</dd>
      <dt>Not counted: no record of the group here since ${st.since}</dt><dd>${fmt(unsurveyed)}</dd>
      ${Object.keys(flags).length ? `<dt>Not recorded here since ${st.since}, but seen in India on iNaturalist${inatInfo && !inatInfo.quiet_complete ? ` (check in progress: ${fmt(inatInfo.quiet_checked)} of ${fmt(inatInfo.quiet_of)} species checked)` : ''}</dt><dd>${fmt(quiet.filter(r => flags[r.key] && +String(flags[r.key][0]).slice(0, 4) >= st.since).length)}</dd>` : ''}
    </dl>
    ${top.length && st.group < 0 ? `<div style="border-top:1px solid var(--line-2);margin-top:16px;padding-top:14px">
      <div style="font-size:13px;font-weight:600;color:var(--ink-2);margin-bottom:8px">Species not recorded since the year, by group</div>
      <div class="gbars">${top.map(([g, c]) => `<div><span>${esc(groups[g])}</span><span class="bar"><i style="width:${(100 * c / max).toFixed(1)}%"></i></span><span>${fmt(c)}</span></div>`).join('')}</div>
    </div>` : ''}
    ${st.district != null || st.state != null ? '<button class="b" type="button" id="clear" style="margin-top:16px">Show all of India</button>' : ''}`;
  const c = $('#clear');
  if (c) c.addEventListener('click', () => { st.district = null; st.state = null; update(); });
}

function renderTable() {
  const allMode = st.all && st.district != null;
  $('#count').innerHTML = allMode
    ? `${fmt(view.length)} species in ${esc(areaLabel())}`
    : `${fmt(view.length)} species with no public record since ${st.since} in ${esc(areaLabel())}`;
  const parts = [];
  if (st.district == null) parts.push('To see all the species with records in an area, select a district.');
  if (!allMode) parts.push(st.unsurv
    ? `This list includes groups with no record here since ${st.since}. A label shows these species.`
    : `This list does not include groups with no record here since ${st.since}. Possibly nobody surveyed these groups here.`);
  $('#scope').textContent = parts.join(' ');
  const pages = Math.max(1, Math.ceil(view.length / PAGE));
  st.page = Math.min(st.page, pages - 1);
  const slice = view.slice(st.page * PAGE, st.page * PAGE + PAGE);
  $('#rows').innerHTML = slice.length ? slice.map(r => `<tr>
      <td class="sp"><a href="/species?key=${encodeURIComponent(r.key)}">${esc(r.name)}</a>${!allMode && isOld(r) ? inatNote(r) : ''}</td>
      <td>${esc(groups[r.gi])}${!allMode && !surveyed(r) ? '<br><span class="tagu">no record of the group here since ' + st.since + '</span>' : ''}</td>
      <td class="muted">${esc(r.family)}</td>
      <td class="n"><span class="yr">${r.first ?? '<span class="muted">unknown</span>'}</span></td>
      <td class="n"><span class="yr${r.last != null && r.last < st.since ? ' q' : ''}">${r.last ?? '<span class="muted">unknown</span>'}</span></td>
      <td class="n mono">${fmt(r.n)}</td></tr>`).join('')
    : `<tr><td colspan="6" class="muted" style="padding:28px 14px">There are no species for these filters.</td></tr>`;
  $('#pinfo').textContent = view.length ? `Showing ${fmt(st.page * PAGE + 1)} to ${fmt(st.page * PAGE + slice.length)} of ${fmt(view.length)}` : '';
  $('#prev').disabled = st.page === 0; $('#next').disabled = st.page >= pages - 1;
  for (const b of document.querySelectorAll('th button')) {
    const th = b.parentElement;
    if (b.dataset.k === st.sort) th.setAttribute('aria-sort', st.dir > 0 ? 'ascending' : 'descending');
    else th.removeAttribute('aria-sort');
  }
}

function refresh() { filter(); renderTable(); renderAside(); }

async function update() {
  st.page = 0;
  syncControls(); syncURL(); paintMap();
  if (await loadRows() === null) return;
  refresh();
}

// Events.
fGroup.addEventListener('change', () => { st.group = +fGroup.value; st.page = 0; syncURL(); paintMap(); refresh(); });
fSince.addEventListener('change', () => { st.since = +fSince.value; st.page = 0; syncURL(); paintMap(); refresh(); });
fState.addEventListener('change', () => { st.state = fState.value === '' ? null : +fState.value; st.district = null; update(); });
fDist.addEventListener('change', () => { st.district = fDist.value === '' ? null : +fDist.value; if (st.district != null) st.state = byId.get(st.district).state_lgd; update(); });
fAll.addEventListener('change', () => { st.all = fAll.checked; st.page = 0; syncURL(); refresh(); });
$('#f-unsurv').addEventListener('change', e => { st.unsurv = e.target.checked; st.page = 0; syncURL(); refresh(); });
let qt;
fQ.addEventListener('input', () => { clearTimeout(qt); qt = setTimeout(() => { st.q = fQ.value.trim(); st.page = 0; syncURL(); refresh(); }, 150); });
$('#prev').addEventListener('click', () => { st.page--; renderTable(); });
$('#next').addEventListener('click', () => { st.page++; renderTable(); });
for (const b of document.querySelectorAll('th button')) {
  b.addEventListener('click', () => {
    st.dir = st.sort === b.dataset.k ? -st.dir : 1; st.sort = b.dataset.k; st.page = 0; filter(); renderTable();
  });
}
$('#csv').addEventListener('click', () => {
  const head = ['gbif_species_key', 'species', 'group', 'family', 'first_record', 'latest_record', 'records', 'area', 'snapshot'];
  const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const lines = [head.join(',')].concat(view.map(r =>
    [r.key, r.name, groups[r.gi], r.family, r.first, r.last, r.n, areaLabel(), summary.run_id].map(q).join(',')));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }));
  a.download = `overlooked_${areaLabel().replace(/[^A-Za-z0-9]+/g, '-').toLowerCase()}_since-${st.since}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});

update();
} catch (err) {
  showLoadError(err);
}
