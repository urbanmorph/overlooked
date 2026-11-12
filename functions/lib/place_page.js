// The place pages in HTML (functions/in/[[path]].js): /in, /in/<place> and /in/<place>/<group>, written into the
// shell site/in.html with their own title, description, canonical address and schema.org CollectionPage, so search
// engines and AI crawlers read them without JavaScript. Pure: the shell and the data in, the page out.
import { esc, iucnBadge, model, speciesName } from '../../site/assets/species_model.js';
import { CATS } from '../../site/assets/cats.js';
import { MIN_SPECIES, countsOf, groupNoun, groupTitle, placePath, places } from './places.js';

const SITE = 'https://yellide.com';
const LIST_MAX = 500;        // species named in full on one page; more are a link to the map

const nf = new Intl.NumberFormat('en-IN');
const fmt = n => nf.format(n);
const list = xs => (xs.length < 3 ? xs.join(' and ') : `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}`);
const byName = (a, b) => a.name.localeCompare(b.name);

function replaceMeta(html, attr, name, value) {
  return html.replace(new RegExp(`<meta ${attr}="${name}" content="[^"]*">`), `<meta ${attr}="${name}" content="${value}">`);
}

/** The shell with this page's title, description, address, structured data and main content. */
function fill(shell, { title, desc, path, body, ld, index = true }) {
  const url = SITE + path, t = esc(title), d = esc(desc);
  let out = shell.replace(/<title>[^<]*<\/title>/, `<title>${t}</title>`);
  out = replaceMeta(out, 'name', 'description', d);
  out = replaceMeta(out, 'property', 'og:title', t);
  out = replaceMeta(out, 'property', 'og:description', d);
  out = out.replace(/<link rel="canonical" href="[^"]*">/, `<link rel="canonical" href="${url}">`)
    .replace(/<meta property="og:url" content="[^"]*">/, `<meta property="og:url" content="${url}">`);
  const json = ld ? `<script type="application/ld+json">${JSON.stringify(ld).replace(/</g, '\\u003c')}</script>\n` : '';
  out = out.replace('</head>', `${index ? '' : '<meta name="robots" content="noindex">\n'}${json}</head>`);
  return out.replace(/<!-- place:[^>]*-->/, body);
}

const crumbs = items => `<nav aria-label="Breadcrumb" class="note crumbs" style="margin-top:32px">`
  + items.map(([name, path]) => (path ? `<a href="${path}">${esc(name)}</a>` : esc(name))).join(' / ') + `</nav>`;

const breadcrumbLd = items => ({ '@type': 'BreadcrumbList', itemListElement: items.map(([name, path], i) =>
  ({ '@type': 'ListItem', position: i + 1, name, ...(path ? { item: SITE + path } : {}) })) });

const speciesItems = rows => rows.map(r => `<li>${speciesName(r.key, r.name, r.english ?? null,
  r.iucn && r.iucn !== 'NE' && r.iucn !== 'LC' ? iucnBadge(r.iucn) : '')}</li>`).join('');

/** "on the map" on the front page: the group's family there, and the state. */
function mapHref(place, group) {
  const cat = CATS.find(([, , t]) => t(group));
  const q = new URLSearchParams({ ...(place.kind === 'state' ? { state: place.code } : {}), ...(cat ? { group: cat[0] } : {}) });
  return `/${q.size ? `?${q}` : ''}`;
}

/** What "in" means for each kind of place, as a sentence starts. */
function sentence(place, n, noun) {
  if (place.kind === 'india') return `${fmt(n)} ${noun} are on the India list`;
  if (place.kind === 'state') return `${fmt(n)} ${noun} on the India list have an open record placed in ${place.title}`;
  return `${fmt(n)} ${noun} on the India list have a GBIF record placed in ${place.title}`;
}

