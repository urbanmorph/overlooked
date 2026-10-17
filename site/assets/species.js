import { snapshot, getJSON, fmt, esc, $, showDevBanner, sourceLine, showLoadError } from './common.js';

// Same hash as pipeline/site_data.py shard_of: FNV-1a 32-bit of the UTF-8 key, modulo 512.
function shardOf(key) {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(String(key))) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
  return h % 512;
}
const BASIS = [
  ['PRESERVED_SPECIMEN', 'Specimen', '#16201C'], ['MATERIAL_SAMPLE', 'Specimen', '#16201C'],
  ['MATERIAL_CITATION', 'From a paper', '#8A9690'], ['HUMAN_OBSERVATION', 'Observation', '#2F5DA8'],
  ['MACHINE_OBSERVATION', 'Observation', '#2F5DA8'], ['OBSERVATION', 'Observation', '#2F5DA8'], ['OCCURRENCE', 'Other', '#C5CCC7'],
];
const KIND = Object.fromEntries(BASIS.map(([b, l, c]) => [b, { l, c }]));
const QUALITY = { research: 'research grade', needs_id: 'waits for a name', casual: 'casual' };

// Show every Nth decade label, counted back from the latest, so that labels never overlap at the measured column width.
function thinLabels(box) {
  const cols = box.querySelectorAll('.col');
  if (cols.length < 2) return;
  const spans = [...box.querySelectorAll('.col span')];
  const pitch = cols[1].offsetLeft - cols[0].offsetLeft;
  const widest = Math.max(...spans.map(s => s.offsetWidth)) + 8;
  const step = Math.max(1, Math.ceil(widest / pitch));
  spans.forEach((s, i) => { s.style.visibility = (spans.length - 1 - i) % step ? 'hidden' : ''; });
}

