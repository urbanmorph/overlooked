// Helpers the server-drawn pages share (functions/lib/html.js): species pages and place pages.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { andList, replaceMeta } from '../functions/lib/html.js';
import { readFileSync } from 'node:fs';

test('andList joins names the way a sentence does', () => {
  assert.equal(andList([]), '');
  assert.equal(andList(['GBIF']), 'GBIF');
  assert.equal(andList(['GBIF', 'IUCN']), 'GBIF and IUCN');
  assert.equal(andList(['GBIF', 'iNaturalist', 'IUCN']), 'GBIF, iNaturalist and IUCN');
});

test('replaceMeta sets one meta tag and keeps a $ in the value as it is', () => {
  const html = '<meta name="description" content="old"><meta property="og:title" content="x">';
  assert.equal(replaceMeta(html, 'name', 'description', 'Costs $1 & $& more'),
    '<meta name="description" content="Costs $1 & $& more"><meta property="og:title" content="x">');
});

test('the species and place pages take these helpers from html.js, not their own copies', () => {
  for (const f of ['species_page.js', 'place_page.js']) {
    const s = readFileSync(new URL(`../functions/lib/${f}`, import.meta.url), 'utf8');
    assert.doesNotMatch(s, /function replaceMeta|const list = /, f);
    assert.match(s, /from '\.\/html\.js'/, f);
  }
});
