// The site moved to yellide.com on 11 Nov 2026 (functions/_middleware.js). Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { onRequest } from '../functions/_middleware.js';

const visit = async (url) => {
  let served = false;
  const r = await onRequest({ request: new Request(url), env: {}, waitUntil() {},
    next: async () => { served = true; return new Response('page', { headers: { 'content-type': 'text/html' } }); } });
  return { r, served };
};

test('the old address and www send every page, query included, to the same page on yellide.com, for good', async () => {
  for (const [from, to] of [
    ['https://overlooked-india.pages.dev/', 'https://yellide.com/'],
    ['https://overlooked-india.pages.dev/species?key=3233T', 'https://yellide.com/species?key=3233T'],
    ['http://overlooked-india.pages.dev/method.html#sources', 'https://yellide.com/method.html'],
    ['https://www.yellide.com/?view=waiting', 'https://yellide.com/?view=waiting'],
    ['https://overlooked-india.pages.dev/sitemaps/species-0.xml', 'https://yellide.com/sitemaps/species-0.xml']]) {
    const { r, served } = await visit(from);
    assert.equal(r.status, 301, from);
    assert.equal(r.headers.get('location'), to);
    assert.equal(served, false);
  }
});

test('yellide.com itself and preview deployments are served as they are', async () => {
  for (const url of ['https://yellide.com/species?key=1', 'https://abc123.overlooked-india.pages.dev/', 'http://localhost:8788/']) {
    const { r, served } = await visit(url);
    assert.equal(served, true, url);
    assert.equal(r.status, 200);
  }
});

test('robots and sitemaps go through the redirect; the old property\'s verification file stays put', () => {
  const ex = JSON.parse(fs.readFileSync(new URL('../site/_routes.json', import.meta.url), 'utf8')).exclude;
  for (const f of ['/robots.txt', '/sitemap.xml', '/sitemap-pages.xml']) assert.ok(!ex.includes(f), f);
  assert.ok(ex.some((f) => /^\/google[0-9a-f]+\.html$/.test(f)));
});

test('nothing on the site or in the code names the old address any more', () => {
  const files = ['functions/lib/mcp.js', 'functions/lib/species_page.js', 'pipeline/master.py', 'pipeline/site_data.py', 'scripts/pages.py',
    'site/index.html', 'site/species.html', 'site/robots.txt', 'site/sitemap.xml', 'site/sitemap-pages.xml', 'site/llms.txt', 'site/mcp.html'];
  for (const f of files) assert.ok(!fs.readFileSync(new URL('../' + f, import.meta.url), 'utf8').includes('overlooked-india.pages.dev'), f);
});
