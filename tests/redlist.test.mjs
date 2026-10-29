// Tests for the Red List assessment gaps (site/assets/redlist.js). Run: node --test tests/redlist.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { REDLIST, redlist } from '../site/assets/redlist.js';

const cats = n => [0, 0, 0, 0, n, 0, 0, 0, 0];
const S = {
  recent_from: 2016,
  india: [[100, 60, cats(100), 3, 40, 15], [50, 20, cats(50), 1, 10, 2]],
  redlist: { assessed: [30, 5], assessable: [7, 1], out_of_date: [10, 2], dd_newer: [2, 0], threatened_not_recent: [1, 1], endemic_not_assessed: [4, 0] },
};

test('a row per count, in the order of summary.json, summed over the chosen groups', () => {
  assert.deepEqual(REDLIST.map(r => r.key), ['assessed', 'assessable', 'out_of_date', 'dd_newer', 'threatened_not_recent', 'endemic_not_assessed']);
  const rows = redlist(S, [0, 1]);
  assert.deepEqual(rows.map(r => r.value), [35, 8, 12, 2, 2, 4]);
  assert.equal(rows[0].of, 150);                                   // assessed: a share of the documented species
  assert.match(rows[2].label, /before 2016/);
  assert.equal(redlist(S, [1])[0].value, 5);
});

test('a summary without the counts gives nothing to show', () => {
  assert.deepEqual(redlist({ india: S.india }, [0]), []);
});

test('the home page holds a row for every count, so nothing moves when they fill', () => {
  const html = readFileSync(new URL('../site/index.html', import.meta.url), 'utf8');
  for (const r of REDLIST) assert.ok(html.includes(`data-rl="${r.key}"`), r.key);
});
