// Tests for the weekly trend helpers (site/assets/trend.js). Run: node --test tests/trend.test.mjs
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { MEASURES, series, change, geometry, nearest, tile } from '../site/assets/trend.js';

const H = {
  measures: ['documented', 'observed', 'identified', 'threatened', 'waiting_species', 'waiting_observations'],
  groups: ['Birds', 'Fish'],
  lists: [
    { period: '2026-10', india: [15, 8, 5, 3, 4, 37], groups: [[10, 6, 4, 3, 3, 30], [5, 2, 1, 0, 1, 7]] },
    { period: '2026-10-26', india: [16, 9, 6, 5, 3, 32], groups: [[11, 7, 5, 4, 2, 25], [5, 2, 1, 1, 1, 7]] },
  ],
};

test('MEASURES name every measure history.json holds, in its order', () => {
  assert.deepEqual(MEASURES.map(m => m.key), H.measures);
});

test('series: one measure for India or for a group, oldest first', () => {
  assert.deepEqual(series(H, 'documented'), [{ period: '2026-10', value: 15 }, { period: '2026-10-26', value: 16 }]);
  assert.deepEqual(series(H, 'waiting_observations', 0).map(p => p.value), [30, 25]);
  assert.deepEqual(series(null, 'documented'), []);
});

test('change: the latest value and the change since the list before', () => {
  assert.deepEqual(change(series(H, 'threatened')), { now: 5, before: 3, delta: 2 });
  assert.deepEqual(change(series(H, 'documented').slice(0, 1)), { now: 15, before: null, delta: null });
  assert.deepEqual(change([]), { now: null, before: null, delta: null });
});

test('geometry: points span the box, the range is padded, one point sits in the middle', () => {
  const g = geometry([{ value: 10 }, { value: 20 }], { w: 100, h: 50, pad: 0 });
  assert.equal(g.xs[0], 0); assert.equal(g.xs[1], 100);
  assert.ok(g.ys[0] > g.ys[1]);                              // more is higher on the screen
  assert.ok(g.min < 10 && g.max > 20);
  assert.match(g.path, /^M0(\.0+)?,[\d.]+L100(\.0+)?,[\d.]+$/);
  const one = geometry([{ value: 7 }], { w: 100, h: 50, pad: 0 });
  assert.equal(one.xs[0], 50); assert.ok(one.min < 7 && one.max > 7);
});

test('nearest: the point closest to a pointer x', () => {
  assert.equal(nearest([0, 50, 100], 30), 1);
  assert.equal(nearest([0, 50, 100], 99), 2);
  assert.equal(nearest([], 10), -1);
});

test('tile: value, change since the list before, and a small line; a button or a link', () => {
  const b = tile(MEASURES[0], series(H, 'documented'), { pressed: true });
  assert.match(b, /^<button type="button" class="card kpi" aria-pressed="true" data-m="documented">/);
  assert.match(b, /<b>16<\/b><span>Species documented in India<\/span>/);
  assert.match(b, /\+1 since the last list/);
  const a = tile(MEASURES[3], series(H, 'threatened'), { href: '/changes?m=threatened' });
  assert.match(a, /^<a class="card kpi" href="\/changes\?m=threatened">/);
  assert.match(tile(MEASURES[0], series(H, 'documented').slice(0, 1), {}), /First week/);
});

test('the home page holds a placeholder tile for every measure, with the same label, so nothing moves when they fill', () => {
  const html = readFileSync(new URL('../site/index.html', import.meta.url), 'utf8');
  for (const m of MEASURES) assert.ok(html.includes(`href="/changes?m=${m.key}"><b>–</b><span>${m.label}</span>`), m.key);
});
