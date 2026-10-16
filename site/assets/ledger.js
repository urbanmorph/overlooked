import { snapshot, getJSON, fmt, esc, $, showDevBanner, sourceLine } from './common.js';
import { drawMap, legendHTML } from './map.js';

const PAGE = 50;
const snap = await snapshot();
const [summary, boundaries, stats] = await Promise.all([snap.summary(), snap.boundaries(), snap.stats()]);
showDevBanner(summary);
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
  history.replaceState(null, '', p.toString() ? `?${p}` : location.pathname);
}

// Map.
const map = drawMap($('#map'), boundaries, {
  label: 'Map of India: quiet species in each district. Select a district to filter the table.',
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
    `${fmt(v)} of ${fmt(stats.districts[id].s[gi])} species quiet since ${st.since}`);
  $('#legend').innerHTML = legendHTML(breaks, `Quiet species since ${st.since}`);
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

const KEYS = { name: r => r.name, gi: r => groups[r.gi], family: r => r.family, first: r => r.first ?? 9999, last: r => r.last ?? 9999, n: r => r.n };

function filter() {
  const q = st.q.toLowerCase();
  const allMode = st.all && st.district != null;
  view = rows.filter(r => (allMode || (r.last != null && r.last < st.since))
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
  const src = st.district != null ? stats.districts[st.district] : st.state != null ? stats.states[st.state] : null;
  const total = src ? src.s[gi] : (st.group < 0 ? summary.species : summary.group_species[st.group]);
  const quiet = rows.filter(r => r.last != null && r.last < st.since && (st.group < 0 || r.gi === st.group));
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
    </dl>
    ${top.length && st.group < 0 ? `<div style="border-top:1px solid var(--line-2);margin-top:16px;padding-top:14px">
      <div style="font-size:13px;font-weight:600;color:var(--ink-2);margin-bottom:8px">Quiet species by group</div>
      <div class="gbars">${top.map(([g, c]) => `<div><span>${esc(groups[g])}</span><span class="bar"><i style="width:${(100 * c / max).toFixed(1)}%"></i></span><span>${fmt(c)}</span></div>`).join('')}</div>
    </div>` : ''}
    ${st.district != null || st.state != null ? '<button class="b" type="button" id="clear" style="margin-top:16px">Back to all of India</button>' : ''}`;
  const c = $('#clear');
  if (c) c.addEventListener('click', () => { st.district = null; st.state = null; update(); });
}

function renderTable() {
  const allMode = st.all && st.district != null;
  $('#count').innerHTML = allMode
    ? `${fmt(view.length)} species in ${esc(areaLabel())}`
    : `${fmt(view.length)} species with no public record since ${st.since} in ${esc(areaLabel())}`;
  $('#scope').textContent = st.district == null
    ? 'Select a district to see every species recorded there, not only quiet ones.'
    : '';
  const pages = Math.max(1, Math.ceil(view.length / PAGE));
  st.page = Math.min(st.page, pages - 1);
  const slice = view.slice(st.page * PAGE, st.page * PAGE + PAGE);
  $('#rows').innerHTML = slice.length ? slice.map(r => `<tr>
      <td class="sp"><a href="https://www.gbif.org/species/${r.key}">${esc(r.name)}</a></td>
      <td>${esc(groups[r.gi])}</td>
      <td class="muted">${esc(r.family)}</td>
      <td class="n"><span class="yr">${r.first ?? '<span class="muted">unknown</span>'}</span></td>
      <td class="n"><span class="yr${r.last != null && r.last < st.since ? ' q' : ''}">${r.last ?? '<span class="muted">unknown</span>'}</span></td>
      <td class="n mono">${fmt(r.n)}</td></tr>`).join('')
    : `<tr><td colspan="6" class="muted" style="padding:28px 14px">No species match these filters.</td></tr>`;
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
