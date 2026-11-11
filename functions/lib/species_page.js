// The species page with the species' own title, description, canonical address, share tags, schema.org Taxon and a
// plain summary in <noscript> (functions/species.js). The browser still draws the full page from the data files; this
// is for search engines, AI crawlers (they do not run JavaScript), link previews and readers with no JavaScript.
// Pure: the static page in, the filled page out. The species comes from lookupSpecies (lib/mcp.js).

const SITE = 'https://yellide.com';
// IUCN category names. EW and EX keep their codes: the site copy does not use those words.
const IUCN_NAMES = { CR: 'Critically Endangered', EN: 'Endangered', VU: 'Vulnerable', NT: 'Near Threatened', LC: 'Least Concern', DD: 'Data Deficient' };

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const list = xs => (xs.length < 3 ? xs.join(' and ') : `${xs.slice(0, -1).join(', ')} and ${xs.at(-1)}`);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function iucnText({ category, year, trend }) {
  if (!category || category === 'NE') return 'Not assessed by IUCN.';
  const name = IUCN_NAMES[category];
  const when = [year, trend && trend !== 'Unknown' ? trend.toLowerCase() : null].filter(Boolean).join(', ');
  return `${name ? `IUCN ${name}` : `IUCN category ${category}`}${when ? ` (${when})` : ''}.`;
}

/** The sentences of the description, also the start of the summary. */
function sentences(s) {
  const head = s.english ? `${s.english} (${s.name})` : s.name;
  const states = s.states_with_open_record || [];
  return [
    `${head}, a species of India.`,
    iucnText(s.iucn),
    s.endemic ? 'Endemic to India.' : null,
    states.length ? `Open records in ${plural(states.length, 'state', 'states')}.` : 'No open record from India yet.',
    s.sources?.length ? `Listed by ${list(s.sources)}.` : null,
    s.group ? `Group: ${s.group}.` : null,
  ].filter(Boolean);
}

function replaceMeta(html, attr, name, value) {
  const re = new RegExp(`<meta ${attr}="${name}" content="[^"]*">`);
  return html.replace(re, `<meta ${attr}="${name}" content="${value}">`);
}

/** found: {S, s, week} from lookupSpecies, or null for a key the list does not have. */
export function speciesPage(html, key, found) {
  if (!found) return html.replace('</head>', '<meta name="robots" content="noindex">\n</head>');
  const { s, week } = found;
  const url = `${SITE}/species?key=${encodeURIComponent(key)}`;
  const title = esc(`${s.english ? `${s.english} (${s.name})` : s.name} · yellide`);
  const desc = esc(`${sentences(s).join(' ')} Updated each week.`);
  const names = [s.english, ...(s.names_in_indian_languages || []).map(([, n]) => n)].filter(Boolean);
  const ld = {
    '@context': 'https://schema.org', '@type': 'Taxon', name: s.name, taxonRank: 'species', url,
    ...(names.length ? { alternateName: names } : {}),
    ...(s.family ? { parentTaxon: { '@type': 'Taxon', name: s.family, taxonRank: 'family' } } : {}),
    description: sentences(s).join(' '),
    isPartOf: { '@type': 'Dataset', name: 'yellide: species of India and their open records', url: `${SITE}/method` },
  };
  const facts = [
    s.described?.year || s.described?.authority ? `Described: ${esc(s.described.authority || s.described.year)}.` : null,
    s.states_with_open_record?.length ? `States with an open record: ${esc(s.states_with_open_record.join(', '))}.` : null,
    s.regions?.length ? `Biogeographic provinces with a GBIF record: ${esc(s.regions.join(', '))}.` : null,
    s.family ? `Family: ${esc(s.family)}${s.order ? `; order: ${esc(s.order)}` : ''}.` : null,
  ].filter(Boolean).map(f => `<li>${f}</li>`).join('');
  const summary = `<noscript><div class="wrap" style="padding:16px 0">`
    + `<h1 class="page">${s.english ? `${esc(s.english)} ` : ''}<i>${esc(s.name)}</i></h1>`
    + `<p>${esc(sentences(s).join(' '))}</p><ul>${facts}</ul>`
    + `<p class="note">List of the week of ${esc(week)}. This page needs JavaScript to draw the map and lists. The same data is open without it: see <a href="/llms.txt">the data guide</a> and <a href="/method">Sources and method</a>. Data: CC BY 4.0, Sathya Sankaran; each source keeps its own licence. yellide is a monitor of public data, not an authority.</p>`
    + `</div></noscript>`;
  let out = html.replace(/<title>[^<]*<\/title>/, `<title>${title}</title>`);
  out = replaceMeta(out, 'name', 'description', desc);
  out = replaceMeta(out, 'property', 'og:title', title);
  out = replaceMeta(out, 'property', 'og:description', desc);
  out = out.replace(/<noscript>.*?<\/noscript>/s, summary);
  const json = JSON.stringify(ld).replace(/</g, '\\u003c');
  return out.replace('</head>', `<link rel="canonical" href="${url}">\n<meta property="og:url" content="${url}">\n`
    + `<script type="application/ld+json">${json}</script>\n</head>`);
}
