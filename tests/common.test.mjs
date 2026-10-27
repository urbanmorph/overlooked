// Tests for the shared site helpers (site/assets/common.js). Run: node --test tests/common.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { bit, tags, periodName } from '../site/assets/common.js';

test('bit reads masks wider than 32 bits', () => {
  assert.equal(bit(2 ** 40, 40), true);
  assert.equal(bit(2 ** 40, 39), false);
  assert.equal(bit(5, 0) && bit(5, 2) && !bit(5, 1), true);
});

test('tags: one label per set bit, escaped; nothing when none is set', () => {
  assert.equal(tags(5, ['a', 'b', '<c>']), '<span class="tag">a</span><span class="tag">&lt;c&gt;</span>');
  assert.equal(tags(0, ['a']), '');
});

test('periodName: a weekly id names its week, a monthly id its month', () => {
  assert.equal(periodName('2026-10-26'), 'week of 26 October 2026');
  assert.equal(periodName('2026-10'), 'October 2026');
  assert.equal(periodName(''), '');
});
