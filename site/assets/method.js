import { snapshot, getJSON, fmt, esc, $, monthName, showDevBanner, showLoadError } from './common.js';

const QUERY = {
  ledger_cube: 'Ledger: species at each place, first and latest year',
  species_history: 'Species names and history by decade',
  unresolved_cube: 'Records with no species name (genus or higher)',
  unlocated_cube: 'Records with no coordinates',
};
const SOURCE = {
  gbif_api: 'GBIF API', gbif_downloads: 'GBIF downloads', r2: 'Overlooked data store', lgd_boundaries: 'LGD boundaries (bharatlas)',
  plazi: 'Plazi', ipni: 'IPNI', index_fungorum: 'Index Fungorum', inaturalist: 'iNaturalist',
  ibp_gbif_dataset: 'India Biodiversity Portal (GBIF dataset)', kew_wcvp: 'Kew WCVP',
  bsi_plant_discoveries: 'BSI Plant Discoveries', bsi_ivh: 'BSI Indian Virtual Herbarium',
};

try {
  const snap = await snapshot();
  const [summary, manifest] = await Promise.all([snap.summary(), getJSON(snap.latest.manifest)]);
  showDevBanner(summary);
  $('#snaph').textContent = `This snapshot: ${manifest.run_id}`;
  $('#downloads').innerHTML = manifest.downloads.map(d => `<tr>
      <td>${esc(QUERY[d.query] || d.query)}</td>
      <td><a class="mono" href="https://doi.org/${esc(d.doi)}">doi:${esc(d.doi)}</a></td>
      <td>${esc(monthName(d.created))}</td><td class="n mono">${fmt(d.records)}</td></tr>`).join('');
  const b = manifest.boundaries || {};
  $('#snapmeta').innerHTML = `Built ${esc(monthName(manifest.built))}. Boundaries: ${esc(b.source || 'LGD via bharatlas')}, file checksum <span class="mono">${esc((b.sha256 || '').slice(0, 12))}</span>.
    Code: <a class="mono" href="https://github.com/urbanmorph/overlooked/commit/${esc(manifest.code_commit)}">${esc((manifest.code_commit || '').slice(0, 7))}</a>.
    Placement: ${esc(manifest.placement || '')}.`;

  const h = manifest.health ? manifest.health.sources : {};
  $('#health').innerHTML = Object.entries(h).map(([k, v]) => `<tr>
      <td>${esc(SOURCE[k] || k)}</td><td class="muted">${esc(v.used_for || '')}</td>
      <td>${v.ok ? '<span class="ok">Answered</span>' : `<span class="bad">${v.critical ? 'Failed: run stopped' : 'Failed: last data kept'}</span>`}</td>
      <td class="n mono">${v.ms != null ? fmt(v.ms) + ' ms' : '–'}</td></tr>`).join('')
    || '<tr><td colspan="4" class="muted">Not recorded for this snapshot.</td></tr>';

  const files = Object.entries(manifest.files || {});
  $('#files').innerHTML = files.map(([name, size]) =>
    `<li><a class="mono" href="/data/${esc(snap.latest.base + name)}" download>${esc(name)}</a> <span class="muted">${fmt(Math.round(size / 1024))} KB</span></li>`).join('')
    + `<li><a class="mono" href="/data/${esc(snap.latest.manifest)}">manifest.json</a> <span class="muted">what the snapshot is built from</span></li>`;
} catch (err) {
  showLoadError(err);
}
