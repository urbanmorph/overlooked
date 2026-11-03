// The /data/ function (functions/data/[[path]].js): ranges as R2 gives them, cache/ never served.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { onRequest } from '../functions/data/[[path]].js';

const SIZE = 1000;
function bucket(range) {
  const obj = { size: SIZE, httpEtag: '"e"', body: 'x', range, writeHttpMetadata() {} };
  return { DATA: { get: async () => obj, head: async () => obj } };
}
const ask = (range, r2range) => onRequest({
  request: new Request('https://x/data/a.parquet', { headers: range ? { Range: range } : {} }),
  env: bucket(r2range), params: { path: ['a.parquet'] },
});

test('a range from an offset: the bytes asked', async () => {
  const r = await ask('bytes=100-199', { offset: 100, length: 100 });
  assert.equal(r.status, 206);
  assert.equal(r.headers.get('Content-Range'), 'bytes 100-199/1000');
  assert.equal(r.headers.get('Content-Length'), '100');
});

test('the last N bytes (a Parquet reader asks for the footer this way)', async () => {
  const r = await ask('bytes=-8', { suffix: 8 });
  assert.equal(r.status, 206);
  assert.equal(r.headers.get('Content-Range'), 'bytes 992-999/1000');
  assert.equal(r.headers.get('Content-Length'), '8');
});

test('cache/ is never served', async () => {
  const r = await onRequest({ request: new Request('https://x/data/cache/a'), env: bucket(), params: { path: ['cache', 'a'] } });
  assert.equal(r.status, 404);
});

test('data files are open to agents and crawlers but kept out of search results', async () => {
  const r = await ask();
  assert.equal(r.status, 200);
  assert.equal(r.headers.get('X-Robots-Tag'), 'noindex');
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
});
