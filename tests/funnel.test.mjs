// Tests for "How far does our knowledge go?" (site/assets/funnel.js). Run: node --test tests/funnel.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { knowledge, segmentChanges, STEPS } from '../site/assets/funnel.js';

const cats = n => [0, 0, 0, 0, n, 0, 0, 0, 0];
// Two groups; india rows [documented, open record, IUCN counts, threatened, in a state, recorded since recent_from].
const S = {
  recent_from: 2016, unlisted: [7, 2],
  india: [[100, 60, cats(100), 3, 40, 15], [50, 20, cats(50), 1, 10, 2]],
  by_state: { 32: [[30, 2, 12], [5, 0, 1]] },
};

test('India: each documented species counted once, at the furthest step we know; the segments add up', () => {
  const k = knowledge(S, [0, 1]);
  assert.equal(k.base, 150);
  assert.deepEqual(k.segments.map(s => [s.key, s.value]), [['k1', 70], ['k2', 30], ['k3', 33], ['k4', 17]]);
  assert.equal(k.segments.reduce((a, s) => a + s.value, 0), k.base);
  assert.deepEqual(k.segments.map(s => s.view), [null, 'observed', 'observed', 'recent']);   // checklists have no states
  assert.equal(Math.round(100 * k.segments[0].share), 47);
  assert.equal(k.unlisted, 9);
});

test('a state: the bar starts at the open record, as checklists give no states yet', () => {
  const k = knowledge(S, [0, 1], '32');
  assert.equal(k.base, 35);
  assert.deepEqual(k.segments.map(s => [s.key, s.value]), [['k3', 22], ['k4', 13]]);
  assert.equal(k.unlisted, null);
  // With filters the year per state is not known: one segment, the open record here.
  const f = knowledge({ ...S, by_state: { 32: [[30, 2, null], [5, 0, null]] } }, [0, 1], '32');
  assert.deepEqual(f.segments.map(s => [s.key, s.value]), [['obs', 35]]);
});

test('a summary from before the funnel (no in_state or recent): checklists only, and the open record', () => {
  const old = { india: [[100, 60, cats(100), 3]], by_state: {} };
  assert.deepEqual(knowledge(old, [0]).segments.map(s => [s.key, s.value]), [['k1', 40], ['obs', 60]]);
});

test('the change of each segment since the last list, from history.json; null where a list lacks a measure', () => {
  const H = { measures: ['documented', 'unlisted', 'observed', 'in_state', 'recent'], lists: [
    { period: '2026-10', groups: [[90, null, 50, 30, null], [40, null, 20, 10, null]] },
    { period: '2026-10-26', groups: [[100, 7, 60, 40, 15], [50, 2, 20, 10, 2]] }] };
  assert.deepEqual(segmentChanges(H, [0, 1]), { k1: 10, k2: 0, k3: null, k4: null });
  assert.deepEqual(segmentChanges(null, [0]), {});
});

test('every step has a name and a sentence; the home page holds the bar, the legend and a row per group', () => {
  for (const s of STEPS) assert.ok(s.name && s.long, s.key);
  const html = readFileSync(new URL('../site/index.html', import.meta.url), 'utf8');
  assert.ok(html.includes('id="kbar"') && html.includes('id="kgroups"'));
  for (const s of STEPS) assert.ok(html.includes(`<i class="${s.key}"></i>${s.name} <b class="mono">–</b></span>`), s.key);
});
