// Species pages for crawlers and readers with no JavaScript (functions/species.js, functions/lib/species_page.js): the
// static page with the species' own title, description, canonical address, share tags, schema.org Taxon and a plain
// summary in <noscript>. AI crawlers do not run JavaScript, so without this every species page reads "Species".
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { speciesPage } from '../functions/lib/species_page.js';
import { onRequest } from '../functions/species.js';

const HTML = readFileSync(new URL('../site/species.html', import.meta.url), 'utf8');
const S = { iucn: ['CR', 'EN', 'VU', 'NT', 'LC', 'DD', 'NE', 'EW', 'EX'] };
const BUSTARD = {
  key: 'GCMS', name: 'Ardeotis nigriceps', english: 'Great Indian Bustard', group: 'Birds', family: 'Otididae', order: 'Otidiformes',
  status: 'open record', open_record: true, iucn: { category: 'CR', year: 2018, doi: 'https://doi.org/x', trend: 'Decreasing' },
  endemic: false, sources: ['GBIF', 'iNaturalist', 'IUCN'], states_with_open_record: ['Rajasthan', 'Gujarat'],
  regions: ['3A Desert: Thar'], described: { year: 1831, authority: '(Vigors, 1831)' }, names_in_indian_languages: [['hi', 'सोन चिरैया']],
  url: 'https://overlooked-india.pages.dev/species?key=GCMS',
};
const page = (s = BUSTARD) => speciesPage(HTML, s.key, { S, s, week: '2026-11-02' });

test('title and description are the species\' own', () => {
  const h = page();
  assert.match(h, /<title>Great Indian Bustard \(Ardeotis nigriceps\) · Overlooked<\/title>/);
  const d = h.match(/<meta name="description" content="([^"]*)">/)[1];
  assert.equal(d, 'Great Indian Bustard (Ardeotis nigriceps), a species of India. IUCN Critically Endangered (2018, decreasing). '
    + 'Open records in 2 states. Listed by GBIF, iNaturalist and IUCN. Group: Birds. Updated each week.');
  assert.ok(h.includes(`<meta property="og:description" content="${d}">`));
  assert.ok(h.includes('<meta property="og:title" content="Great Indian Bustard (Ardeotis nigriceps) · Overlooked">'));
  assert.equal((h.match(/<title>/g) || []).length, 1);
});

test('canonical address with the key, and schema.org Taxon', () => {
  const h = page();
  assert.ok(h.includes('<link rel="canonical" href="https://overlooked-india.pages.dev/species?key=GCMS">'));
  assert.ok(h.includes('<meta property="og:url" content="https://overlooked-india.pages.dev/species?key=GCMS">'));
  const ld = JSON.parse(h.match(/<script type="application\/ld\+json">(.*?)<\/script>/s)[1]);
  assert.equal(ld['@type'], 'Taxon');
  assert.equal(ld.name, 'Ardeotis nigriceps');
  assert.equal(ld.taxonRank, 'species');
  assert.deepEqual(ld.alternateName, ['Great Indian Bustard', 'सोन चिरैया']);
  assert.deepEqual(ld.parentTaxon, { '@type': 'Taxon', name: 'Otididae', taxonRank: 'family' });
});

test('a plain summary for readers and crawlers with no JavaScript', () => {
  const ns = page().match(/<noscript>(.*?)<\/noscript>/s)[1];
  assert.match(ns, /<h1[^>]*>Great Indian Bustard <i>Ardeotis nigriceps<\/i><\/h1>/);
  assert.match(ns, /Rajasthan, Gujarat/);
  assert.match(ns, /3A Desert: Thar/);
  assert.match(ns, /\(Vigors, 1831\)/);
  assert.match(ns, /llms\.txt/);                       // the note on open data stays
});

test('no English name, not assessed, endemic; text is escaped; banned words never appear', () => {
  const s = { ...BUSTARD, key: 'K<1', name: 'Aus "bus"', english: null, iucn: { category: 'EX' }, endemic: true,
    states_with_open_record: [], open_record: false, regions: null, names_in_indian_languages: null };
  const h = page(s);
  assert.match(h, /<title>Aus &quot;bus&quot; · Overlooked<\/title>/);
  assert.match(h, /Endemic to India\./);
  assert.match(h, /IUCN category EX/);
  assert.match(h, /No open record from India yet\./);
  assert.ok(h.includes('"name":"Aus \\"bus\\""'));                 // JSON-LD keeps the quotes escaped
  const ns = h.match(/<noscript>(.*?)<\/noscript>/s)[1];
  for (const t of [h.match(/<title>(.*?)<\/title>/)[1], h.match(/<meta name="description" content="([^"]*)">/)[1], ns]) {
    assert.doesNotMatch(t, /extinct|missing|lost|quiet|—/i);
  }
});

test('an unknown key: the page as it is, marked noindex', () => {
  const h = speciesPage(HTML, 'NOPE', null);
  assert.ok(h.includes('<meta name="robots" content="noindex">'));
  assert.match(h, /<title>Species · Overlooked<\/title>/);
});

test('the function: no key passes through; a key fills the page; a data failure still serves the page', async () => {
  const asset = () => new Response(HTML, { headers: { 'content-type': 'text/html; charset=utf-8', etag: '"x"' } });
  const plain = await onRequest({ request: new Request('https://x/species'), env: {}, next: asset });
  assert.match(await plain.text(), /<title>Species · Overlooked<\/title>/);
  const broken = { DATA: { get: async () => { throw new Error('R2 down'); } } };
  const r = await onRequest({ request: new Request('https://x/species?key=GCMS'), env: broken, next: asset });
  assert.equal(r.status, 200);
  assert.match(await r.text(), /<title>Species · Overlooked<\/title>/);
});

import { onRequest as sitemap } from '../functions/sitemaps/[name].js';

test('species sitemaps come from the current build in R2; other names are not served', async () => {
  const store = { 'layers/master/latest.json': '{"base":"layers/master/w/b/"}', 'layers/master/w/b/sitemaps/species-0.xml': '<urlset/>' };
  const env = { DATA: { get: async k => (k in store ? { text: async () => store[k], json: async () => JSON.parse(store[k]), body: store[k] } : null) } };
  const ask = name => sitemap({ request: new Request(`https://x/sitemaps/${name}`), env, params: { name } });
  const r = await ask('species-0.xml');
  assert.equal(r.status, 200);
  assert.match(r.headers.get('content-type'), /xml/);
  assert.equal(await r.text(), '<urlset/>');
  assert.equal((await ask('species-4.xml')).status, 404);
  assert.equal((await ask('../latest.json')).status, 404);
  const index = readFileSync(new URL('../site/sitemap.xml', import.meta.url), 'utf8');
  for (let i = 0; i < 5; i++) assert.ok(index.includes(`https://overlooked-india.pages.dev/sitemaps/species-${i}.xml`));
  assert.ok(index.includes('https://overlooked-india.pages.dev/sitemap-pages.xml') && index.includes('<sitemapindex'));
});
