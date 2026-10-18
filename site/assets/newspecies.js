// New species: described from India since the layer's first year. Seen again after the description (from the
// new-species layer), and identified, IUCN status and observations waiting for a name (from the master list).

import { getJSON, fmt, esc, $, monthName, showLoadError } from './common.js';

const AFTER = { recorded: 'Observed again', later_papers: 'Only in later papers', none: 'Not observed since' };
const CLS = { recorded: 'st-ok', later_papers: 'st-paper', none: 'st-none' };
const NAME = ['Listed only', 'Observed, not identified', 'Identified'];
const THREAT = new Set(['CR', 'EN', 'VU']);
const IDENTIFY = 'https://www.inaturalist.org/observations/identify';
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
    const master = await getJSON('layers/master/latest.json');
    const [data, S, ns] = await Promise.all([getJSON(layer.file), getJSON(master.base + 'summary.json'),
      getJSON(master.base + 'ns.json').catch(() => ({}))]);
    $('#body').removeAttribute('aria-busy');
    // ns.json: key -> [status, IUCN index, labels, states observed, states identified, waiting in India, taxon]
    const rows = expand(data).map(r => {
      const m = ns[r.key];
      return { ...r, name_status: m ? m[0] : null, iucn: m ? S.iucn[m[1]] : 'NE', wait: m ? m[5] : 0, taxon: m ? m[6] : null };
    });
    const pct = (a, b) => (b ? `${Math.round((100 * a) / b)}%` : '–');
    $('#runline').textContent = `New species · built ${monthName(data.built)} · GBIF snapshot ${data.snapshot || ''}`;

    // Years: the range drives every figure on the page.
    const years = [...new Set(rows.map(r => r.year))].sort();
    const fFrom = $('#f-from'), fTo = $('#f-to');
    fFrom.innerHTML = years.map(y => `<option${y === years[0] ? ' selected' : ''}>${y}</option>`).join('');
    fTo.innerHTML = years.map(y => `<option${y === years[years.length - 1] ? ' selected' : ''}>${y}</option>`).join('');
    const inYears = r => r.year >= +fFrom.value && r.year <= +fTo.value;

    function figures(sel) {
      const n = sel.length, k = document.querySelectorAll('#kpis b');
      const assessed = sel.filter(r => r.iucn !== 'NE'), threat = sel.filter(r => THREAT.has(r.iucn));
      k[0].textContent = fmt(n); k[1].textContent = pct(sel.filter(r => r.status === 'none').length, n);
      k[2].textContent = pct(sel.filter(r => r.name_status === 2).length, n); k[3].textContent = pct(assessed.length, n);
      $('#k0').textContent = `species described from India, ${fFrom.value} to ${fTo.value}`;
      $('#k3').textContent = `assessed by IUCN${threat.length ? `; ${fmt(threat.length)} threatened` : ''}`;
      // Stacked bars by group (groups with 20 or more new species in the range).
      const groups = new Map();
      for (const r of sel) { const g = groups.get(r.group) || { recorded: 0, later_papers: 0, none: 0, n: 0 }; g[r.status]++; g.n++; groups.set(r.group, g); }
      const big = [...groups].filter(([, g]) => g.n >= 20).sort((a, b) => b[1].none / b[1].n - a[1].none / a[1].n);
      $('#sbars').innerHTML = big.map(([name, g]) => `<div><span>${esc(name)}</span>
        <span class="stackbar" title="${fmt(g.n)} species"><i style="width:${(100 * g.recorded / g.n).toFixed(1)}%;background:var(--accent)"></i><i style="width:${(100 * g.later_papers / g.n).toFixed(1)}%;background:#8FB9AE"></i><i style="width:${(100 * g.none / g.n).toFixed(1)}%;background:var(--q2)"></i></span>
        <span class="mono">${pct(g.none, g.n)} · ${fmt(g.n)}</span></div>`).join('') || '<p class="muted">No group has 20 or more new species in these years.</p>';
      $('#ybars').innerHTML = years.filter(y => y >= +fFrom.value && y <= +fTo.value).map(y => {
        const ys = sel.filter(r => r.year === y), none = ys.filter(r => r.status === 'none').length;
        return `<div><span class="mono">${y}</span><span class="bar"><i style="width:${(100 * none / (ys.length || 1)).toFixed(1)}%"></i></span><span>${pct(none, ys.length)}</span></div>`;
      }).join('');
    }

    // Table.
    const fG = $('#f-group'), fS = $('#f-status'), fI = $('#f-id'), fU = $('#f-iucn'), fQ = $('#f-q');
    fG.insertAdjacentHTML('beforeend', [...new Set(rows.map(r => r.group))].sort().map(g => `<option>${esc(g)}</option>`).join(''));
    const iucnOk = r => !fU.value || (fU.value === 'threat' ? THREAT.has(r.iucn) : fU.value === 'assessed' ? r.iucn !== 'NE' : r.iucn === 'NE');
    let page = 0;
    function render() {
      const sel = rows.filter(inYears);
      figures(sel);
      const q = fQ.value.trim().toLowerCase();
      const view = sel.filter(r => (!fG.value || r.group === fG.value) && (!fS.value || r.status === fS.value)
        && (fI.value === '' || r.name_status === +fI.value) && iucnOk(r) && (!q || r.name.toLowerCase().includes(q)));
      const slice = view.slice(page * PAGE, page * PAGE + PAGE);
      $('#rows').innerHTML = slice.map(r => `<tr>
        <td class="sp">${r.key ? `<a href="/species?key=${encodeURIComponent(r.key)}">${esc(r.name)}</a>` : `<i>${esc(r.name)}</i>`}</td>
        <td>${esc(r.group)}</td><td class="n mono">${r.year}</td>
        <td><a href="${esc(r.link)}">${esc(r.sources.join(', '))}</a>${r.journal ? `<br><span class="note">${esc(r.journal)}</span>` : ''}</td>
        <td>${esc(r.state || '')}</td>
        <td><span class="badge ${CLS[r.status]}" title="Found by: ${esc(r.matched_by)}">${AFTER[r.status]}${r.status === 'recorded' && r.latest_after ? ` (${r.latest_after})` : ''}</span></td>
        <td>${r.name_status == null ? '<span class="muted">–</span>' : NAME[r.name_status]}</td>
        <td><span class="iucn i-${esc(r.iucn)}">${esc(r.iucn === 'NE' ? 'Not assessed' : r.iucn)}</span></td>
        <td>${r.wait && r.taxon ? `<a class="idlink" href="${IDENTIFY}?quality_grade=needs_id&taxon_id=${encodeURIComponent(r.taxon)}&place_id=${encodeURIComponent(S.waiting.places.india)}" target="_blank" rel="noopener">${fmt(r.wait)} to identify</a>` : ''}</td></tr>`).join('')
        || '<tr><td colspan="9" class="muted" style="padding:24px 14px">There are no species for these filters.</td></tr>';
      $('#pinfo').textContent = view.length ? `Showing ${fmt(page * PAGE + 1)} to ${fmt(page * PAGE + slice.length)} of ${fmt(view.length)}` : '';
      $('#prev').disabled = page === 0; $('#next').disabled = (page + 1) * PAGE >= view.length;
    }
    for (const el of [fFrom, fTo, fG, fS, fI, fU]) el.addEventListener('change', () => {
      if (+fFrom.value > +fTo.value) (el === fFrom ? fTo : fFrom).value = el.value;
      page = 0; render();
    });
    let t; fQ.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => { page = 0; render(); }, 150); });
    $('#prev').addEventListener('click', () => { page--; render(); });
    $('#next').addEventListener('click', () => { page++; render(); });
    render();
    const src = [...new Set(rows.flatMap(r => r.sources))];
    $('#source').innerHTML = `Names: ${esc(src.join(', '))}. Plazi is CC0; BSI and ZSI material is reproduced with acknowledgement (Ministry of Environment, Forest and Climate Change, Government of India). Records: GBIF.org (${esc(monthName(data.downloads[0].created))}), ${data.downloads.map(d => `<a class="mono" href="https://doi.org/${esc(d.doi)}">doi:${esc(d.doi)}</a>`).join(', ')}. Identified and IUCN: the master list.`;
  }
} catch (err) {
  showLoadError(err);
}
