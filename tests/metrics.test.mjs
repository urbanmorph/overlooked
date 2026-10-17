// Tests for the server-side usage metrics (functions/lib/metrics.js). Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { clientClass, deviceClass, refHost, observe, record } from '../functions/lib/metrics.js';

const FIREFOX = 'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0';
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1';
const IPAD = 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1';
const ANDROID_TAB = 'Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 Chrome/126.0 Safari/537.36';
const ANDROID_PHONE = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36';

function req(path, { ua = FIREFOX, method = 'GET', referer, country = 'IN', headers = {} } = {}) {
  const h = new Headers(headers);
  if (ua) h.set('user-agent', ua);
  if (referer) h.set('referer', referer);
  const r = new Request('https://overlooked-india.pages.dev' + path, { method, headers: h });
  // request.cf is not settable on a Node Request; observe() reads it through this field
  Object.defineProperty(r, 'cf', { value: country ? { country } : undefined });
  return r;
}
const html = (status = 200) => new Response('<!doctype html>', { status, headers: { 'content-type': 'text/html; charset=utf-8' } });
const json = (status = 200) => new Response(status === 304 ? null : '{}', { status, headers: { 'content-type': 'application/json' } });
const has = (pairs, dim, key) => pairs.some(([d, k]) => d === dim && k === key);
const dims = pairs => pairs.map(([d]) => d);

test('clientClass: browsers are human, AI crawlers are llm, scripts are bot', () => {
  assert.equal(clientClass(FIREFOX), 'human');
  assert.equal(clientClass(IPHONE), 'human');
  assert.equal(clientClass('Mozilla/5.0 (compatible; GPTBot/1.2; +https://openai.com/gptbot)'), 'llm');
  assert.equal(clientClass('Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0)'), 'llm');
  assert.equal(clientClass('Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'), 'bot');
  assert.equal(clientClass('curl/8.4.0'), 'bot');
  assert.equal(clientClass('python-requests/2.32'), 'bot');
  assert.equal(clientClass('Mozilla/5.0 HeadlessChrome/126.0'), 'bot');
  assert.equal(clientClass(''), 'bot');
  assert.equal(clientClass(null), 'bot');
});

test('deviceClass: mobile, tablet or desktop from the user agent', () => {
  assert.equal(deviceClass(FIREFOX), 'desktop');
  assert.equal(deviceClass(IPHONE), 'mobile');
  assert.equal(deviceClass(ANDROID_PHONE), 'mobile');
  assert.equal(deviceClass(IPAD), 'tablet');
  assert.equal(deviceClass(ANDROID_TAB), 'tablet');
});

test('refHost: external host only, never the path or query; own hosts are dropped', () => {
  assert.equal(refHost('https://www.google.com/search?q=private+words'), 'google.com');
  assert.equal(refHost('https://Twitter.com/someone/status/1'), 'twitter.com');
  assert.equal(refHost('https://overlooked-india.pages.dev/ledger'), null);
  assert.equal(refHost('https://abc123.overlooked-india.pages.dev/'), null);
  assert.equal(refHost('http://localhost:8000/'), null);
  assert.equal(refHost('not a url'), null);
  assert.equal(refHost(''), null);
  assert.equal(refHost(null), null);
});

test('page view: path, country, device, class and referrer host', () => {
  const p = observe(req('/ledger', { referer: 'https://www.google.com/search?q=x' }), html());
  assert.ok(has(p, 'class', 'human'));
  assert.ok(has(p, 'page', '/ledger'));
  assert.ok(has(p, 'country', 'IN'));
  assert.ok(has(p, 'device', 'desktop'));
  assert.ok(has(p, 'ref', 'google.com'));
  assert.ok(!JSON.stringify(p).includes('search?q'));
});

test('page view: trailing slash and .html are folded into one path', () => {
  assert.ok(has(observe(req('/'), html()), 'page', '/'));
  assert.ok(has(observe(req('/method/'), html()), 'page', '/method'));
  assert.ok(has(observe(req('/method.html'), html()), 'page', '/method'));
});

test('page view: no referrer row for direct visits or internal navigation', () => {
  assert.ok(!dims(observe(req('/'), html())).includes('ref'));
  assert.ok(!dims(observe(req('/', { referer: 'https://overlooked-india.pages.dev/ledger' }), html())).includes('ref'));
});

test('front page URL parameters record view, group and state selections', () => {
  const p = observe(req('/?view=iucn&group=birds&state=29'), html());
  assert.ok(has(p, 'view', 'iucn'));
  assert.ok(has(p, 'group', 'birds'));
  assert.ok(has(p, 'state', '29'));
});

test('front page URL parameters: malformed values are dropped, not stored', () => {
  const p = observe(req('/?view=<script>&group=' + 'x'.repeat(200) + '&state=karnataka'), html());
  assert.deepEqual(dims(p).filter(d => ['view', 'group', 'state'].includes(d)), []);
});