/** /in/<place>/<group>. d: {S, rows, week, unmarked} from speciesWhere; C: placeCounts. */
export function groupPage(shell, { place, gi, d, C }) {
  const { S, rows, week } = d, group = S.groups[gi], noun = groupNoun(group), title = `${groupTitle(group)} of ${place.title}`;
  const path = placePath(place, group);
  const M = model(S), order = c => S.threatened.indexOf(c);
  const thr = rows.filter(r => M.threatened(r.iucn)).sort((a, b) => order(a.iucn) - order(b.iucn) || byName(a, b));
  const marked = !d.unmarked.includes(group), end = marked ? rows.filter(r => r.endemic).sort(byName) : [];
  const byCat = S.threatened.map(c => [c, thr.filter(r => r.iucn === c).length]).filter(([, n]) => n);
  const n = rows.length;
  const lead = n ? `${sentence(place, n, noun)}${thr.length ? `, ${fmt(thr.length)} of them threatened (${list(byCat.map(([c, k]) => `${fmt(k)} ${M.iucnName(c)}`))})` : ''}`
    + `${end.length ? `${thr.length ? ' and' : ','} ${fmt(end.length)} endemic to India` : ''}.` : 'No species on the list is recorded here yet.';
  const what = place.kind === 'state' ? 'A species is in a state when it has an open record placed there: a record anyone can check online (a GBIF record, or a research-grade iNaturalist observation).'
    : place.kind === 'zone' ? 'A species is in a region when a GBIF record of it is placed there (the biogeographic zones of the Wildlife Institute of India).'
      : 'The India list: every species documented from India, across sources.';
  const all = [...rows].sort(byName);
  const elsewhere = places(S).filter(p => p.slug !== place.slug && countsOf(C, p)[gi] > 0);
  const others = S.groups.map((g, i) => [g, i]).filter(([, i]) => i !== gi && countsOf(C, place)[i] > 0);
  const trail = [['Places', '/in'], [place.name, placePath(place)], [groupTitle(group), null]];
  const body = `${crumbs(trail)}
<h1 class="page">${esc(title)}</h1>
<p class="lede">${esc(lead)}</p>
<p class="note">${esc(what)} Threatened: IUCN Red List ${esc(M.threatenedWords)}. ${marked ? '' : `The sources give no endemic mark for ${esc(noun)} yet. `}List of the week of ${esc(week)}.</p>
${thr.length ? `<section id="threatened" class="place-list"><h2>Threatened ${esc(noun)} of ${esc(place.title)} (${fmt(thr.length)})</h2><ul class="splist">${speciesItems(thr.slice(0, LIST_MAX))}</ul></section>` : ''}
${end.length ? `<section id="endemic" class="place-list"><h2>${esc(groupTitle(group))} of ${esc(place.title)} endemic to India (${fmt(end.length)})</h2><ul class="splist">${speciesItems(end.slice(0, LIST_MAX))}</ul></section>` : ''}
${n ? `<section id="all" class="place-list"><h2>All ${esc(noun)} of ${esc(place.title)} on the list (${fmt(n)})</h2><ul class="splist">${speciesItems(all.slice(0, LIST_MAX))}</ul>
<p class="note">${n > LIST_MAX ? `The first ${fmt(LIST_MAX)} by name. ` : ''}<a href="${esc(mapHref(place, group))}">See them on the map, with filters</a>.</p></section>` : ''}
${elsewhere.length ? `<section class="place-links"><h2>${esc(groupTitle(group))} elsewhere</h2><p>${elsewhere.map(p => `<a href="${placePath(p, group)}">${esc(p.name)}</a>`).join(' · ')}</p></section>` : ''}
${others.length ? `<section class="place-links"><h2>Other species of ${esc(place.title)}</h2><p>${others.map(([g]) => `<a href="${placePath(place, g)}">${esc(groupTitle(g))}</a>`).join(' · ')}</p></section>` : ''}`;
  const desc = `${lead} ${what.split(':')[0]}. Updated each week.`;
  return fill(shell, {
    title: `${title}: ${fmt(n)} species${thr.length ? `, ${fmt(thr.length)} threatened` : ''} · yellide`, desc, path, body, index: n >= MIN_SPECIES,
    ld: { '@context': 'https://schema.org', '@graph': [
      { '@type': 'CollectionPage', name: title, url: SITE + path, description: lead, isPartOf: { '@type': 'WebSite', name: 'yellide', url: `${SITE}/` },
        about: { '@type': 'Place', name: place.name }, numberOfItems: n },
      breadcrumbLd(trail)] },
  });
}

