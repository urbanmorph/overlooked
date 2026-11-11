// A species page lives at /species/<key>/<slug of its Latin name> (site/assets/species_url.js); /species?key= and a
// wrong slug send there for good (functions/species/[[path]].js, which Pages also routes /species to). Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { slug, speciesPath } from '../site/assets/species_url.js';
import { handle } from '../functions/species/[[path]].js';

const SLUGS = JSON.parse(readFileSync(new URL('./fixtures/species_slugs.json', import.meta.url), 'utf8'));
const HTML = readFileSync(new URL('../site/species.html', import.meta.url), 'utf8');
const S = { iucn: ['CR', 'EN', 'VU', 'NT', 'LC', 'DD', 'NE'] };
const BUSTARD = { key: 'GCMS', name: 'Ardeotis nigriceps', english: 'Great Indian Bustard', group: 'Birds', family: 'Otididae',
  iucn: { category: 'CR', year: 2018 }, sources: ['GBIF'], states_with_open_record: ['Rajasthan'] };
const lookup = async (env, key) => (key === 'GCMS' ? { S, s: BUSTARD, week: '2026-11-09' } : null);
const asset = async () => new Response(HTML, { headers: { 'content-type': 'text/html; charset=utf-8' } });

test('the slug: the Latin name in lower case, accents dropped, anything else one hyphen (the same in Python)', () => {
  for (const [name, want] of SLUGS) assert.equal(slug(name), want, name);
  assert.equal(speciesPath('GCMS', 'Ardeotis nigriceps'), '/species/GCMS/ardeotis-nigriceps');
  assert.equal(speciesPath('a/b', 'X y'), '/species/a%2Fb/x-y');
  assert.equal(speciesPath('K1', ''), '/species/K1');
});

test('a species page at its address: the filled page, with the name in the heading and a summary anyone can read', async () => {
  const r = await handle(new Request('https://yellide.com/species/GCMS/ardeotis-nigriceps'), {}, asset, lookup);
  assert.equal(r.status, 200);
  const h = await r.text();
  assert.ok(h.includes('<link rel="canonical" href="https://yellide.com/species/GCMS/ardeotis-nigriceps">'));
  assert.match(h, /<h1 class="page" id="name"[^>]*>Ardeotis nigriceps<\/h1>/);
  assert.equal((h.match(/<h1\b/g) || []).length, 1, 'one heading');
  assert.match(h, /<p class="note" id="summary"[^>]*>Great Indian Bustard \(Ardeotis nigriceps\), a species of India\. IUCN Critically Endangered/);
});

test('a wrong or missing slug, or a trailing slash, sends to the right address for good; an unknown key is a 404 page', async () => {
  for (const p of ['/species/GCMS', '/species/GCMS/', '/species/GCMS/otis-tarda', '/species/GCMS/ardeotis-nigriceps/', '/species/GCMS/x/y']) {
    const r = await handle(new Request('https://yellide.com' + p), {}, asset, lookup);
    assert.equal(r.status, 301, p);
    assert.equal(r.headers.get('location'), 'https://yellide.com/species/GCMS/ardeotis-nigriceps', p);
  }
  const r = await handle(new Request('https://yellide.com/species/NOPE/x'), {}, asset, lookup);
  assert.equal(r.status, 404);
  assert.ok((await r.text()).includes('<meta name="robots" content="noindex">'));
});

test('when the data cannot be read, the page still serves and draws itself from the address', async () => {
  const r = await handle(new Request('https://yellide.com/species/GCMS/ardeotis-nigriceps'), {}, asset, async () => { throw new Error('R2 down'); });
  assert.equal(r.status, 200);
  assert.match(await r.text(), /<title>Species · yellide<\/title>/);
  assert.match(readFileSync(new URL('../site/assets/species.js', import.meta.url), 'utf8'), /location\.pathname/);
});

test('/species?key= sends to the species address for good; no key or an unknown key serves the page as before', async () => {
  const ask = q => handle(new Request('https://yellide.com/species' + q), {}, asset, lookup);
  const r = await ask('?key=GCMS');
  assert.equal(r.status, 301);
  assert.equal(r.headers.get('location'), 'https://yellide.com/species/GCMS/ardeotis-nigriceps');
  const plain = await ask('');
  assert.equal(plain.status, 200);
  assert.match(await plain.text(), /<title>Species · yellide<\/title>/);
  const unknown = await ask('?key=NOPE');
  assert.equal(unknown.status, 404);
});

test('links inside the site and in MCP answers go straight to the species address', () => {
  for (const f of ['site/assets/common.js', 'site/assets/species.js', 'site/assets/explore.js', 'site/assets/review.js', 'functions/lib/mcp.js', 'functions/lib/species_page.js'])
    assert.ok(!readFileSync(new URL('../' + f, import.meta.url), 'utf8').includes('species?key='), f);
});
