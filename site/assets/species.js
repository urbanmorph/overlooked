// One species: its name and picture; the seven gaps as a pyramid, each block with the share of its group where the gap
// is known; where it is (district map) beside when (GBIF records by decade) and its numbers; who it interacts with
// (GloBI); its relatives in the family on a time axis; then the details: status, sources, labels, evidence, links.

import { snapshot, getJSON, fmt, esc, $, bit, tags, showDevBanner, sourceLine, showLoadError } from './common.js?v=9455fd8cc8';
import { drawMap } from './map.js?v=b39659b5ac';
import { gbifKeyOf, gbifIndiaLinks, gbifNameSearch, nextSteps } from './links.js?v=5e428c2f50';
import { barcodeText, countText, localNames } from './evidence.js?v=2fcbd9aeae';
import { KINDS, VERBS, gapStates, glyphSVG, groupShares, pyramidHTML, relatives, tree, whereFill } from './web.js?v=323725a916';

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
const STATE = { known: 'Known', part: 'Part known', gap: 'Open gap', na: 'Not measured' };
const IDENTIFY = 'https://www.inaturalist.org/observations/identify';
const AFTER = { recorded: y => `Recorded again after ${y}`, later_papers: y => `After ${y}, only in papers`,
  none: y => `No GBIF record after ${y}` };
const BASIS = [
  ['PRESERVED_SPECIMEN', 'Specimen'], ['MATERIAL_SAMPLE', 'Specimen'], ['MATERIAL_CITATION', 'From a paper'],
  ['HUMAN_OBSERVATION', 'Observation'], ['MACHINE_OBSERVATION', 'Observation'], ['OBSERVATION', 'Observation'], ['OCCURRENCE', 'Other'],
];
const KIND = Object.fromEntries(BASIS);
const KIND_ORDER = [['Specimen', '#16201C'], ['From a paper', '#8A9690'], ['Observation', '#2F5DA8'], ['Other', '#C5CCC7']];

// The group in a few words, for "known for 43% of bats": the part after the colon, else the group; long names read "this group".
const groupWord = g => { const w = (g.split(': ')[1] || g).toLowerCase(); return w.length > 18 ? 'species of this group' : w; };

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

