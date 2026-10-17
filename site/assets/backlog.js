import { snapshot, getJSON, fmt, esc, $, monthName, showDevBanner, sourceLine, showLoadError } from './common.js';
import { drawMap, legendHTML } from './map.js';

const NAMES = {
  Plantae: 'Plants', Insecta: 'Insects', Aves: 'Birds', Fungi: 'Fungi and lichens', Arachnida: 'Spiders and kin',
  Mollusca: 'Molluscs', Reptilia: 'Reptiles', Amphibia: 'Amphibians', Mammalia: 'Mammals',
  Actinopterygii: 'Ray-finned fishes', Animalia: 'Other animals', Chromista: 'Kelp, diatoms and kin',
  Protozoa: 'Protozoa', unknown: 'No name at all',
};
const INDIA = 6681;
const pct = (a, b) => (b ? `${((100 * a) / b).toFixed(0)}%` : '–');

try {
  const snap = await snapshot();
  const [summary, boundaries] = await Promise.all([snap.summary(), snap.boundaries()]);
  showDevBanner(summary);
  const layer = await getJSON('layers/inat/latest.json').catch(() => null);
  const bl = layer && layer.backlog ? await getJSON(layer.backlog) : null;
  const unres = await getJSON(snap.file('unresolved.json')).catch(() => null);
  const thisYear = String(new Date().getUTCFullYear());

  // Totals per place (sum over groups) and per group (India).
  const waiting = r => Object.values(r.needs_id_by_year).reduce((a, b) => a + b, 0);
  const older = r => Object.entries(r.needs_id_by_year).filter(([y]) => y < thisYear).reduce((a, [, v]) => a + v, 0);
  const byPlace = new Map(), india = [];
  for (const r of bl ? bl.backlog : []) {
    const key = String(r.place_id);
    const t = byPlace.get(key) || { w: 0, rg: 0, old: 0 };
    t.w += waiting(r); t.rg += r.research_grade; t.old += older(r);
    byPlace.set(key, t);
    if (r.place_id === INDIA) india.push(r);
  }
  const all = byPlace.get(String(INDIA)) || { w: 0, rg: 0, old: 0 };

  const k = document.querySelectorAll('#kpis b');
  k[0].textContent = bl ? fmt(all.w) : 'Later';
  k[1].textContent = bl ? pct(all.w, all.w + all.rg) : '–';
  k[2].textContent = bl ? pct(all.old, all.w) : '–';
  k[3].textContent = unres ? fmt(unres.india.n) : 'Next run';

  // Group table.
  const ids = new Map((bl ? bl.identifiers : []).map(x => [x.group, x]));
  $('#groups').innerHTML = india.sort((a, b) => waiting(b) - waiting(a)).map(r => {
    const w = waiting(r), idn = ids.get(r.group)?.identifiers_12m;
    return `<tr><td>${esc(NAMES[r.group] || r.group)}</td><td class="n mono">${fmt(w)}</td><td class="n mono">${fmt(r.research_grade)}</td>
      <td class="n mono">${pct(w, w + r.research_grade)}</td><td class="n mono">${pct(older(r), w)}</td>
      <td class="n mono">${idn == null ? '–' : fmt(idn)}</td><td class="n mono">${idn ? fmt(Math.round(w / idn)) : '–'}</td></tr>`;
  }).join('') || '<tr><td colspan="7" class="muted" style="padding:24px 14px">The iNaturalist counts are not available yet.</td></tr>';

  // Map: iNaturalist by state (each district shows its state), or GBIF by district.
  const placeOfState = new Map(Object.entries(bl ? bl.places : {}).map(([code, v]) => [+code, String(v.place_id)]));
  const map = drawMap($('#map'), boundaries, { label: 'Map of India: observations that wait for a name' });
  const sel = $('#layer');
  function paint() {
    const vals = new Map();
    if (sel.value === 'inat') {
      $('#maph').textContent = 'Waiting for a name, by state';
      $('#mapnote').textContent = 'iNaturalist observations that wait for a species name. Each district shows the total for its state.';
      for (const d of boundaries.districts) { const t = byPlace.get(placeOfState.get(d.state_lgd)); vals.set(d.id, t ? t.w : null); }
      const b = map.paint(vals, (id, v) => (v == null ? 'No data' : `${fmt(v)} observations in the state wait for a name`));
      $('#legend').innerHTML = legendHTML(b, 'Observations waiting (state)');
    } else {
      $('#maph').textContent = 'Records with no species name, by district';
      $('#mapnote').textContent = 'GBIF records named only to genus, family or higher. They count as records, but not as records of a species.';
      for (const d of boundaries.districts) { const u = unres?.districts[d.id]; vals.set(d.id, u ? u.n : null); }
      const b = map.paint(vals, (id, v) => (v == null ? 'No records' : `${fmt(v)} records with no species name`));
      $('#legend').innerHTML = legendHTML(b, 'Records with no species name');
    }
  }
  sel.addEventListener('change', paint);
  if (!unres) sel.querySelector('option[value=gbif]').disabled = true;
  paint();

  // Side panel: states with the most waiting.
  const states = [...placeOfState].map(([code, pid]) => ({ name: boundaries.districts.find(d => d.state_lgd === code)?.state, t: byPlace.get(pid) }))
    .filter(s => s.t).sort((a, b) => b.t.w - a.t.w).slice(0, 8);
  const max = states.length ? states[0].t.w : 1;
  $('#aside').innerHTML = `<h2 style="font-size:20px">Most waiting</h2>
    <p class="note">States with the most iNaturalist observations that wait for a name</p>
    <div class="gbars wide" style="margin-top:14px">${states.map(s => `<div><span>${esc(s.name)}</span><span class="bar"><i style="width:${(100 * s.t.w / max).toFixed(1)}%"></i></span><span>${fmt(s.t.w)}</span></div>`).join('') || '<p class="muted">Not available yet.</p>'}</div>`;

  $('#runline').textContent = `Module 05 · iNaturalist counts of ${bl ? esc(monthName(bl.as_of)) : 'a later date'} · GBIF snapshot ${summary.run_id}`;
  $('#source').innerHTML = `iNaturalist: counts from api.inaturalist.org${bl ? `, ${esc(monthName(bl.as_of))}` : ''}. Research-grade observations with an open licence also reach GBIF. ${sourceLine(summary)} The India Biodiversity Portal also holds observations without a name; its data is not available to automated tools.`;
} catch (err) {
  showLoadError(err);
}
