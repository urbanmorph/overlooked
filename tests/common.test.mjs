// Tests for the shared site helpers (site/assets/common.js). Run: node --test tests/common.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { bit, tags, periodName, getJSON, nameMatches, plainName, safeHref, speciesLink, iucnBadge, stateOptions, setParams } from '../site/assets/common.js';

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

test('a failed request is not kept: the next getJSON asks again', async () => {
  let n = 0;
  globalThis.fetch = async () => (++n === 1 ? { ok: false, status: 503 } : { ok: true, json: async () => ({ n }) });
  globalThis.early = {};
  await assert.rejects(getJSON('c.json'), /503/);
  assert.deepEqual(await getJSON('c.json'), { n: 2 });
});

test('pages start their first data request in the head, not with a preload link (WebKit fetches those twice)', () => {
  const dir = new URL('../site/', import.meta.url);
  for (const name of readdirSync(dir).filter(n => n.endsWith('.html'))) {
    assert.ok(!/rel="preload" href="\/data\//.test(readFileSync(new URL(name, dir), 'utf8')), name);
  }
  const early = name => readFileSync(new URL(name, dir), 'utf8').match(/window\.early = .*?\[(.*?)\]/)?.[1];
  // Both pointers a page waits on start at once (the list's and the snapshot's), not one after the other.
  assert.equal(early('index.html'), "'layers/master/latest.json', 'latest.json'");
  assert.equal(early('species.html'), "'layers/master/latest.json', 'latest.json'");
  assert.equal(early('fix.html'), "'latest.json', 'layers/master/latest.json'");
  assert.equal(early('shortlist.html'), "'layers/shortlist/latest.json', 'layers/master/latest.json'");
});

test('a search row matches from the start of its Latin name, or of any word of its common name', () => {
  const latin = ['Anathana ellioti', 'DHXJ', 3, 1, 1, 0, 0, 1850];
  const common = ['Madras Treeshrew', ...latin.slice(1), 'Anathana ellioti'];
  assert.ok(nameMatches(latin, 'anathana e'));
  assert.ok(!nameMatches(latin, 'ellioti'));                      // a Latin name from its start only
  for (const q of ['madras', 'treeshrew', 'madras tree', 'Madras-Treeshrew']) assert.ok(nameMatches(common, q), q);
  assert.ok(!nameMatches(common, 'shrew') && !nameMatches(common, 'adras'));
  assert.ok(nameMatches(['Pallas’s Leaf Warbler', ...latin.slice(1), 'X y'], 'pallass leaf'));
});

test('plainName: lower case, hyphens and runs of spaces as one space, no apostrophes', () => {
  assert.equal(plainName("  Sri Lanka Green-Pigeon "), 'sri lanka green pigeon');
  assert.equal(plainName("Pallas's"), 'pallass');
});

test('safeHref: a web address from a source, or nothing (a javascript: link never reaches an href)', () => {
  assert.equal(safeHref('https://doi.org/10.1/x'), 'https://doi.org/10.1/x');
  assert.equal(safeHref('http://a.org/'), 'http://a.org/');
  for (const u of ['javascript:alert(1)', ' JAVASCRIPT:x', 'data:text/html,x', '', null, undefined]) assert.equal(safeHref(u), null);
});

test('speciesLink: the species page when it has one, else the name; the name in italics and escaped', () => {
  assert.equal(speciesLink('4Q 7', 'Aus bus'), '<a href="/species?key=4Q%207"><i>Aus bus</i></a>');
  assert.equal(speciesLink('', 'Aus <b>'), '<i>Aus &lt;b&gt;</i>');
});

test('speciesLink with an English name: the name on its own line under the Latin name, escaped', () => {
  assert.equal(speciesLink('K1', 'Aus bus', 'Common <aus>'),
    '<a href="/species?key=K1"><i>Aus bus</i></a><div class="en">Common &lt;aus&gt;</div>');
  assert.equal(speciesLink('K1', 'Aus bus', null), '<a href="/species?key=K1"><i>Aus bus</i></a>');
});

test('iucnBadge: the category, "Not assessed" for NE', () => {
  assert.equal(iucnBadge('EN'), '<span class="iucn i-EN" title="IUCN Red List">EN</span>');
  assert.match(iucnBadge('NE'), />Not assessed</);
});

test('stateOptions: one option per state of the list', () => {
  assert.equal(stateOptions({ states: [{ code: 29, name: 'Karnataka' }, { code: 32, name: 'Kerala & <x>' }] }),
    '<option value="29">Karnataka</option><option value="32">Kerala &amp; &lt;x&gt;</option>');
});

test('setParams: each choice into the address, an empty one taken out', () => {
  const calls = [];
  globalThis.location = { href: 'https://x/fix?state=29&group=birds&keep=1' };
  globalThis.history = { replaceState: (a, b, u) => calls.push(String(u)) };
  setParams([['state', '32'], ['group', null], ['band', '']]);
  assert.deepEqual(calls, ['https://x/fix?state=32&keep=1']);
});
