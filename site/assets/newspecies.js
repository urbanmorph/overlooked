import { getJSON, fmt, esc, $, monthName, showLoadError } from './common.js';

const STATUS = { recorded: 'Recorded again', later_papers: 'Only in later papers', none: 'No public record since' };
const CLS = { recorded: 'st-ok', later_papers: 'st-paper', none: 'st-none' };
const PAGE = 50;
const LOOKUP = ['sources', 'journal', 'state', 'group', 'matched_by', 'status'];

// Rows from the file. Version 2 is columnar with lookup tables (pipeline/layer_newspecies.py compact);
// a file without a version is the older list of row objects.
function expand(doc) {
  if (!doc.version) return doc.species;
  const { lookups: lk, columns: c } = doc;
  const fields = Object.keys(c).filter(f => f !== 'link_rest');
  return Array.from({ length: doc.n }, (_, i) => {
    const r = {};
    for (const f of fields) r[f] = LOOKUP.includes(f) ? lk[f][c[f][i]] : c[f][i];
    r.link = lk.link[c.link[i]] + c.link_rest[i];
    r.any_record = !!r.any_record;
    return r;
  });
}

try {
  const layer = await getJSON('layers/newspecies/latest.json').catch(() => null);
  if (!layer) {
    $('#body').hidden = true; $('#pending').hidden = false;
  } else {
    const data = await getJSON(layer.file);
    $('#body').removeAttribute('aria-busy');
    const rows = expand(data);
    const n = rows.length, cnt = s => rows.filter(r => r.status === s).length;
    const pct = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : '–');
    const k = document.querySelectorAll('#kpis b');
    k[0].textContent = fmt(n); k[1].textContent = pct(cnt('none'), n); k[2].textContent = fmt(cnt('recorded')); k[3].textContent = pct(rows.filter(r => r.any_record).length, n);
    $('#runline').textContent = `Module 03 · built ${monthName(data.built)} · GBIF snapshot ${data.snapshot || ''}`;

    // Stacked bars by group (groups with 20 or more new species).
    const groups = new Map();
    for (const r of rows) { const g = groups.get(r.group) || { recorded: 0, later_papers: 0, none: 0, n: 0 }; g[r.status]++; g.n++; groups.set(r.group, g); }
    const big = [...groups].filter(([, g]) => g.n >= 20).sort((a, b) => b[1].none / b[1].n - a[1].none / a[1].n);
    $('#sbars').innerHTML = big.map(([name, g]) => `<div><span>${esc(name)}</span>
      <span class="stackbar" title="${fmt(g.n)} species"><i style="width:${(100 * g.recorded / g.n).toFixed(1)}%;background:var(--accent)"></i><i style="width:${(100 * g.later_papers / g.n).toFixed(1)}%;background:#8FB9AE"></i><i style="width:${(100 * g.none / g.n).toFixed(1)}%;background:var(--q2)"></i></span>
      <span class="mono">${pct(g.none, g.n)} · ${fmt(g.n)}</span></div>`).join('');

    // By year described.
    const years = [...new Set(rows.map(r => r.year))].sort();
    const yb = years.map(y => { const ys = rows.filter(r => r.year === y); return [y, ys.length, ys.filter(r => r.status === 'none').length]; });
    $('#ybars').innerHTML = yb.map(([y, t, none]) => `<div><span class="mono">${y}</span><span class="bar"><i style="width:${(100 * none / t).toFixed(1)}%"></i></span><span>${pct(none, t)}</span></div>`).join('');

    // Table.
    const fG = $('#f-group'), fS = $('#f-status'), fY = $('#f-year'), fQ = $('#f-q');
    fG.insertAdjacentHTML('beforeend', [...groups.keys()].sort().map(g => `<option>${esc(g)}</option>`).join(''));
    fY.insertAdjacentHTML('beforeend', years.map(y => `<option>${y}</option>`).join(''));
    let page = 0, view = rows;
    function render() {
      const q = fQ.value.trim().toLowerCase();
      view = rows.filter(r => (!fG.value || r.group === fG.value) && (!fS.value || r.status === fS.value)
        && (!fY.value || String(r.year) === fY.value) && (!q || r.name.toLowerCase().includes(q)));
      const slice = view.slice(page * PAGE, page * PAGE + PAGE);
      $('#rows').innerHTML = slice.map(r => `<tr>
        <td class="sp">${r.key ? `<a href="/species?key=${encodeURIComponent(r.key)}">${esc(r.name)}</a>` : `<i>${esc(r.name)}</i>`}</td>
        <td>${esc(r.group)}</td><td class="n mono">${r.year}</td>
        <td><a href="${esc(r.link)}">${esc(r.sources.join(', '))}</a>${r.journal ? `<br><span class="note">${esc(r.journal)}</span>` : ''}</td>
        <td>${esc(r.state || '')}</td>
        <td><span class="badge ${CLS[r.status]}">${STATUS[r.status]}${r.status === 'recorded' && r.latest_after ? ' (' + r.latest_after + ')' : ''}</span></td>
        <td class="note" style="margin:0">${esc(r.matched_by)}</td></tr>`).join('') || '<tr><td colspan="7" class="muted" style="padding:24px 14px">There are no species for these filters.</td></tr>';
      $('#pinfo').textContent = view.length ? `Showing ${fmt(page * PAGE + 1)} to ${fmt(page * PAGE + slice.length)} of ${fmt(view.length)}` : '';
      $('#prev').disabled = page === 0; $('#next').disabled = (page + 1) * PAGE >= view.length;
    }
    for (const el of [fG, fS, fY]) el.addEventListener('change', () => { page = 0; render(); });
    let t; fQ.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { page = 0; render(); }, 150); });
    $('#prev').addEventListener('click', () => { page--; render(); });
    $('#next').addEventListener('click', () => { page++; render(); });
    render();
    $('#source').innerHTML = `Names: Plazi TreatmentBank (CC0); Botanical Survey of India, Plant Discoveries ${years[0]} to ${years[years.length - 1]}, Ministry of Environment, Forest and Climate Change, Government of India (reproduced with acknowledgement). Records: GBIF.org (${esc(monthName(data.downloads[0].created))}), ${data.downloads.map(d => `<a class="mono" href="https://doi.org/${esc(d.doi)}">doi:${esc(d.doi)}</a>`).join(', ')}.`;
  }
} catch (err) {
  showLoadError(err);
}