// GBIF records by decade, stacked by kind of record. False when there are none.
function history(s) {
  const decades = new Map();
  for (const [dec, basis, n] of s?.decades || []) {
    if (dec == null) continue;
    const k = KIND[basis] || 'Other';
    const m = decades.get(dec) || {}; m[k] = (m[k] || 0) + n; decades.set(dec, m);
  }
  if (!decades.size) return false;
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
  return true;
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

// The picture beside the name: a photo with its credit; null, a box that asks for one on iNaturalist (where others
// confirm the name before it shows here); undefined (a list with no pictures yet), nothing.
function picture(pic, name) {
  if (pic === undefined) return '';
  if (!pic) {
    return `<div class="ph none"><b>No open photo yet</b><span>Seen it in India? Add your photo to iNaturalist. Once others there confirm the name, it shows here.</span>
      <a href="https://www.inaturalist.org/observations/upload" target="_blank" rel="noopener">Add a photo on iNaturalist</a></div>`;
  }
  const [url, page, by, licence, source] = pic;
  return `<div class="ph"><img src="${esc(url)}" alt="${esc(name)}" decoding="async"></div>
    <figcaption>Photo: ${by ? `${esc(by)}, ` : ''}${esc(licence)} · <a href="${esc(page)}" target="_blank" rel="noopener">${esc(source)}</a></figcaption>`;
}

// Relatives on a time axis: a line from the year described to the latest record placed in a state, with each
// species' glyph; this species in colour. A row links to that species' page.
function relativesSVG(R, key, since) {
  const rowH = 32, top = 26, left = 300, W = 1000, right = 20, H = top + R.length * rowH + 8;
  const years = R.map(r => r.year).filter(Boolean);
  const y0 = Math.floor((Math.min(...years, 1900) - 10) / 25) * 25, y1 = 2030;
  const x = y => left + (W - left - right) * (y - y0) / (y1 - y0);
  let s = `<rect x="${x(since)}" y="${top - 6}" width="${x(y1) - x(since)}" height="${H - top}" fill="var(--line-2)"/>`;
  for (let y = y0; y <= 2025; y += 25) s += `<line x1="${x(y)}" x2="${x(y)}" y1="${top - 6}" y2="${H - 6}" stroke="var(--line)"/><text class="ax" x="${x(y)}" y="14" text-anchor="middle">${y}</text>`;
  R.forEach((r, i) => {
    const y = top + i * rowH + rowH / 2, me = r.key === key, c = me ? 'var(--accent)' : 'var(--field)';
    const tip = `${r.name}: ${r.year ?? 'year not known'} to ${r.last ?? 'no placed record'}; ${fmt(r.states)} state${r.states === 1 ? '' : 's'} with an open record`;
    s += `<a href="/species?key=${encodeURIComponent(r.key)}" class="${me ? 'me' : ''}"><title>${esc(tip)}</title>`
      + `<rect x="0" y="${y - rowH / 2}" width="${W}" height="${rowH}" fill="transparent"/>`
      + glyphSVG(r.gaps, 26).replace('<svg ', `<svg x="0" y="${y - 10}" `)
      + `<text x="36" y="${y + 4}" font-style="italic">${esc(r.name)}</text>`
      + (r.year && r.last ? `<line x1="${x(r.year)}" x2="${x(r.last)}" y1="${y}" y2="${y}" stroke="${c}" stroke-width="${me ? 4 : 2.5}" stroke-linecap="round"/>` : '')
      + (r.year ? `<circle cx="${x(r.year)}" cy="${y}" r="4.5" fill="var(--surface)" stroke="${c}" stroke-width="2"/>` : '')
      + (r.last ? `<circle cx="${x(r.last)}" cy="${y}" r="5" fill="${c}"/>` : '') + '</a>';
  });
  return { svg: s, viewBox: `0 0 ${W} ${H}` };
}

try {
  const key = new URLSearchParams(location.search).get('key');
  if (!key) throw new Error('no species key in the address');
  const latest = await getJSON('layers/master/latest.json');
  const snap = await snapshot();
  const shard = shardOf(key);
  const [S, part, snapSummary, boundaries, gbif, web, pics] = await Promise.all([
    getJSON(latest.base + 'summary.json'), getJSON(`${latest.base}sp/${shard}.json`),
    snap.summary(), snap.boundaries(), getJSON(snap.file(`species/${shard}.json`)).then(p => p[key]).catch(() => null),
    getJSON(`${latest.base}web/${shard}.json`).then(p => p[key] || null).catch(() => undefined),   // undefined: a list with no web yet
    getJSON(`${latest.base}pic/${shard}.json`).catch(() => undefined)]);                           // undefined: a list with no pictures yet
  showDevBanner(snapSummary);
  const row = part[key];
  if (!row) throw new Error('species not on the master list');
  const [name, gi, sources, status, iucn, labels, obsMask, taxon, waitIndia, waitStates, year, authority, paper, iucnYear, iucnDoi,
    partners, interactionsIndia, cells, types, photos, barcode, localPairs, trend, traits, precise, papers, papersLatest, iucnTrend,
    family] = row;
  const group = S.groups[gi] || '', word = groupWord(group);
  const states = S.states.map((st, i) => ({ ...st, i, obs: bit(obsMask, i), wait: (waitStates.find(x => x[0] === i) || [0, 0])[1] }));
  const nObs = states.filter(s => s.obs).length;
  const cat = S.iucn[iucn];
  const codes = new Set(S.labels.filter((l, i) => bit(labels, i)).map(l => l.code));
  const latestYear = gbif?.districts?.length ? Math.max(...gbif.districts.map(d => d[2] ?? 0)) || null : null;
  const gaps = gapStates({ year, latest: latestYear, trend, iucnTrend, dna: codes.has('dna'), barcode, traits, precise, partners,
    interactionsIndia }, S);
  const nKnown = gaps.filter(g => g.state === 'known').length, nNa = gaps.filter(g => g.state === 'na').length;

  // Name, picture and the few facts that tell what this species is on the list.
  document.title = `${name} · Overlooked`;
  $('#name').textContent = name;
  const fam = family || gbif?.family;
  $('#crumb').textContent = `/ ${group}${fam ? ` / ${fam}` : ''}`;
  const pic = pics === undefined ? undefined : pics[key] ?? null;
  $('#common').textContent = pic?.[5] || '';
  $('#common').hidden = !pic?.[5];
  $('#photo').innerHTML = picture(pic, name);
  const author = (authority || '').replace(/,?\s*\d{4}\)?\s*$/, m => (m.endsWith(')') ? ')' : ''));
  const trendWord = ['Increasing', 'Stable', 'Decreasing'].includes(iucnTrend) ? `population ${iucnTrend.toLowerCase()} · ` : '';
  $('#pills').innerHTML = [
    `<span class="sp-pill">${glyphSVG(gaps.map(g => g.state), 26)} ${nKnown} of 7 known</span>`,
    `<span class="sp-pill"><b>${esc(STATUS[status])}</b></span>`,
    cat && cat !== 'NE' ? `<span class="sp-pill"><b>IUCN ${esc(cat)}</b> <span>${esc(trendWord)}${iucnYear ? `assessed ${iucnYear}` : ''}</span></span>`
      : '<span class="sp-pill">Not assessed by IUCN</span>',
    year ? `<span class="sp-pill"><b>Described</b> <a href="/?described=${year}-${year}">${year}</a>${author ? ` by ${esc(author)}` : ''}</span>` : '',
  ].join('');

  // The seven gaps: the pyramid, each block this species' state with the group's share as a bar.
  const shares = groupShares(S, gi), documented = S.india?.[gi]?.[0];
  $('#pyr').innerHTML = pyramidHTML(gaps, shares, word);
  $('#pyrkey').innerHTML = [['known', 'Known'], ['part', 'Part known'], ['gap', 'Open gap'], ['na', 'Not measured']]
    .map(([c, l]) => `<span class="lbl"><i class="sw blk ${c}" style="min-height:0;padding:0"></i>${l} for this species</span>`).join('')
    + (shares.some(v => v != null) ? `<span class="lbl">Bar: the share of the ${fmt(documented)} ${esc(word)} on the India list where it is known</span>` : '');
  const intro = `${nKnown} of 7 known for this species${nNa ? `, ${nNa} not measured yet` : ''}. Pick a block for what we measured.`;
  $('#gapnote').textContent = intro;
  $('#pyr').addEventListener('click', e => {
    const b = e.target.closest('.blk');
    if (!b) return;
    const i = +b.dataset.i, g = gaps[i], pct = shares[i], was = b.getAttribute('aria-pressed') === 'true';
    for (const x of document.querySelectorAll('#pyr .blk')) x.setAttribute('aria-pressed', 'false');
    if (was) { $('#gapnote').textContent = intro; return; }
    b.setAttribute('aria-pressed', 'true');
    $('#gapnote').innerHTML = `<b>${esc(g.plain)} (${esc(g.term)} gap): ${esc(STATE[g.state].toLowerCase())}.</b> ${esc(g.text)}`
      + (pct == null ? '' : ` Known for ${pct}% of the ${fmt(documented)} ${esc(word)} on the India list.`);
  });

  // Map: each district by its latest GBIF record; else its state by an open record. Waiting observations in the tip.
  const identify = place => `${IDENTIFY}?quality_grade=needs_id&taxon_id=${encodeURIComponent(taxon)}&place_id=${encodeURIComponent(place)}`;
  const byState = new Map(states.map(s => [Number(s.code), s]));
  const map = drawMap($('#map'), boundaries, {
    label: `Map of India: where ${name} has a record`, pickLabel: 'Explore this state',
    onPick: d => { location.href = `/?state=${d.state_lgd}`; },
  });
  const since = S.recent_from;
  map.fill(whereFill(boundaries.districts, gbif?.districts, byState, since),
    v => ({ recent: '--q3', old: '--q1', state: '--q0', none: '--none' }[v.cls]),
    (id, v) => [v.cls === 'recent' || v.cls === 'old' ? `${fmt(v.n)} GBIF record${v.n === 1 ? '' : 's'}, ${v.first ?? '?'} to ${v.latest ?? '?'}`
      : v.cls === 'state' ? 'Recorded in this state, but no record gives the district' : 'No open record in the state',
    v.wait ? `${fmt(v.wait)} observations in the state wait for a name` : ''].filter(Boolean).join('<br>'));
  $('#legend').innerHTML = `<span class="lbl"><i class="sw" style="background:var(--q3);border:0"></i>Record since ${since}</span>
    <span class="lbl"><i class="sw" style="background:var(--q1);border:0"></i>Older record</span>
    <span class="lbl"><i class="sw" style="background:var(--q0);border:0"></i>Recorded in the state, district not given</span>
    <span class="lbl"><i class="sw" style="background:var(--zero);border:0"></i>No open record</span>`;
  const nDist = gbif?.districts?.length || 0;
  $('#where').textContent = nObs ? `Open records in ${fmt(nObs)} state${nObs === 1 ? '' : 's'}${nDist ? `; GBIF records placed in ${fmt(nDist)} district${nDist === 1 ? '' : 's'}` : ''}.`
    : 'No open record with a state yet.';
  const waitList = states.filter(s => s.wait).sort((a, b) => b.wait - a.wait).slice(0, 8);
  $('#waiting').innerHTML = waitList.length && taxon ? `Observations that wait for a name: ${waitList.map(s => `<a href="${identify(S.waiting.places[s.code] ?? S.waiting.places.india)}" target="_blank" rel="noopener">${esc(s.name)} (${fmt(s.wait)})</a>`).join(', ')}. Help name them on iNaturalist.` : '';

  // When: GBIF records by decade, then the numbers under it.
  $('#nohist').hidden = history(gbif);
  const placed = gbif?.districts?.reduce((a, d) => a + d[3], 0) || 0;
  const firstYear = gbif?.districts?.length ? Math.min(...gbif.districts.map(d => d[1]).filter(y => y > 0)) : null;
  $('#tiles').innerHTML = [
    [fmt(nObs), `state${nObs === 1 ? '' : 's'} with an open record`, nDist ? `${fmt(nDist)} districts` : ''],
    latestYear ? [String(latestYear), 'latest placed record', Number.isFinite(firstYear) ? `first ${firstYear}` : ''] : null,
    placed ? [fmt(placed), 'GBIF records placed', 'in a district'] : null,
    [fmt(partners ?? 0), 'partner species', 'GloBI'],
    photos != null ? [fmt(photos), 'records with a photo', 'from India'] : null,
    [fmt(waitIndia), 'observations waiting', 'for a name on iNaturalist'],
  ].filter(Boolean).map(([v, l, s]) => `<div><b>${esc(v)}</b><span>${esc(l)}${s ? `<br><small>${esc(s)}</small>` : ''}</span></div>`).join('');

  // Who it interacts with: a bar of kinds (pick to show or hide), a search, India only, then a branch per kind.
  const T = tree(web || { n: {}, p: {} }), shownAll = new Set(), on = new Set(T.map(b => b.kind));
  const allN = T.reduce((a, b) => a + b.total, 0);
  $('#webnote').innerHTML = web
    ? `${fmt(partners)} partner species in GloBI (Global Biotic Interactions), by kind of link, the most records first; a filled dot has a record from India. <a href="https://www.globalbioticinteractions.org/?interactionType=interactsWith&amp;sourceTaxon=${encodeURIComponent(name)}">All links on GloBI</a>.`
    : web === undefined ? 'The partner species show here from the next weekly list.' : 'No interaction recorded in GloBI.';
  $('#webcontrols').hidden = !T.length;
  $('#kindsbar').innerHTML = T.map(b => `<button type="button" aria-pressed="true" data-k="${b.kind}" style="flex:${b.total} 1 0;background:${b.color}"
    title="${esc(b.label)}: ${fmt(b.total)} species, ${Math.round(100 * b.total / allN)}% of links">${esc(b.label)} ${fmt(b.total)}</button>`).join('');
  const drawTree = () => {
    const q = $('#q').value.trim().toLowerCase(), india = $('#indiaonly').checked;
    const html = T.filter(br => on.has(br.kind)).map(br => {
      const rows = br.rows.filter(r => (!q || r.name.toLowerCase().includes(q)) && (!india || r.india));
      if (!rows.length) return '';
      const limit = shownAll.has(br.kind) || q ? rows.length : 8;
      const microbes = br.kind === 'hosts' && rows.slice(0, limit).some(r => /virus|bacter|plasm/i.test(r.name));
      return `<section class="wb" style="--c:${br.color}"><h3><i></i>${esc(br.label)} <span class="note">${fmt(rows.length)} shown of ${fmt(br.total)}</span></h3>
        ${microbes ? '<p class="note why">Viruses and microbes here come from screening studies: they were found in the animal, which does not mean they make it ill.</p>' : ''}
        <ul>${rows.slice(0, limit).map(r => {
          const inner = `<i class="dot${r.india ? ' in' : ''}"></i><span class="nm">${esc(r.name)}</span><span class="bar"><i style="width:${(100 * r.bar).toFixed(1)}%"></i></span><span class="ct">${fmt(r.n)}</span>`;
          const tip = `${r.types.map(t => VERBS[t] || t).join(', ')} · ${fmt(r.n)} record${r.n === 1 ? '' : 's'}${r.india ? ', some from India' : ', none from India'}`;
          return `<li>${r.key ? `<a class="wp" href="/species?key=${encodeURIComponent(r.key)}" title="${esc(tip)}">${inner}</a>` : `<span class="wp" title="${esc(tip)}">${inner}</span>`}</li>`;
        }).join('')}</ul>
        ${rows.length > limit ? `<button type="button" class="linkish wmore" data-k="${br.kind}">Show all ${fmt(rows.length)}</button>` : ''}</section>`;
    }).join('');
    $('#web').innerHTML = html || (T.length ? '<p class="note">No partner matches. Clear the search or show more kinds of link.</p>' : '');
  };
  $('#kindsbar').addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    const k = b.dataset.k;
    if (on.has(k) && on.size > 1) on.delete(k); else on.add(k);
    b.setAttribute('aria-pressed', String(on.has(k)));
    drawTree();
  });
  $('#web').addEventListener('click', e => {
    const b = e.target.closest('.wmore');
    if (b) { shownAll.add(b.dataset.k); drawTree(); }
  });
  $('#q').addEventListener('input', drawTree);
  $('#indiaonly').addEventListener('change', drawTree);
  drawTree();
  $('#weblegend').innerHTML = web ? `<span class="lbl"><i class="dot in" style="--c:var(--ink-2)"></i>A record of the link from India</span>
    <span class="lbl"><i class="dot" style="--c:var(--ink-2)"></i>None from India</span><span class="lbl">Bar and number: records of the link</span>
    <span class="lbl">A name in colour links to its page</span>` : '';

  // Relatives: the species of the family on the list, on a time axis.
  if (family) {
    getJSON(`${latest.base}fam/${shardOf(family)}.json`).then(p => {
      const rows = p[family] || [];
      if (rows.length < 2) return;
      const R = relatives(rows, key, name, S), { svg, viewBox } = relativesSVG(R.rows, key, since);
      const genus = name.split(' ')[0];
      $('#rel').setAttribute('viewBox', viewBox);
      $('#rel').innerHTML = svg;
      $('#relnote').textContent = `${fmt(R.total)} species of ${family} on the India list${R.total > R.rows.length ? `; the ${R.rows.length} here are ${genus} first, then those recorded most recently` : ''}. Each line runs from the year a species was described to its latest record placed in a state; ${name} in colour. The small pyramid shows each one's seven gaps. Pick a name for its page.`;
      $('#relcard').hidden = false;
    }).catch(() => {});
  }

  // Details: status, the evidence behind it, sources and labels, and the next step a person can take.
  const chips = (mask, names) => tags(mask, names) || '<span class="muted">–</span>';
  $('#status').innerHTML = `<h2 style="font-size:18px">${esc(STATUS[status])}</h2><p class="note" style="margin:4px 0 12px">${STATUS_TEXT[status]}</p>
    <dl class="stats">
      <dt>Area of occupancy</dt><dd>${cells == null ? '<span class="muted">Not counted yet</span>'
        : `${fmt(4 * cells)} km² <span class="muted">· ${fmt(cells)} ${cells === 1 ? 'cell' : 'cells'} of 2 × 2 km with an open record placed in India</span>`}</dd>
${evidenceRows(S, name, types, photos, barcode, localPairs)}${S.papers?.[gi] != null ? `
      <dt>Papers</dt><dd>${papers ? `${fmt(papers)} in the Bibliography of South Asian Ornithology${papersLatest ? `, latest ${papersLatest}` : ''}` : '<span class="muted">None in the Bibliography of South Asian Ornithology</span>'} <span class="muted">· <a href="https://southasiaornith.in">A. Pittie</a></span></dd>` : ''}
      <dt>IUCN Red List</dt><dd><span class="iucn i-${esc(cat)}">${esc(cat === 'NE' ? 'Not assessed' : cat)}</span>${iucnTrend ? ` <span class="muted">· population ${esc(iucnTrend.toLowerCase())}</span>` : ''}${iucnYear
        ? ` <span class="muted">· assessed in ${iucnYear}${iucnDoi ? ` (<a href="${esc(iucnDoi)}">the assessment</a>)` : ''}</span>` : ''}</dd>
    </dl>
    ${paper ? `<p class="note" style="margin:12px 0 0">${paper[5] === year ? 'Description' : `Listed in ${paper[5]}`}: <a href="${esc(paper[2])}">${esc(paper[0].join(', '))}</a>${paper[1] ? ` (${esc(paper[1])})` : ''}.
      ${AFTER[paper[3]] ? `${esc(AFTER[paper[3]](paper[5]))}${paper[3] === 'recorded' && paper[4] ? ` (latest ${paper[4]})` : ''}.` : ''}</p>` : ''}
    <div class="note" style="margin:12px 0 4px">Sources</div><div>${chips(sources, S.sources)}</div>
    <div class="note" style="margin:12px 0 4px">Labels</div><div>${chips(labels, S.labels.map(l => l.name))}</div>
    <div class="sp-wait" id="next"></div>`;
  // Next step: what a person can do for this species, and where. GBIF links fill in when GBIF gives its key.
  const showNext = gbifKey => {
    const steps = nextSteps({ status, iucn: cat, codes, wait: waitIndia, identify: taxon ? identify(S.waiting.places.india) : null,
      gbifKey, name, paper: paper?.[2] });
    $('#next').hidden = !steps.length;
    $('#next').innerHTML = `<div class="note" style="margin:0 0 4px">Next step</div><ol class="next-steps">${steps.map(s => `<li>${esc(s.text)}${s.links.length ? `<br>${s.links.map(l =>
      `<a class="idlink" href="${esc(l.href)}" target="_blank" rel="noopener">${esc(l.text)}</a>`).join(' · ')}` : ''}</li>`).join('')}</ol>`;
  };
  showNext(null);

  if (gbif?.districts?.length) {
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
    const k = gbifKeyOf(m), links = gbifIndiaLinks(k, codes);
    if (k != null) showNext(k);
    if (links.length) $('#gbif-links').innerHTML = links.map(l => `<a href="${esc(l.href)}">${esc(l.text)}</a>`).join('<br>');
  }).catch(() => {});
  $('#source').innerHTML = `${esc(S.disclaimer || '')} ${sourceLine(snapSummary)}`;
} catch (err) {
  showLoadError(err);
}
