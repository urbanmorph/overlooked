// One species: what the master list knows (sources, observed, identified, IUCN, labels, year described,
// waiting observations),
// where it is observed and identified, and its GBIF records when the snapshot has them.

import { snapshot, getJSON, fmt, esc, $, showDevBanner, sourceLine, showLoadError } from './common.js';
import { drawMap } from './map.js';
import { gbifKeyOf, gbifIndiaLinks } from './links.js';

// Same hash as pipeline/site_data.py shard_of: FNV-1a 32-bit of the UTF-8 key, modulo 512.
function shardOf(key) {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(String(key))) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
  return h % 512;
}
const STATUS = ['Listed only', 'Observed, not identified', 'Identified'];
const STATUS_TEXT = [
  'A source lists this species for India. No observation of it is in the sources yet.',
  'Someone observed it in India, but nobody has confirmed the name yet.',
  'Someone observed it in India and the name is confirmed.',
];
const IDENTIFY = 'https://www.inaturalist.org/observations/identify';
const AFTER = { recorded: y => `Recorded again after ${y}`, later_papers: y => `After ${y}, only in papers`,
  none: y => `No GBIF record after ${y}` };
const BASIS = [
  ['PRESERVED_SPECIMEN', 'Specimen'], ['MATERIAL_SAMPLE', 'Specimen'], ['MATERIAL_CITATION', 'From a paper'],
  ['HUMAN_OBSERVATION', 'Observation'], ['MACHINE_OBSERVATION', 'Observation'], ['OBSERVATION', 'Observation'], ['OCCURRENCE', 'Other'],
];
const KIND = Object.fromEntries(BASIS);
const KIND_ORDER = [['Specimen', '#16201C'], ['From a paper', '#8A9690'], ['Observation', '#2F5DA8'], ['Other', '#C5CCC7']];
const bit = (mask, i) => Math.floor(mask / 2 ** i) % 2 === 1;   // masks can pass 32 bits

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

// GBIF records by decade, stacked by kind of record.
function history(s) {
  const decades = new Map();
  for (const [dec, basis, n] of s.decades) {
    if (dec == null) continue;
    const k = KIND[basis] || 'Other';
    const m = decades.get(dec) || {}; m[k] = (m[k] || 0) + n; decades.set(dec, m);
  }
  if (!decades.size) return;
  const lo = Math.min(...decades.keys()), hi = Math.max(...decades.keys(), 2020);
  const cols = []; for (let d = lo; d <= hi; d += 10) cols.push(d);
  const tot = d => Object.values(decades.get(d) || {}).reduce((a, b) => a + b, 0);
  const max = Math.max(...cols.map(tot), 1);
  $('#hist').innerHTML = cols.map(d => {
    const m = decades.get(d) || {};
    const segs = KIND_ORDER.filter(([l]) => m[l]).map(([l, c]) => `<i style="height:${(100 * m[l] / max).toFixed(2)}%;background:${c}" title="${d}s: ${fmt(m[l])} ${l.toLowerCase()}"></i>`).join('');
    return `<div class="col"><div class="stack">${segs}</div><span class="mono">${d}</span></div>`;
  }).join('');
  const hist = $('#hist');
  thinLabels(hist);
  new ResizeObserver(() => thinLabels(hist)).observe(hist);
  $('#hlegend').innerHTML = KIND_ORDER.map(([l, c]) => `<span class="lbl"><i class="sw" style="background:${c};border:0"></i>${l}</span>`).join('');
  $('#histnote').textContent = `${lo}s to ${hi}s. Each bar is one decade, on one scale; the tallest has ${fmt(max)} records.`;
  $('#gbif-hist').hidden = false;
}

