// /sitemaps/species-<i>.xml: the species pages for search engines, from the current master build in R2
// (pipeline/master.py sitemap_files). /sitemaps/places.xml: the place pages worth indexing (/in, each place and each
// group in a place with MIN_SPECIES species or more), from the week's agent index. /sitemaps/priority.xml: the hubs to
// crawl first (/in, India and each state, with their groups) and the critically endangered and endangered species
// with an open record and an English name, about 2,000 URLs. site/sitemap.xml names them all.
import { placeCounts, speciesWhere } from '../lib/mcp.js';
import { speciesPath } from '../../site/assets/species_model.js';
import { MIN_SPECIES, countsOf, placePath, places } from '../lib/places.js';

const NAME = /^species-\d{1,2}\.xml$/;
const XML = { 'Content-Type': 'application/xml; charset=utf-8', 'Cache-Control': 'public, max-age=3600' };
const urlset = paths => `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n`
  + paths.map(p => `<url><loc>https://yellide.com${p}</loc></url>\n`).join('') + '</urlset>\n';

async function placesSitemap(env, counts) {
  const C = await counts(env), paths = ['/in'];
  for (const p of places(C.S, C.districts)) {
    const c = countsOf(C, p);
    if (c.reduce((a, b) => a + b, 0) < MIN_SPECIES) continue;
    paths.push(placePath(p));
    C.S.groups.forEach((g, i) => { if (c[i] >= MIN_SPECIES) paths.push(placePath(p, g)); });
  }
  return new Response(urlset(paths), { headers: XML });
}

async function prioritySitemap(env, counts, where) {
  const C = await counts(env), paths = ['/in'];
  for (const p of places(C.S).filter(x => x.kind === 'india' || x.kind === 'state')) {
    const c = countsOf(C, p);
    if (c.reduce((a, b) => a + b, 0) < MIN_SPECIES) continue;
    paths.push(placePath(p));
    C.S.groups.forEach((g, i) => { if (c[i] >= MIN_SPECIES) paths.push(placePath(p, g)); });
  }
  const { rows } = await where(env, { iucn: ['CR', 'EN'], open_record: true });
  for (const s of rows) if (s.english && s.open && (s.iucn === 'CR' || s.iucn === 'EN')) paths.push(speciesPath(s.key, s.name));
  return new Response(urlset(paths), { headers: XML });
}

export async function onRequest({ env, params, counts = placeCounts, where = speciesWhere }) {
  const name = String(params.name || '');
  if (name === 'places.xml' || name === 'priority.xml') {
    try {
      return await (name === 'places.xml' ? placesSitemap(env, counts) : prioritySitemap(env, counts, where));
    } catch {
      return new Response('Not available just now', { status: 503, headers: { 'retry-after': '300' } });
    }
  }
  const latest = NAME.test(name) ? await env.DATA.get('layers/master/latest.json') : null;
  const base = latest && (await latest.json()).base;
  const obj = base && (await env.DATA.get(`${base}sitemaps/${name}`));
  if (!obj) return new Response('Not found', { status: 404 });
  return new Response(obj.body, { headers: XML });
}