test('species page open records the species key from the page URL', () => {
  assert.ok(has(observe(req('/species?key=2435099'), html()), 'species', '2435099'));
  assert.ok(has(observe(req('/species?key=6W3C4'), html()), 'species', '6W3C4'));
  assert.ok(!dims(observe(req('/species?key=a%20b%3Cc'), html())).includes('species'));
  assert.ok(!dims(observe(req('/species'), html())).includes('species'));
});

test('bots and AI crawlers bump only their class counter', () => {
  const p = observe(req('/species?key=1', { ua: 'Mozilla/5.0 (compatible; GPTBot/1.2)' }), html());
  assert.deepEqual(p, [['class', 'llm']]);
  assert.deepEqual(observe(req('/', { ua: 'curl/8' }), html()), [['class', 'bot']]);
});

test('prefetches, HEAD requests, errors and non-HTML responses are not page views', () => {
  assert.deepEqual(observe(req('/', { headers: { 'sec-purpose': 'prefetch' } }), html()), []);
  assert.deepEqual(observe(req('/', { method: 'HEAD' }), html()), []);
  assert.deepEqual(observe(req('/nope'), html(404)), []);
  assert.deepEqual(observe(req('/robots.txt'), new Response('x', { headers: { 'content-type': 'text/plain' } })), []);
});

test('search shard fetch records the two-letter prefix only', () => {
  const p = observe(req('/data/layers/master/2026-10/search/pa.json'), json());
  assert.deepEqual(p, [['search', 'pa']]);
  assert.deepEqual(observe(req('/data/layers/master/2026-10/search/a_.json'), json(304)), [['search', 'a_']]);
  // places.json loads with every front page, so it says nothing about a search
  assert.deepEqual(observe(req('/data/layers/master/2026-10/search/places.json'), json()), []);
});

test('group file fetch records the group index', () => {
  assert.deepEqual(observe(req('/data/layers/master/2026-10/g/12.json'), json()), [['group_open', '12']]);
});

test('other data files, failed fetches and bot fetches record nothing', () => {
  assert.deepEqual(observe(req('/data/latest.json'), json()), []);
  assert.deepEqual(observe(req('/data/layers/master/2026-10/summary.json'), json()), []);
  assert.deepEqual(observe(req('/data/layers/master/2026-10/search/pa.json'), json(404)), []);
  assert.deepEqual(observe(req('/data/layers/master/2026-10/g/1.json', { ua: 'curl/8' }), json()), []);
});

test('no IP, cookie or user agent string is ever part of the output', () => {
  const r = req('/?group=birds', { headers: { 'cf-connecting-ip': '203.0.113.9', cookie: 'id=abc' } });
  const out = JSON.stringify(observe(r, html()));
  assert.ok(!out.includes('203.0.113.9'));
  assert.ok(!out.includes('abc'));
  assert.ok(!out.includes('Firefox'));
});

test('record: one upsert per pair in a single batch, keyed by day', async () => {
  const calls = [];
  const db = {
    prepare: sql => ({ bind: (...a) => ({ sql, a }) }),
    batch: async stmts => { calls.push(stmts); },
  };
  await record(db, '2026-10-17', [['page', '/'], ['country', 'IN']]);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].length, 2);
  assert.match(calls[0][0].sql, /ON CONFLICT\(day, dim, key\) DO UPDATE SET n = n \+ 1/);
  assert.deepEqual(calls[0][0].a, ['2026-10-17', 'page', '/']);
});

test('record: does nothing without a binding or pairs, and never throws', async () => {
  await record(undefined, '2026-10-17', [['page', '/']]);
  await record({ prepare: () => { throw new Error('x'); } }, '2026-10-17', [['page', '/']]);
  let called = false;
  await record({ prepare: () => ({ bind: () => ({}) }), batch: async () => { called = true; } }, '2026-10-17', []);
  assert.equal(called, false);
});

test('middleware: response passes through; nothing is scheduled without the binding', async () => {
  const { onRequest } = await import('../functions/_middleware.js');
  const res = html();
  const waits = [];
  const out = await onRequest({ request: req('/'), env: {}, next: async () => res, waitUntil: p => waits.push(p) });
  assert.equal(out, res);
  assert.equal(waits.length, 0);
});

test('middleware: with the binding, counts go to waitUntil and a failing D1 changes nothing', async () => {
  const { onRequest } = await import('../functions/_middleware.js');
  const res = json();
  const waits = [];
  const METRICS = { prepare: () => ({ bind: () => ({}) }), batch: async () => { throw new Error('D1 down'); } };
  const out = await onRequest({ request: req('/data/layers/master/m/g/3.json'), env: { DB: METRICS }, next: async () => res, waitUntil: p => waits.push(p) });
  assert.equal(out, res);
  assert.equal(waits.length, 1);
  await waits[0];
});
