// Tests for the seven gaps in what we know (site/assets/gaps.js). Run: node --test tests/gaps.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { GAPS, gaps } from '../site/assets/gaps.js';

const cats = n => [0, 0, 0, 0, n, 0, 0, 0, 0];
const S = {
  recent_from: 2016, described_recent: [3, 1], dna: [10, 5],
  india: [[100, 60, cats(100), 3, 40, 15], [50, 20, cats(50), 1, 10, 2]],
};

test('the seven gaps of Hortal et al. (2015), in their order, each with a plain name and a question', () => {
  assert.deepEqual(GAPS.map(g => g.term), ['Linnean', 'Wallacean', 'Prestonian', 'Darwinian', 'Raunkiæran', 'Hutchinsonian', 'Eltonian']);
  for (const g of GAPS) assert.ok(g.plain && g.question && (g.measure || g.source), g.term);
});

test('what we measure today, for some groups: Linnean, Wallacean, Darwinian; the rest are not measured yet', () => {
  const by = Object.fromEntries(gaps(S, [0, 1]).map(g => [g.term, g]));
  assert.equal(by.Linnean.value, 4);
  assert.deepEqual([by.Wallacean.value, by.Wallacean.of], [17, 150]);
  assert.deepEqual([by.Darwinian.value, by.Darwinian.of], [15, 150]);
  assert.equal(by.Prestonian.value, null);
  assert.equal(gaps(S, [1]).find(g => g.term === 'Darwinian').value, 5);
});

test('a summary without a count leaves that gap unmeasured, not 0', () => {
  const old = { recent_from: 2016, india: [[100, 60, cats(100), 3]] };
  assert.ok(gaps(old, [0]).every(g => g.value == null));
});

test('the home page holds a row for every gap, with its terms, so nothing moves when the numbers fill', () => {
  const html = readFileSync(new URL('../site/index.html', import.meta.url), 'utf8');
  for (const g of GAPS) assert.ok(html.includes(`data-gap="${g.term}"`) && html.includes(`<b>${g.plain}</b>`), g.term);
});
