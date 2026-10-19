// Tests for the action links on the species page (site/assets/links.js). Run: node --test tests/links.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { gbifKeyOf, gbifIndiaLinks } from '../site/assets/links.js';

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