try {
  const key = new URLSearchParams(location.search).get('key');
  if (!key) throw new Error('no species key in the address');
  const snap = await snapshot();
  const [summary, boundaries, part] = await Promise.all([snap.summary(), snap.boundaries(), getJSON(snap.file(`species/${shardOf(key)}.json`))]);
  showDevBanner(summary);
  const s = part[key];
  if (!s) throw new Error('species not in this snapshot');
  const dist = new Map(boundaries.districts.map(d => [d.id, d]));
  const group = summary.groups[s.gi] || '';
  document.title = `${s.name} · Overlooked`;
  $('#name').textContent = s.name;
  $('#crumb').textContent = `/ ${group} / ${s.family || ''}`;
  $('#classif').textContent = [s.kingdom, s.phylum, s.class, s.order, s.family].filter(Boolean).join(' › ');
  $('#tags').innerHTML = `<span class="tag2">${esc(group)}</span>`;

  // Latest record in India.
  const last = s.districts.reduce((m, d) => (d[2] != null && (m == null || d[2] > m[2]) ? d : m), null);
  const first = Math.min(...s.districts.map(d => d[1] ?? 9999));
  const records = s.districts.reduce((a, d) => a + d[3], 0);
  const ld = last ? dist.get(last[0]) : null;
  $('#latest').innerHTML = `<div class="note" style="margin:0">Latest public record in India</div>
    <div class="mono" style="font-size:44px;font-weight:500;line-height:1.1;color:${last && last[2] < 1980 ? 'var(--quiet)' : 'var(--ink)'}">${last ? last[2] : 'unknown'}</div>
    <div style="margin-top:6px">${ld ? `${esc(ld.name)}, ${esc(ld.state)}` : ''}</div>
    <dl class="stats" style="margin-top:14px"><dt>First public record</dt><dd>${first < 9999 ? first : 'unknown'}</dd>
    <dt>Public records in India</dt><dd>${fmt(records)}</dd><dt>Districts</dt><dd>${fmt(s.districts.length)}</dd></dl>
    <div id="inat"></div>`;

  // iNaturalist note, if the layer has one for this snapshot.
  getJSON('layers/inat/latest.json').then(l => l && l.quiet_flags ? getJSON(l.quiet_flags) : null).then(f => {
    const v = f && f.snapshot === summary.run_id ? f.species[key] : null;
    if (v) $('#inat').innerHTML = `<p class="tagi" style="margin-top:12px">iNaturalist: seen in India ${esc(v[0])} (${QUALITY[v[1]] || esc(v[1])}${v[2] ? '' : ', no open licence'}); ${fmt(v[3])} observations in India</p>`;
  }).catch(() => {});

  // History by decade, stacked by kind of record.
  const decades = new Map();
  for (const [dec, basis, n] of s.decades) {
    if (dec == null) continue;
    const k = (KIND[basis] || KIND.OCCURRENCE).l;
    const m = decades.get(dec) || {}; m[k] = (m[k] || 0) + n; decades.set(dec, m);
  }
  if (decades.size) {
    const lo = Math.min(...decades.keys()), hi = Math.max(...decades.keys(), 2020);
    const cols = []; for (let d = lo; d <= hi; d += 10) cols.push(d);
    const tot = d => Object.values(decades.get(d) || {}).reduce((a, b) => a + b, 0);
    const max = Math.max(...cols.map(tot), 1);
    const order = [['Specimen', '#16201C'], ['From a paper', '#8A9690'], ['Observation', '#2F5DA8'], ['Other', '#C5CCC7']];
    $('#hist').innerHTML = cols.map(d => {
      const m = decades.get(d) || {};
      const segs = order.filter(([l]) => m[l]).map(([l, c]) => `<i style="height:${(100 * m[l] / max).toFixed(2)}%;background:${c}" title="${d}s: ${fmt(m[l])} ${l.toLowerCase()}"></i>`).join('');
      return `<div class="col${d < 1980 ? ' old' : ''}"><div class="stack">${segs}</div><span class="mono">${d}</span></div>`;
    }).join('');
    const hist = $('#hist');
    thinLabels(hist);
    new ResizeObserver(() => thinLabels(hist)).observe(hist);
    $('#hlegend').innerHTML = order.map(([l, c]) => `<span class="lbl"><i class="sw" style="background:${c};border:0"></i>${l}</span>`).join('');
    $('#histnote').textContent = `${lo}s to ${hi}s. Each bar is one decade, on one scale; the tallest has ${fmt(max)} records. The shaded decades are before 1980.`;
  } else {
    $('#hist').innerHTML = '<p class="muted">No history by decade in this snapshot.</p>';
  }

  // Districts.
  $('#dh').textContent = `Districts with records (${fmt(s.districts.length)})`;
  $('#districts').innerHTML = s.districts.map(([id, f, l, n]) => {
    const d = dist.get(id);
    return `<tr><td><a href="/ledger?district=${id}">${esc(d ? d.name : id)}</a></td><td>${esc(d ? d.state : '')}</td>
      <td class="n mono">${f ?? 'unknown'}</td><td class="n"><span class="yr${l != null && l < 1980 ? ' q' : ''}">${l ?? 'unknown'}</span></td><td class="n mono">${fmt(n)}</td></tr>`;
  }).join('');

  const q = encodeURIComponent(s.name);
  $('#links').innerHTML = [
    summary.taxon_ids === 'gbif' ? `<a href="https://www.gbif.org/species/${encodeURIComponent(key)}">GBIF species page</a>` : `<a href="https://www.catalogueoflife.org/data/taxon/${encodeURIComponent(key)}">Catalogue of Life</a>`,
    `<a href="https://www.gbif.org/species/search?q=${q}">GBIF: search this name</a>`,
    `<a href="https://www.inaturalist.org/observations?place_id=6681&taxon_name=${q}">iNaturalist: observations in India</a>`,
    `<a href="https://indiabiodiversity.org/species/list?query=${q}">India Biodiversity Portal</a>`,
  ].map(x => `<li>${x}</li>`).join('');
  $('#source').innerHTML = `"No public record since 1980" means that GBIF has no record of the species in the area after 1980. It does not mean that the species is not there now. ${sourceLine(summary)}`;
} catch (err) {
  showLoadError(err);
}
