// /sitemaps/species-<i>.xml: the species pages for search engines, from the current master build in R2
// (pipeline/master.py sitemap_files). site/sitemap.xml is the index that names them.
const NAME = /^species-\d{1,2}\.xml$/;

export async function onRequest({ env, params }) {
  const name = String(params.name || '');
  const latest = NAME.test(name) ? await env.DATA.get('layers/master/latest.json') : null;
  const base = latest && (await latest.json()).base;
  const obj = base && (await env.DATA.get(`${base}sitemaps/${name}`));
  if (!obj) return new Response('Not found', { status: 404 });
  return new Response(obj.body, { headers: { 'Content-Type': 'application/xml; charset=utf-8', 'Cache-Control': 'public, max-age=3600' } });
}
