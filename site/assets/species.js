// One species: what the master list knows (sources, open record, IUCN, labels, year described, waiting observations),
// the states with an open record and with observations that wait, and its GBIF records when the snapshot has them.

import { snapshot, getJSON, fmt, esc, $, bit, tags, showDevBanner, sourceLine, showLoadError } from './common.js?v=9455fd8cc8';
import { drawMap } from './map.js?v=b39659b5ac';
import { gbifKeyOf, gbifIndiaLinks, gbifNameSearch, nextSteps } from './links.js?v=5e428c2f50';
import { barcodeText, countText, localNames } from './evidence.js?v=2fcbd9aeae';
import { KINDS, VERBS, gapStates, layout, webSVG, whereFill } from './web.js?v=dd8b6274fa';

// Same hash as pipeline/site_data.py shard_of: FNV-1a 32-bit of the UTF-8 key, modulo 512.
function shardOf(key) {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(String(key))) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
  return h % 512;
}
const STATUS = ['No open record yet', 'Open record', 'Not on the India list yet'];
const STATUS_TEXT = [
  'A checklist or a paper lists this species for India. No open record of it is online yet: no specimen, photo or sighting that anyone can check.',
  'There is an open record of it from India: a specimen, photo or sighting that anyone can check online.',
  'Only iNaturalist observations that wait for a name give this species for India. When someone confirms the name, it goes on the list.',
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

// Type specimens, photos, DNA barcode and local names; nothing when this list does not measure them.
function evidenceRows(S, name, types, photos, barcode, names) {
  if (S.types == null) return '';
  const none = text => `<span class="muted">${text}</span>`;
  const t = countText(types, true, 'record'), p = countText(photos, true, 'record'), b = barcodeText(barcode);
  const local = localNames(names);
  return `<dt>Type specimen</dt><dd>${t ? `${t} from India with a type status <span class="muted">· GBIF</span>` : none('None from India on GBIF')}</dd>
      <dt>Photo</dt><dd>${p ? `${p} from India with a photo <span class="muted">· GBIF</span>` : none('None from India on GBIF')}</dd>
      <dt>DNA barcode</dt><dd>${b ? `${b} <span class="muted">· <a href="https://portal.boldsystems.org/result?query=${encodeURIComponent(name)}[tax]">BOLD</a></span>` : none('None on BOLD')}</dd>
      <dt>Local names</dt><dd>${local.length ? local.map(l => `${esc(l.names.join(', '))} <span class="muted">(${esc(l.lang)})</span>`).join('; ')
        : none('None in Wikidata yet')}</dd>`;
}

try {
  const key = new URLSearchParams(location.search).get('key');
  if (!key) throw new Error('no species key in the address');
  const latest = await getJSON('layers/master/latest.json');
  const snap = await snapshot();
  const [S, part, snapSummary, boundaries, gbif, web] = await Promise.all([
    getJSON(latest.base + 'summary.json'), getJSON(`${latest.base}sp/${shardOf(key)}.json`),
    snap.summary(), snap.boundaries(), getJSON(snap.file(`species/${shardOf(key)}.json`)).then(p => p[key]).catch(() => null),
    getJSON(`${latest.base}web/${shardOf(key)}.json`).then(p => p[key] || null).catch(() => undefined)]);   // undefined: a list with no web yet
  showDevBanner(snapSummary);
  const row = part[key];
  if (!row) throw new Error('species not on the master list');
  const [name, gi, sources, status, iucn, labels, obsMask, taxon, waitIndia, waitStates, year, authority, paper, iucnYear, iucnDoi,
    partners, interactionsIndia, cells, types, photos, barcode, localPairs, trend, traits, precise] = row;
  const group = S.groups[gi] || '';
  const states = S.states.map((st, i) => ({ ...st, i, obs: bit(obsMask, i), wait: (waitStates.find(x => x[0] === i) || [0, 0])[1] }));
  document.title = `${name} · Overlooked`;
  $('#name').textContent = name;
  $('#crumb').textContent = `/ ${group}${gbif?.family ? ` / ${gbif.family}` : ''}`;
  $('#classif').textContent = gbif ? [gbif.kingdom, gbif.phylum, gbif.class, gbif.order, gbif.family].filter(Boolean).join(' › ') : group;

  // Status, IUCN, sources, labels and what waits for a name.
  const nObs = states.filter(s => s.obs).length;
  const cat = S.iucn[iucn];
  const chips = (mask, names) => tags(mask, names) || '<span class="muted">–</span>';
  const identify = place => `${IDENTIFY}?quality_grade=needs_id&taxon_id=${encodeURIComponent(taxon)}&place_id=${encodeURIComponent(place)}`;
  $('#status').innerHTML = `<div class="muted crumb">In India</div>
    <p class="sp-big">${STATUS[status]}</p><p class="note" style="margin:4px 0 12px">${STATUS_TEXT[status]}</p>
    <dl class="stats">
      <dt>Described</dt><dd>${year ? `<a href="/?described=${year}-${year}">${year}</a>` : '<span class="muted">Year not known</span>'}${authority ? ` <span class="muted">· ${esc(authority)}</span>` : ''}</dd>
      <dt>Interactions</dt><dd>${partners == null ? '<span class="muted">None recorded</span>'
        : `${fmt(partners)} partner species${interactionsIndia ? ', some recorded in India' : ', none recorded in India'}`}
        <span class="muted">· <a href="https://www.globalbioticinteractions.org/?interactionType=interactsWith&amp;sourceTaxon=${encodeURIComponent(name)}">GloBI</a></span></dd>
      <dt>Area of occupancy</dt><dd>${cells == null ? '<span class="muted">Not counted yet</span>'
        : `${fmt(4 * cells)} km² <span class="muted">· ${fmt(cells)} ${cells === 1 ? 'cell' : 'cells'} of 2 × 2 km with an open record placed in India</span>`}</dd>
${evidenceRows(S, name, types, photos, barcode, localPairs)}
      <dt>IUCN Red List</dt><dd><span class="iucn i-${esc(cat)}">${esc(cat === 'NE' ? 'Not assessed' : cat)}</span>${iucnYear
        ? ` <span class="muted">· assessed in ${iucnYear}${iucnDoi ? ` (<a href="${esc(iucnDoi)}">the assessment</a>)` : ''}</span>` : ''}</dd>
      <dt>Open record in</dt><dd>${fmt(nObs)} state${nObs === 1 ? '' : 's'}</dd>
    </dl>
    ${paper ? `<p class="note" style="margin:12px 0 0">${paper[5] === year ? 'Description' : `Listed in ${paper[5]}`}: <a href="${esc(paper[2])}">${esc(paper[0].join(', '))}</a>${paper[1] ? ` (${esc(paper[1])})` : ''}.
      ${AFTER[paper[3]] ? `${esc(AFTER[paper[3]](paper[5]))}${paper[3] === 'recorded' && paper[4] ? ` (latest ${paper[4]})` : ''}.` : ''}</p>` : ''}
    <div class="note" style="margin:12px 0 4px">Sources</div><div>${chips(sources, S.sources)}</div>
    <div class="note" style="margin:12px 0 4px">Labels</div><div>${chips(labels, S.labels.map(l => l.name))}</div>
    <div class="sp-wait" id="next"></div>`;
  // Next step: what a person can do for this species, and where. GBIF links fill in when GBIF gives its key.
  const codes = new Set(S.labels.filter((l, i) => bit(labels, i)).map(l => l.code));
  const showNext = gbifKey => {
    const steps = nextSteps({ status, iucn: cat, codes, wait: waitIndia, identify: taxon ? identify(S.waiting.places.india) : null,
      gbifKey, name, paper: paper?.[2] });
    $('#next').hidden = !steps.length;
    $('#next').innerHTML = `<div class="note" style="margin:0 0 4px">Next step</div><ol class="next-steps">${steps.map(s => `<li>${esc(s.text)}${s.links.length ? `<br>${s.links.map(l =>
      `<a class="idlink" href="${esc(l.href)}" target="_blank" rel="noopener">${esc(l.text)}</a>`).join(' · ')}` : ''}</li>`).join('')}</ol>`;
  };
  showNext(null);

  // The web: partners around the seven gaps; a partner picked shows its details beside it.
  const latestYear = gbif?.districts?.length ? Math.max(...gbif.districts.map(d => d[2] ?? 0)) || null : null;
  const gaps = gapStates({ year, latest: latestYear, trend, dna: codes.has('dna'), barcode, traits, precise, partners,
    interactionsIndia }, S);
  const L = layout(web || { n: {}, p: {} });
  $('#web').innerHTML = webSVG(L, gaps, name);
  const kindOf = Object.fromEntries(KINDS.map(k => [k.k, k]));
  $('#weblegend').innerHTML = KINDS.filter(k => web?.n?.[k.k]).map(k => `<span class="lbl"><i class="sw" style="background:${k.color};border:0"></i>${k.label}</span>`).join('')
    + (web ? '<span class="lbl"><i class="sw" style="background:#fff;border:2px solid var(--muted)"></i>No record from India</span>' : '');
  $('#webnote').innerHTML = web
    ? `Partner species from GloBI (Global Biotic Interactions), by kind of link; a dot is filled when a record of the link is from India, and larger with more records. <a href="https://www.globalbioticinteractions.org/?interactionType=interactsWith&amp;sourceTaxon=${encodeURIComponent(name)}">All links on GloBI</a>.`
    : web === undefined ? 'The partner species show here from the next weekly list. The ring shows the seven gaps for this species.'
      : 'No interaction recorded in GloBI. The ring shows the seven gaps for this species.';
  const gapList = () => {
    $('#pick').innerHTML = `<div class="muted crumb">The seven gaps for this species</div>
      <ul class="gaplist">${gaps.map(g => `<li><i class="pip ${g.state}"></i><div><b>${esc(g.term)}</b> · ${esc(g.plain)}<small>${esc(g.text)}</small></div></li>`).join('')}</ul>
      <div class="legend" style="margin-top:12px"><span class="lbl"><i class="pip known"></i>Known</span><span class="lbl"><i class="pip part"></i>Part known</span>
      <span class="lbl"><i class="pip gap"></i>Open gap</span><span class="lbl"><i class="pip na"></i>Not measured</span></div>`;
  };
  let on = null;
  const pickNode = i => {
    const n = L.nodes[i], k = kindOf[n.kind];
    on?.classList.remove('on'); on = $(`#web .wn[data-i="${i}"]`); on?.classList.add('on');
    $('#pick').innerHTML = `<div class="crumb" style="color:${k.color}">${esc(k.label)}</div>
      <p class="sp-big" style="font-style:italic">${n.key ? `<a href="/species?key=${encodeURIComponent(n.key)}">${esc(n.name)}</a>` : esc(n.name)}</p>
      <p class="note" style="margin:4px 0 10px">${esc(n.types.map(t => VERBS[t] || t).join(', '))}</p>
      <dl class="stats"><dt>Records of the link</dt><dd>${fmt(n.n)}</dd><dt>From India</dt><dd>${n.india ? 'yes' : 'none'}</dd>
        <dt>On the India list</dt><dd>${n.key ? 'yes' : '<span class="muted">no</span>'}</dd></dl>
      <p style="margin:12px 0 0"><button type="button" class="linkish" id="gapsback">Show the seven gaps</button></p>`;
    $('#gapsback').addEventListener('click', () => { on?.classList.remove('on'); on = null; gapList(); });
  };
  for (const g of document.querySelectorAll('#web .wn')) {
    const i = +g.dataset.i;
    g.addEventListener('click', () => pickNode(i));
    g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pickNode(i); } });
  }
  gapList();
  if (web) {
    $('#partners').innerHTML = L.sectors.flatMap(sec => web.p[sec.kind].map(([pn, pk, n, india]) =>
      `<tr><td><i>${pk ? `<a href="/species?key=${encodeURIComponent(pk)}">${esc(pn)}</a>` : esc(pn)}</i></td><td>${esc(kindOf[sec.kind].label)}</td>
        <td class="n mono">${fmt(n)}</td><td class="n mono">${india ? fmt(india) : '–'}</td></tr>`)).join('');
    $('#web-table').hidden = false;
  }

  // Map: each district by its latest GBIF record; else its state by an open record. Waiting observations in the tip.
  const byState = new Map(states.map(s => [Number(s.code), s]));
  const map = drawMap($('#map'), boundaries, {
    label: `Map of India: where ${name} has a record`, pickLabel: 'Explore this state',
    onPick: d => { location.href = `/?state=${d.state_lgd}`; },
  });
  const since = S.recent_from;
  map.fill(whereFill(boundaries.districts, gbif?.districts, byState, since),
    v => ({ recent: '--q3', old: '--q1', state: '--q0', none: '--none' }[v.cls]),
    (id, v) => [v.cls === 'recent' || v.cls === 'old' ? `${fmt(v.n)} GBIF record${v.n === 1 ? '' : 's'}, ${v.first ?? '?'} to ${v.latest ?? '?'}`
      : v.cls === 'state' ? 'An open record in the state; none placed in this district' : 'No open record in the state',
    v.wait ? `${fmt(v.wait)} observations in the state wait for a name` : ''].filter(Boolean).join('<br>'));
  $('#legend').innerHTML = `<span class="lbl"><i class="sw" style="background:var(--q3);border:0"></i>Record since ${since}</span>
    <span class="lbl"><i class="sw" style="background:var(--q1);border:0"></i>Older record</span>
    <span class="lbl"><i class="sw" style="background:var(--q0);border:0"></i>Open record in the state, district not known</span>
    <span class="lbl"><i class="sw" style="background:var(--zero);border:0"></i>No open record</span>`;
  const nDist = gbif?.districts?.length || 0;
  $('#where').textContent = nObs ? `Open records in ${fmt(nObs)} state${nObs === 1 ? '' : 's'}${nDist ? ` and ${fmt(nDist)} district${nDist === 1 ? '' : 's'}` : ''}${latestYear ? `; latest ${latestYear}` : ''}.`
    : 'No open record with a state yet.';
  const waitList = states.filter(s => s.wait).sort((a, b) => b.wait - a.wait).slice(0, 8);
  $('#waiting').innerHTML = waitList.length && taxon ? `Observations that wait for a name: ${waitList.map(s => `<a href="${identify(S.waiting.places[s.code] ?? S.waiting.places.india)}" target="_blank" rel="noopener">${esc(s.name)} (${fmt(s.wait)})</a>`).join(', ')}. Help name them on iNaturalist.` : '';

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
    `<span id="gbif-links"><a href="${esc(gbifNameSearch(name))}">GBIF: search this name</a></span>`,
    taxon ? `<a href="https://www.inaturalist.org/taxa/${encodeURIComponent(taxon)}">iNaturalist</a>` : `<a href="https://www.inaturalist.org/taxa/search?q=${q}">iNaturalist: search this name</a>`,
    `<a href="https://www.iucnredlist.org/search?query=${q}">IUCN Red List</a>`,
    `<a href="https://indiabiodiversity.org/species/list?query=${q}">India Biodiversity Portal</a>`,
  ].map(x => `<li>${x}</li>`).join('');
  // GBIF's own key gives direct links to the records from India. If GBIF does not answer, the name search stays.
  fetch(`https://api.gbif.org/v1/species/match?strict=true&name=${q}`).then(r => (r.ok ? r.json() : null)).then(m => {
    const key = gbifKeyOf(m), links = gbifIndiaLinks(key, codes);
    if (key != null) showNext(key);
    if (links.length) $('#gbif-links').innerHTML = links.map(l => `<a href="${esc(l.href)}">${esc(l.text)}</a>`).join('<br>');
  }).catch(() => {});
  $('#source').innerHTML = `${esc(S.disclaimer || '')} ${sourceLine(snapSummary)}`;
} catch (err) {
  showLoadError(err);
}