/** /in/<place>: its groups, with how many species and how many threatened are there. d: speciesWhere for the place. */
export function placeHub(shell, { place, d, C }) {
  const { S, rows, week } = d, counts = countsOf(C, place), n = rows.length;
  const M = model(S), thr = rows.filter(r => M.threatened(r.iucn)).length;
  const thrBy = S.groups.map((_, i) => rows.filter(r => r.gi === i && M.threatened(r.iucn)).length);
  const title = `Species of ${place.title}`, path = placePath(place);
  const lead = n ? `${sentence(place, n, 'species')}, ${fmt(thr)} of them threatened.` : 'No species on the list is recorded here yet.';
  const trail = [['Places', '/in'], [place.name, null]];
  const rowsHtml = S.groups.map((g, i) => [g, i]).filter(([, i]) => counts[i] > 0).map(([g, i]) =>
    `<tr><td><a href="${placePath(place, g)}">${esc(groupTitle(g))}</a></td><td class="n">${fmt(counts[i])}</td><td class="n">${fmt(thrBy[i])}</td></tr>`).join('');
  const body = `${crumbs(trail)}
<h1 class="page">${esc(title)}</h1>
<p class="lede">${esc(lead)}</p>
<p class="note">List of the week of ${esc(week)}. Pick a group for its species.</p>
${rowsHtml ? `<div class="tablebox"><table><thead><tr><th>Group</th><th class="n">Species</th><th class="n">Threatened</th></tr></thead><tbody>${rowsHtml}</tbody></table></div>` : ''}`;
  return fill(shell, {
    title: `${title}: ${fmt(n)} species by group · yellide`, desc: `${lead} By group: birds, mammals, reptiles, amphibians, insects, plants and more. Updated each week.`,
    path, body, index: n >= MIN_SPECIES,
    ld: { '@context': 'https://schema.org', '@graph': [
      { '@type': 'CollectionPage', name: title, url: SITE + path, description: lead, about: { '@type': 'Place', name: place.name } },
      breadcrumbLd(trail)] },
  });
}

/** /in: every place, with how many species are there. */
export function placesIndex(shell, { C }) {
  const total = p => countsOf(C, p).reduce((a, b) => a + b, 0);
  const all = places(C.S), link = p => `<li><a href="${placePath(p)}">${esc(p.name)}</a> <span class="muted">${fmt(total(p))}</span></li>`;
  const title = 'Species of India, by state and region';
  const body = `${crumbs([['Explore', '/'], ['Places', null]])}
<h1 class="page">${esc(title)}</h1>
<p class="lede">For India, each state and each biogeographic zone: how many species of each group are recorded there, which are threatened and which are endemic to India.</p>
<section class="place-list"><h2>India</h2><ul class="splist">${all.filter(p => p.kind === 'india').map(link).join('')}</ul></section>
<section class="place-list"><h2>States and union territories</h2><p class="note">Species with an open record placed in the state.</p><ul class="splist">${all.filter(p => p.kind === 'state').map(link).join('')}</ul></section>
<section class="place-list"><h2>Biogeographic zones</h2><p class="note">Species with a GBIF record placed in the zone (Wildlife Institute of India).</p><ul class="splist">${all.filter(p => p.kind === 'zone').map(link).join('')}</ul></section>`;
  return fill(shell, { title: `${title} · yellide`, desc: 'The species of India by state and biogeographic region, group by group: how many have an open record there, which are threatened and which are endemic. Updated each week.',
    path: '/in', body, ld: { '@context': 'https://schema.org', '@type': 'CollectionPage', name: title, url: `${SITE}/in` } });
}

/** A place or group the list does not have. */
export const notFound = shell => fill(shell, { title: 'Not found · yellide', desc: 'No such place or group.', path: '/in', index: false,
  body: `${crumbs([['Places', '/in']])}<h1 class="page">No such place or group</h1><p class="lede"><a href="/in">See every place</a>.</p>` });
