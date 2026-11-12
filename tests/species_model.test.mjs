// Tests for the one way the site and the agent server read and show a species (site/assets/species_model.js).
// Run: node --test tests/species_model.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { esc, iucnBadge, speciesName, speciesText, speciesTitle, speciesInline, model, shardOf, hashOf, englishOf, fillEnglish } from '../site/assets/species_model.js';

// The summary parts the model reads, as pipeline/master.py site_files writes them (tests/test_master.py keeps the
// fixture equal to the pipeline's), with two labels.
const fx = JSON.parse(readFileSync(new URL('./fixtures/summary_model.json', import.meta.url)));
export const S = { ...fx, labels: [{ code: 'rg' }, { code: 'end' }] };

test('esc: the five characters HTML gives a meaning to', () => {
  assert.equal(esc(`<a href="x">'&'</a>`), '&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;');
  assert.equal(esc(null), '');
});

test('speciesName: the Latin name in italics, linked to its page when it has a key, the English name under it', () => {
  assert.equal(speciesName('4Q 7', 'Aus bus'), '<a href="/species/4Q%207/aus-bus"><i>Aus bus</i></a><span class="en" data-en="4Q 7"></span>');
  assert.equal(speciesName('K1', 'Aus bus', 'Common <aus>'), '<a href="/species/K1/aus-bus"><i>Aus bus</i></a><span class="en">Common &lt;aus&gt;</span>');
  assert.equal(speciesName('K1', 'Aus bus', null), '<a href="/species/K1/aus-bus"><i>Aus bus</i></a>');   // known: no English name
  assert.equal(speciesName('', 'Aus <b>'), '<i>Aus &lt;b&gt;</i>');
  assert.equal(speciesName('K1', 'Aus bus', 'Common aus', iucnBadge('EN')),           // a badge on the line of the Latin name
    '<a href="/species/K1/aus-bus"><i>Aus bus</i></a> <span class="iucn i-EN" title="IUCN Red List">EN</span><span class="en">Common aus</span>');                                         // no key: no page, no lookup
});

test('speciesText: the same as speciesName without the link, for a place that is a link itself', () => {
  assert.equal(speciesText('Aus bus', 'Common aus'), '<i>Aus bus</i><span class="en">Common aus</span>');
  assert.equal(speciesText('Aus bus'), '<i>Aus bus</i>');
});

test('speciesTitle: "English (Latin)" in plain text, else the Latin name', () => {
  assert.equal(speciesTitle('Panthera pardus', 'Leopard'), 'Leopard (Panthera pardus)');
  assert.equal(speciesTitle('Aus bus', null), 'Aus bus');
});

test('speciesInline: a species inside a sentence, "English (<i>Latin</i>)", escaped', () => {
  assert.equal(speciesInline('Aus bus', 'Common <aus>'), 'Common &lt;aus&gt; (<i>Aus bus</i>)');
  assert.equal(speciesInline('Aus bus'), '<i>Aus bus</i>');
});

test('iucnBadge: the category, "Not assessed" for NE', () => {
  assert.equal(iucnBadge('EN'), '<span class="iucn i-EN" title="IUCN Red List">EN</span>');
  assert.match(iucnBadge('NE'), />Not assessed</);
});

test('model: every field of a row by name, from the field names the list publishes', () => {
  const m = model(S);
  const row = ['K1', 'Aus bus', 9, 1, 1, 2, 4, 1758, 2020, null, null, 0, 'Common aus'];
  assert.equal(row[m.g.english], 'Common aus');
  assert.equal(row[m.g.year], 1758);
  assert.equal(m.search.latin, 8);
  assert.deepEqual(m.read('g', row).name, 'Aus bus');
  assert.throws(() => m.g.nosuch.toString());
});

test('model: the words and the rules for status, IUCN, threatened and endemic, from the list', () => {
  const m = model(S);
  assert.equal(m.status(2), 'Not on the India list yet: waits for a name');
  assert.equal(m.iucnName('CR'), 'Critically Endangered');
  assert.equal(m.iucnName('EW'), 'EW');
  assert.equal(m.threatenedWords, 'Critically Endangered, Endangered or Vulnerable');                               // no word: the code
  assert.equal(m.threatened('VU'), true);
  assert.equal(m.threatened('NT'), false);
  assert.equal(m.threatenedAt(1), true);                              // by index into S.iucn
  assert.equal(m.endemic(0b10), true);
  assert.equal(m.endemic(0b01), false);
  assert.equal(model({ ...S, labels: [{ code: 'rg' }] }).endemic(0b10), false);   // a list with no endemic label
});

test('model: a list without field names cannot be read, so no page reads a field by a guessed position', () => {
  assert.throws(() => model({ ...S, fields: undefined }), /fields/);
});

test('shardOf: FNV-1a of the key, as pipeline/site_data.py shard_of (512 shards; hashOf for other counts)', () => {
  assert.equal(shardOf('K1'), 97);
  assert.equal(hashOf('K1') % 64, 33);
  assert.deepEqual(['K1', 'K1'].map(shardOf), [97, 97]);   // safe in map: no second argument
});

test('englishOf: the English names of some keys, one request per shard they fall in', async () => {
  const asked = [];
  const get = async path => { asked.push(path); return { K1: 'Common aus', K9: 'Other' }; };
  const names = await englishOf(get, 'B/', S, ['K1', 'K1', 'K2', '']);
  assert.deepEqual([...names], [['K1', 'Common aus']]);
  assert.deepEqual(asked, [`B/en/${hashOf('K1') % 64}.json`, `B/en/${hashOf('K2') % 64}.json`].filter((p, i, a) => a.indexOf(p) === i));
});

test('englishOf: a list with no English-name files gives no names, and the page still shows', async () => {
  const names = await englishOf(async () => { throw new Error('404'); }, 'B/', S, ['K1']);
  assert.equal(names.size, 0);
});

test('fillEnglish: each empty English-name slot gets its name, or goes when there is none', async () => {
  const slot = key => ({ dataset: { en: key }, textContent: '', gone: false, remove() { this.gone = true; } });
  const a = slot('K1'), b = slot('K2');
  const root = { querySelectorAll: sel => (sel === '[data-en]' ? [a, b] : []) };
  await fillEnglish(root, async () => ({ K1: 'Common aus' }), 'B/', S);
  assert.equal(a.textContent, 'Common aus');
  assert.equal(b.gone, true);
});
