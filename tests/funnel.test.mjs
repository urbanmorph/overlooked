// Tests for the evidence funnel (site/assets/funnel.js). Run: node --test tests/funnel.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { funnel, sumSeries } from '../site/assets/funnel.js';

const cats = n => [0, 0, 0, 0, n, 0, 0, 0, 0];
// Two groups; india rows [documented, open record, IUCN counts, threatened, in a state, recorded since recent_from].
const S = {
  recent_from: 2016, unlisted: [7, 2],
  india: [[100, 60, cats(100), 3, 40, 15], [50, 20, cats(50), 1, 10, 2]],
  by_state: { 32: [[30, 2, 12], [5, 0, 1]] },
};

test('India: each stage nests in the one before, with the gap between them named', () => {
  const f = funnel(S, [0, 1]);
  assert.deepEqual(f.stages.map(s => [s.key, s.value]), [['documented', 150], ['observed', 80], ['in_state', 50], ['recent', 17]]);
  assert.deepEqual(f.stages.map(s => s.gap), ['Linnean', 'Wallacean', 'Wallacean', 'Wallacean']);
  assert.deepEqual(f.stages.map(s => Math.round(100 * s.share)), [100, 53, 33, 11]);   // share of documented
  assert.equal(f.stages[1].lost, 70);
  assert.match(f.stages[1].lostText, /70 .*checklists and papers/);
  assert.match(f.stages[3].lostText, /33 .*since 2016/);
  assert.equal(f.unlisted, 9);
  for (let i = 1; i < f.stages.length; i++) assert.ok(f.stages[i].value <= f.stages[i - 1].value);
});

test('one group, or a state: the same stages from its own rows; a state starts at the open record', () => {
  assert.equal(funnel(S, [1]).stages[0].value, 50);
  const st = funnel(S, [0, 1], '32');
  assert.deepEqual(st.stages.map(s => [s.key, s.value]), [['observed', 35], ['recent', 13]]);
  assert.equal(st.stages[0].share, 1);
  assert.equal(st.unlisted, null);   // names not on the list are counted for India only
});

test('a summary from before the funnel (no in_state or recent) gives only the stages it has', () => {
  const old = { india: [[100, 60, cats(100), 3]], by_state: {} };
  assert.deepEqual(funnel(old, [0]).stages.map(s => s.key), ['documented', 'observed']);
});

test('history: a measure summed over groups, oldest first; a list without the measure is left out', () => {
  const H = { measures: ['documented', 'recent'], lists: [
    { period: '2026-10', groups: [[90, null], [40, null]] },
    { period: '2026-10-26', groups: [[100, 15], [50, 2]] }] };
  assert.deepEqual(sumSeries(H, 'documented', [0, 1]), [{ period: '2026-10', value: 130 }, { period: '2026-10-26', value: 150 }]);
  assert.deepEqual(sumSeries(H, 'recent', [0, 1]), [{ period: '2026-10-26', value: 17 }]);
  assert.deepEqual(sumSeries(null, 'recent', [0]), []);
});

test('the home page holds a placeholder row for every India step, with the same label, so nothing moves when they fill', async () => {
  const { readFileSync } = await import('node:fs');
  const html = readFileSync(new URL('../site/index.html', import.meta.url), 'utf8');
  funnel(S, [0, 1]).stages.forEach((s, i) => assert.ok(html.includes(
    `data-stage="${s.key}"><div class="st">${i ? '<span class="st-lost"></span>' : ''}<span class="st-label">${s.label}</span>`), s.key));
});
