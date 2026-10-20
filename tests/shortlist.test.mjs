// Tests for the shortlist page helpers (site/assets/shortlist.js). Run: node --test tests/shortlist.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { shortlistOf, filterRows, bandCounts, goHref, photoCredit, taxonHTML, groupFiles } from '../site/assets/shortlist.js';

const FIX = new URL('./fixtures/shortlist/layers/shortlist/', import.meta.url);
const latest = JSON.parse(readFileSync(new URL('latest.json', FIX)));
const bugs = JSON.parse(readFileSync(new URL(`${latest.run}/g/true-bugs.json`, FIX))).rows;

const row = (kw = {}) => ({ id: 1, band: 'quick', names: ['A b', 'A c', 'A d', 'A e'], genera: ['A', 'B', 'C', 'D', 'E', 'F'], state: '29', ...kw });

test('shortlistOf: Quick to confirm shows up to 3 species in order', () => {
  assert.deepEqual(shortlistOf(row()), { band: 'quick', label: 'Quick to confirm', rank: 'species', names: ['A b', 'A c', 'A d'] });
});

test('shortlistOf: Genus first shows up to 5 genera in order', () => {
  assert.deepEqual(shortlistOf(row({ band: 'genus', names: [] })), { band: 'genus', label: 'Genus first', rank: 'genus', names: ['A', 'B', 'C', 'D', 'E'] });
});

test('shortlistOf: expert rows, unknown bands and empty lists are not shown', () => {
  assert.equal(shortlistOf(row({ band: 'expert' })), null);
  assert.equal(shortlistOf(row({ band: 'p=0.93' })), null);
  assert.equal(shortlistOf(row({ names: [] })), null);
  assert.equal(shortlistOf(row({ band: 'genus', genera: [] })), null);
});

test('filterRows: drops rows that are not shown, keeps the file order, filters by state and band', () => {
  const shown = filterRows(bugs, {});
  assert.ok(shown.length > 0 && shown.length < bugs.length);
  assert.ok(shown.every(r => r.band !== 'expert'));
  assert.deepEqual(shown.map(r => r.id), bugs.filter(r => r.band !== 'expert').map(r => r.id));
  assert.ok(filterRows(bugs, { state: '33' }).every(r => r.state === '33'));
  assert.ok(filterRows(bugs, { band: 'genus' }).every(r => r.band === 'genus'));
  assert.deepEqual(filterRows(bugs, { state: '99' }), []);
});

test('bandCounts: shown rows per band, for the bands the page offers', () => {
  const c = bandCounts(bugs);
  assert.equal(c.quick + c.genus, filterRows(bugs, {}).length);
  assert.equal(c.expert, undefined);
  assert.deepEqual(bandCounts([]), { quick: 0, genus: 0 });
});

test('goHref: the counted redirect, only for a numeric observation id and a clean group key', () => {
  assert.equal(goHref(123456789, 'true-bugs'), '/go/inat/123456789?g=true-bugs');
  assert.equal(goHref('42', 'birds'), '/go/inat/42?g=birds');
  assert.equal(goHref(42, 'Bad Key!'), '/go/inat/42');
  assert.equal(goHref('12a', 'birds'), null);
  assert.equal(goHref(-1, 'birds'), null);
  assert.equal(goHref(null, 'birds'), null);
});

test('photoCredit: the attribution as given, plus the licence when the text does not name it; escaped', () => {
  assert.equal(photoCredit({ attribution: '(c) Ann, some rights reserved (CC BY)', licence: 'cc-by' }), 'Photo (c) Ann, some rights reserved (CC BY)');
  assert.equal(photoCredit({ attribution: '(c) Ann', licence: 'cc-by-nc' }), 'Photo (c) Ann · CC BY-NC');
  assert.equal(photoCredit({ attribution: 'Ann <b>', licence: 'cc0' }), 'Photo Ann &lt;b&gt; · CC0');
  assert.equal(photoCredit({ attribution: '', licence: null }), 'Photo: author on iNaturalist');
});

test('taxonHTML: genus and below in italics; higher ranks name the rank', () => {
  assert.equal(taxonHTML({ name: 'Halyomorpha halys', rank: 'species' }), '<i>Halyomorpha halys</i>');
  assert.equal(taxonHTML({ name: 'Halyomorpha', rank: 'genus' }), '<i>Halyomorpha</i> (genus)');
  assert.equal(taxonHTML({ name: 'Pentatomidae', rank: 'family' }), 'Pentatomidae (family)');
  assert.equal(taxonHTML({ name: '<x>', rank: 'species' }), '<i>&lt;x&gt;</i>');
  assert.equal(taxonHTML(null), 'No name yet');
});

test('fixture follows the contract: groups, keys, bands, list lengths', () => {
  assert.match(latest.run, /^\d{4}-\d{2}-\d{2}$/);
  for (const g of latest.groups) {
    assert.match(g.key, /^[a-z]+(-[a-z]+)*$/);
    assert.ok(['Quick to confirm', 'Genus first'].includes(g.verdict));
  }
  for (const r of bugs) {
    assert.ok(['quick', 'genus', 'expert'].includes(r.band));
    assert.ok(r.names.length <= 3 && r.genera.length <= 5);
    assert.ok(r.state === null || /^\d{1,3}$/.test(r.state));
  }
});

test('groupFiles: every page file of a group, the first without a number', () => {
  assert.deepEqual(groupFiles('2026-10-20', { key: 'true-bugs', pages: 2 }),
    ['layers/shortlist/2026-10-20/g/true-bugs.json', 'layers/shortlist/2026-10-20/g/true-bugs.2.json']);
  assert.deepEqual(groupFiles('2026-10-20', { key: 'birds' }), ['layers/shortlist/2026-10-20/g/birds.json']);
  assert.deepEqual(groupFiles('2026-10-20', null), []);
});
