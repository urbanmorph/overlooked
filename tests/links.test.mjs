// Tests for the action links on the species page (site/assets/links.js). Run: node --test tests/links.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gbifKeyOf, gbifIndiaLinks, nextSteps } from '../site/assets/links.js';

test('GBIF key only for an exact match of the name', () => {
  assert.equal(gbifKeyOf({ matchType: 'EXACT', usageKey: 5 }), 5);
  assert.equal(gbifKeyOf({ matchType: 'EXACT', usageKey: 5, synonym: true, acceptedUsageKey: 7 }), 7);
  assert.equal(gbifKeyOf({ matchType: 'FUZZY', usageKey: 5 }), null);
  assert.equal(gbifKeyOf({ matchType: 'NONE' }), null);
  assert.equal(gbifKeyOf(null), null);
});

test('records from India, and the ones with no exact location when the species has that label', () => {
  const all = 'https://www.gbif.org/occurrence/search?country=IN&taxon_key=5';
  assert.deepEqual(gbifIndiaLinks(5, false).map(l => l.href), [all]);
  const links = gbifIndiaLinks(5, true);
  assert.deepEqual(links.map(l => l.href), [all, `${all}&has_coordinate=false`]);
  assert.deepEqual(gbifIndiaLinks(null, true), []);
});

const base = { status: 2, iucn: 'LC', codes: new Set(), wait: 0, identify: 'ID', gbifKey: 5, name: 'Aus bus', paper: null };
const steps = o => nextSteps({ ...base, ...o });
const texts = o => steps(o).map(s => s.text).join(' | ');

test('a species that nobody has observed: look for it and add the record', () => {
  const s = steps({ status: 0, iucn: 'NE', codes: new Set(['chk']) });
  assert.match(s[0].text, /No observation/);
  assert.ok(s[0].links.some(l => l.href.includes('inaturalist.org/observations/upload')));
  assert.match(texts({ status: 0, codes: new Set(['chk', 'nra']), paper: 'https://p' }), /since it was described/);
});

test('observed but not identified: identify on iNaturalist, or ask a specialist', () => {
  assert.equal(steps({ status: 1, wait: 3 })[0].links[0].href, 'ID');
  assert.match(steps({ status: 1, wait: 0 })[0].text, /specialist/);
});

test('records with no exact location: correct them on GBIF; flagged ones may not be from India', () => {
  const s = steps({ codes: new Set(['lnc', 'lfl']) }).find(x => /exact location/.test(x.text));
  assert.ok(s.links[0].href.endsWith('taxon_key=5&has_coordinate=false'));
  assert.match(s.text, /may not be from India/);
  assert.ok(!texts({ codes: new Set() }).includes('exact location'));
});

test('IUCN: not assessed, too little data, threatened', () => {
  assert.match(texts({ iucn: 'NE' }), /not assessed/);
  assert.match(texts({ iucn: 'NE', codes: new Set(['end']) }), /endemic to India/);
  assert.match(texts({ iucn: 'DD' }), /too little data/);
  assert.match(texts({ iucn: 'EN' }), /threatened/);
  assert.match(texts({ status: 0, iucn: 'NE' }), /not assessed/);
});

test('a name that does not match the Catalogue of Life: a taxonomist can check it', () => {
  assert.match(texts({ codes: new Set(['nm']) }), /Catalogue of Life/);
});

test('no step text uses words the site avoids', () => {
  const all = [0, 1, 2].flatMap(status => ['NE', 'DD', 'CR', 'LC'].map(iucn =>
    texts({ status, iucn, codes: new Set(['chk', 'nra', 'lnc', 'lco', 'lfl', 'end', 'nm']), paper: 'p' })));
  for (const t of all) assert.doesNotMatch(t, /missing|lost|extinct|quiet|—/i);
});

test('identified species with observations still waiting: the identify step stays', () => {
  assert.ok(steps({ status: 2, wait: 3 }).some(s => s.links.some(l => l.href === 'ID')));
});

test('one observation waits, several wait', () => {
  assert.match(texts({ status: 1, wait: 1 }), /^1 observation on iNaturalist waits for a name\. If you know the group, identify it\./);
  assert.match(texts({ status: 1, wait: 1200 }), /^1,200 observations on iNaturalist wait/);
});
