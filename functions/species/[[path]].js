// Species pages. /species/<key>/<slug> is a species page at its own address, filled with its title, description,
// summary and schema.org Taxon (lib/species_page.js) so search engines and AI crawlers read the species without
// JavaScript. A missing or wrong slug, a trailing slash or extra parts send to the right address for good, and so
// does the old address, /species?key=<key> (this file also answers /species: Pages routes it here). An unknown key
// is a 404 page marked noindex; /species with no key is the static page. If the data cannot be read, the static page
// goes out: the browser draws it from the address.
import { lookupSpecies } from '../lib/mcp.js';
import { speciesPage } from '../lib/species_page.js';
import { speciesPath } from '../../site/assets/species_url.js';

const HTML_HEADERS = { 'content-type': 'text/html; charset=utf-8' };

/** The answer for one request; `asset()` gives the static species page, `lookup` finds the species. */
export async function handle(request, env, asset, lookup = lookupSpecies) {
  const url = new URL(request.url);
  let key;
  try {
    key = decodeURIComponent(url.pathname.split('/')[2] || '');
  } catch {
    key = '';
  }
  const old = !key && url.searchParams.get('key');
  if (!key && !old) return asset();
  let found;
  try {
    found = await lookup(env, key || old);
  } catch {
    return new Response(await (await asset()).text(), { status: 200, headers: HTML_HEADERS });
  }
  const html = await (await asset()).text();
  if (!found) return new Response(speciesPage(html, key || old, null), { status: 404, headers: HTML_HEADERS });
  const path = speciesPath(key || old, found.s.name);
  if (url.pathname !== path) return Response.redirect(url.origin + path, 301);
  return new Response(speciesPage(html, key, found), { status: 200, headers: HTML_HEADERS });
}

export function onRequest({ request, env }) {
  if (request.method !== 'GET' && request.method !== 'HEAD') return new Response('Method not allowed', { status: 405 });
  return handle(request, env, () => env.ASSETS.fetch(new URL('/species', request.url)));
}
