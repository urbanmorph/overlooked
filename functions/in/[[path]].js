// The place pages: /in (every place), /in/<place> (its groups) and /in/<place>/<group> ("Birds of Kerala"), written
// in the HTML (lib/place_page.js) from the current week's agent index (lib/mcp.js). A trailing slash or extra parts
// send to the page for good; an unknown place or group is a noindex 404; if the data cannot be read, a 503.
import { placeCounts, speciesWhere } from '../lib/mcp.js';
import { groupPage, notFound, placeHub, placesIndex } from '../lib/place_page.js';
import { groupSlug, placePath, places } from '../lib/places.js';

const HEADERS = { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'public, max-age=3600' };
const page = (html, status = 200) => new Response(html, { status, headers: HEADERS });

/** The answer for one request; `asset()` gives the shell (site/in.html), `data` reads the list. */
export async function handle(request, env, asset, data = { where: speciesWhere, counts: placeCounts }) {
  const url = new URL(request.url);
  const parts = url.pathname.split('/').slice(2);              // ['', 'in', place, group, ...] -> [place, group, ...]
  const shell = async () => (await asset()).text();
  let C;
  try {
    C = await data.counts(env);
  } catch {
    return new Response('The list cannot be read just now. Try again in a few minutes.', { status: 503, headers: { 'retry-after': '300' } });
  }
  const place = parts[0] ? places(C.S, C.districts).find(p => p.slug === parts[0]) : null;
  const gi = place && parts[1] ? C.S.groups.findIndex(g => groupSlug(g) === parts[1]) : -1;
  if ((parts[0] && !place) || (parts[1] && gi < 0)) return page(notFound(await shell()), 404);
  const want = placePath(place, gi >= 0 ? C.S.groups[gi] : null);
  if (url.pathname !== want) return Response.redirect(url.origin + want, 301);
  try {
    if (!place) return page(placesIndex(await shell(), { C }));
    const d = await data.where(env, { ...place.filter, ...(gi >= 0 ? { group: C.S.groups[gi] } : {}) });
    return page(gi >= 0 ? groupPage(await shell(), { place, gi, d, C }) : placeHub(await shell(), { place, d, C }));
  } catch {
    return new Response('The list cannot be read just now. Try again in a few minutes.', { status: 503, headers: { 'retry-after': '300' } });
  }
}

export function onRequest({ request, env }) {
  if (request.method !== 'GET' && request.method !== 'HEAD') return new Response('Method not allowed', { status: 405 });
  return handle(request, env, () => env.ASSETS.fetch(new URL('/in', request.url)));
}
