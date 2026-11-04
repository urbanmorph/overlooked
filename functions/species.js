// /species?key=...: the static species page with the species' own title, description and summary (lib/species_page.js),
// so search engines, AI crawlers and link previews see the species. With no key, or if the data cannot be read, the
// static page goes out unchanged: the browser draws the page from the data files either way.
import { lookupSpecies } from './lib/mcp.js';
import { speciesPage } from './lib/species_page.js';

export async function onRequest({ request, env, next }) {
  const key = new URL(request.url).searchParams.get('key');
  const page = await next();
  if (request.method !== 'GET' || !key || page.status !== 200 || !(page.headers.get('content-type') || '').includes('text/html')) return page;
  const html = await page.text();
  let found;
  try {
    found = await lookupSpecies(env, key);
  } catch {
    return new Response(html, { status: 200, headers: page.headers });
  }
  const headers = new Headers(page.headers);
  headers.delete('content-length');
  headers.delete('etag');
  return new Response(speciesPage(html, key, found), { status: found ? 200 : 404, headers });
}
