// Tests for the shared site helpers (site/assets/common.js). Run: node --test tests/common.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { bit, tags, periodName, getJSON } from '../site/assets/common.js';

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

test('getJSON uses a request the page started in its head (window.early), once, and fetches the rest', async () => {
  const asked = [];
  globalThis.fetch = async url => { asked.push(url); return { ok: true, json: async () => ({ url }) }; };
  globalThis.early = { 'a.json': Promise.resolve({ ok: true, json: async () => ({ early: true }) }) };
  assert.deepEqual(await getJSON('a.json'), { early: true });
  assert.deepEqual(await getJSON('a.json'), { early: true });       // the same answer, not a second request
  assert.deepEqual(await getJSON('b.json'), { url: '/data/b.json' });
  assert.deepEqual(asked, ['/data/b.json']);
});

test('pages start their first data request in the head, not with a preload link (WebKit fetches those twice)', () => {
  const dir = new URL('../site/', import.meta.url);
  for (const name of readdirSync(dir).filter(n => n.endsWith('.html'))) {
    assert.ok(!/rel="preload" href="\/data\//.test(readFileSync(new URL(name, dir), 'utf8')), name);
  }
  const early = name => readFileSync(new URL(name, dir), 'utf8').match(/window\.early = .*?\[(.*?)\]/)?.[1];
  assert.equal(early('index.html'), "'layers/master/latest.json'");
  assert.equal(early('fix.html'), "'latest.json'");
  assert.equal(early('shortlist.html'), "'layers/shortlist/latest.json', 'layers/master/latest.json'");
});