try {
  const key = new URLSearchParams(location.search).get('key');
  if (!key) throw new Error('no species key in the address');
  const latest = await getJSON('layers/master/latest.json');
  const snap = await snapshot();
  const [S, part, snapSummary, boundaries, gbif] = await Promise.all([
    getJSON(latest.base + 'summary.json'), getJSON(`${latest.base}sp/${shardOf(key)}.json`),
    snap.summary(), snap.boundaries(), getJSON(snap.file(`species/${shardOf(key)}.json`)).then(p => p[key]).catch(() => null)]);
  showDevBanner(snapSummary);
  const row = part[key];
  if (!row) throw new Error('species not on the master list');
  const [name, gi, sources, status, iucn, labels, obsMask, idMask, taxon, waitIndia, waitStates, year, authority, paper] = row;
  const group = S.groups[gi] || '';
  const states = S.states.map((st, i) => ({ ...st, i, obs: bit(obsMask, i), id: bit(idMask, i), wait: (waitStates.find(x => x[0] === i) || [0, 0])[1] }));
  document.title = `${name} · Overlooked`;
  $('#name').textContent = name;
  $('#crumb').textContent = `/ ${group}${gbif?.family ? ` / ${gbif.family}` : ''}`;
  $('#classif').textContent = gbif ? [gbif.kingdom, gbif.phylum, gbif.class, gbif.order, gbif.family].filter(Boolean).join(' › ') : group;

  // Status, IUCN, sources, labels and what waits for a name.
  const nId = states.filter(s => s.id).length, nObs = states.filter(s => s.obs).length;
  const cat = S.iucn[iucn];
  const tags = (mask, names) => names.map((n, i) => (bit(mask, i) ? `<span class="tag">${esc(n)}</span>` : '')).filter(Boolean).join('') || '<span class="muted">–</span>';
  const identify = place => `${IDENTIFY}?quality_grade=needs_id&taxon_id=${encodeURIComponent(taxon)}&place_id=${encodeURIComponent(place)}`;
  $('#status').innerHTML = `<div class="muted crumb">In India</div>
    <p class="sp-big">${STATUS[status]}</p><p class="note" style="margin:4px 0 12px">${STATUS_TEXT[status]}</p>
    <dl class="stats">
      <dt>Described</dt><dd>${year ? `<a href="/?described=${year}-${year}">${year}</a>` : '<span class="muted">Year not known</span>'}${authority ? ` <span class="muted">· ${esc(authority)}</span>` : ''}</dd>
      <dt>IUCN Red List</dt><dd><span class="iucn i-${esc(cat)}">${esc(cat === 'NE' ? 'Not assessed' : cat)}</span></dd>
      <dt>Identified in</dt><dd>${fmt(nId)} state${nId === 1 ? '' : 's'}</dd>
      <dt>Observed in</dt><dd>${fmt(nObs)} state${nObs === 1 ? '' : 's'}</dd>
    </dl>
    ${paper ? `<p class="note" style="margin:12px 0 0">${paper[5] === year ? 'Description' : `Listed in ${paper[5]}`}: <a href="${esc(paper[2])}">${esc(paper[0].join(', '))}</a>${paper[1] ? ` (${esc(paper[1])})` : ''}.
      ${AFTER[paper[3]] ? `${esc(AFTER[paper[3]](paper[5]))}${paper[3] === 'recorded' && paper[4] ? ` (latest ${paper[4]})` : ''}.` : ''}</p>` : ''}
    <div class="note" style="margin:12px 0 4px">Sources</div><div>${tags(sources, S.sources)}</div>
    <div class="note" style="margin:12px 0 4px">Labels</div><div>${tags(labels, S.labels.map(l => l.name))}</div>
    ${waitIndia ? `<p class="sp-wait"><b class="mono">${fmt(waitIndia)}</b> observation${waitIndia === 1 ? '' : 's'} on iNaturalist wait for a name.
      <a class="idlink" href="${identify(S.waiting.places.india)}" target="_blank" rel="noopener">Identify on iNaturalist</a></p>` : ''}`;

  // Map: each state shaded by what is known there.
  const byState = new Map(states.map(s => [Number(s.code), s]));
  const map = drawMap($('#map'), boundaries, {
    label: `Map of India: where ${name} is observed and identified`, pickLabel: 'Explore this state',
    onPick: d => { location.href = `/?state=${d.state_lgd}`; },
  });
  map.fill(new Map(boundaries.districts.map(d => [d.id, byState.get(d.state_lgd)])),
    s => (s?.id ? '--q3' : s?.obs ? '--q1' : '--none'),
    (id, s) => (s ? `${s.id ? 'Identified' : s.obs ? 'Observed, not identified' : 'No observation'} in the state${s.wait ? `; ${fmt(s.wait)} wait for a name` : ''}` : 'No data'));
  const names = list => list.map(s => esc(s.name)).join(', ');
  const waitList = states.filter(s => s.wait).sort((a, b) => b.wait - a.wait).slice(0, 8);
  $('#where').innerHTML = (nId ? `Identified in ${names(states.filter(s => s.id))}.` : nObs ? 'Not identified in any state yet.' : 'No observation with a state yet.')
    + (nObs > nId ? ` Observed but not identified in ${names(states.filter(s => s.obs && !s.id))}.` : '')
    + (waitList.length && taxon ? `<br><span class="note">Waiting for a name: ${waitList.map(s => `<a href="${identify(S.waiting.places[s.code] ?? S.waiting.places.india)}" target="_blank" rel="noopener">${esc(s.name)} (${fmt(s.wait)})</a>`).join(', ')}</span>` : '');

  // GBIF records, when the snapshot has the species.
  if (gbif) {
    history(gbif);
    const dist = new Map(boundaries.districts.map(d => [d.id, d]));
    $('#dh').textContent = `Districts with GBIF records (${fmt(gbif.districts.length)})`;
    $('#districts').innerHTML = gbif.districts.map(([id, f, l, n]) => {
      const d = dist.get(id);
      return `<tr><td>${esc(d ? d.name : id)}</td><td>${d ? `<a href="/?state=${d.state_lgd}">${esc(d.state)}</a>` : ''}</td>
        <td class="n mono">${f ?? 'unknown'}</td><td class="n mono">${l ?? 'unknown'}</td><td class="n mono">${fmt(n)}</td></tr>`;
    }).join('');
    $('#gbif-districts').hidden = false;
  }

  const q = encodeURIComponent(name);
  $('#links').innerHTML = [
    `<a href="https://www.catalogueoflife.org/data/taxon/${encodeURIComponent(key)}">Catalogue of Life</a>`,
    `<span id="gbif-links"><a href="https://www.gbif.org/species/search?q=${q}">GBIF: search this name</a></span>`,
    taxon ? `<a href="https://www.inaturalist.org/taxa/${encodeURIComponent(taxon)}">iNaturalist</a>` : `<a href="https://www.inaturalist.org/taxa/search?q=${q}">iNaturalist: search this name</a>`,
    `<a href="https://www.iucnredlist.org/search?query=${q}">IUCN Red List</a>`,
    `<a href="https://indiabiodiversity.org/species/list?query=${q}">India Biodiversity Portal</a>`,
  ].map(x => `<li>${x}</li>`).join('');
  // GBIF's own key gives direct links to the records from India. If GBIF does not answer, the name search stays.
  const lm = S.labels.findIndex(l => l.code === 'lm');
  fetch(`https://api.gbif.org/v1/species/match?strict=true&name=${q}`).then(r => (r.ok ? r.json() : null)).then(m => {
    const links = gbifIndiaLinks(gbifKeyOf(m), lm >= 0 && bit(labels, lm));
    if (links.length) $('#gbif-links').innerHTML = links.map(l => `<a href="${esc(l.href)}">${esc(l.text)}</a>`).join('<br>');
  }).catch(() => {});
  $('#source').innerHTML = `${esc(S.disclaimer || '')} ${sourceLine(snapSummary)}`;
} catch (err) {
  showLoadError(err);
}
