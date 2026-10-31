// Tests for the seven gaps in what we know (site/assets/gaps.js). Run: node --test tests/gaps.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { GAPS, gaps, gapAbsent } from '../site/assets/gaps.js';

const cats = n => [0, 0, 0, 0, n, 0, 0, 0, 0];
// gaps_known: per group, the documented species where each gap is known (pipeline/master.py), the same counts the
// species page uses for its group bars.
const S = {
  recent_from: 2016, described_recent: [3, 1], interactions: [40, 9],
  india: [[100, 60, cats(100), 3, 40, 15], [50, 20, cats(50), 1, 10, 2]],
  gaps_known: [[90, 15, null, 10, 7, 20, 12], [45, 2, 8, 5, 2, 4, 3]],
};

test('the seven gaps of Hortal et al. (2015), in their order, each with a plain name and a question', () => {
  assert.deepEqual(GAPS.map(g => g.term), ['Linnean', 'Wallacean', 'Prestonian', 'Darwinian', 'Raunkiæran', 'Hutchinsonian', 'Eltonian']);
  for (const g of GAPS) assert.ok(g.plain && g.question, g.term);
});

test('each gap, for some groups: the documented species where it is known, over the documented species of the groups that measure it', () => {
  const by = Object.fromEntries(gaps(S, [0, 1]).map(g => [g.term, g]));
  assert.deepEqual([by.Linnean.value, by.Linnean.of], [135, 150]);
  assert.match(by.Linnean.note, /4 described since 2016/);
  assert.deepEqual([by.Wallacean.value, by.Wallacean.of], [17, 150]);
  assert.deepEqual([by.Prestonian.value, by.Prestonian.of], [8, 50]);      // the measured group only
  assert.match(by.Prestonian.note, /1 of the 2 groups/);
  assert.deepEqual([by.Darwinian.value, by.Darwinian.of], [15, 150]);
  assert.deepEqual([by['Raunkiæran'].value, by.Hutchinsonian.value, by.Eltonian.value], [9, 24, 15]);
  assert.match(by.Eltonian.note, /49 .*anywhere/);
  assert.equal(gaps(S, [0]).find(g => g.term === 'Prestonian').value, null);   // no measured group chosen
  assert.equal(gaps(S, [1]).find(g => g.term === 'Darwinian').value, 5);
});

test('a summary without the counts leaves every gap unmeasured, not 0', () => {
  assert.ok(gaps({ recent_from: 2016, india: [[100, 60, cats(100), 3]] }, [0]).every(g => g.value == null));
});

test('the home page holds the pyramid with a block for every gap, so nothing moves when the numbers fill', () => {
  const html = readFileSync(new URL('../site/index.html', import.meta.url), 'utf8');
  assert.match(html, /class="pyr" id="gaps"/);
  GAPS.forEach((g, i) => assert.ok(html.includes(`data-i="${i}"`) && html.includes(`<span class="t">${g.plain}</span>`), g.term));
});

test('gapAbsent: a gap not measured yet gives its data source', () => {
  const by = Object.fromEntries(gaps(S, [0]).map(g => [g.term, g]));
  assert.equal(gapAbsent(by.Prestonian), 'Not measured yet for these groups. Data: IUCN Red List population trends (IUCN 2026, version 2026-1); State of India\u2019s Birds for birds.');
});

test('the Linnean and Darwinian notes add type specimens, local names and barcodes when the list measures them', () => {
  const S = { recent_from: 2016, described_recent: [3, 1], india: [[10, 5, [], 0, 4, 2], [5, 2, [], 0, 1, 1]],
    gaps_known: [[9, 2, null, 2, 0, 0, 0], [5, 1, null, 0, 0, 0, 0]], types: [4, 1], local_names: [6, 0], barcodes: [7, 2], barcodes_india: [3, 1] };
  const [lin, , , dar] = gaps(S, [0, 1]);
  assert.match(lin.note, /5 have a type specimen from India on GBIF; 6 have a name in an Indian language/);
  assert.match(dar.note, /9 have a DNA barcode on BOLD \(4 from India\)/);
  const old = gaps({ ...S, types: undefined, barcodes: undefined }, [0, 1]);
  assert.doesNotMatch(old[0].note, /type specimen/);
  assert.doesNotMatch(old[3].note, /barcode on BOLD \(/);
});
