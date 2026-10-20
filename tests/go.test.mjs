// Tests for the counted link to iNaturalist (functions/go/inat/[id].js, counted by _middleware.js). Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { onRequest as go } from '../functions/go/inat/[id].js';
import { onRequest as middleware } from '../functions/_middleware.js';

const FIREFOX = 'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0';
const req = (path, ua = FIREFOX) => new Request('https://overlooked-india.pages.dev' + path, { headers: { 'user-agent': ua } });
const id = path => path.split('?')[0].split('/').pop();
const open = path => go({ request: req(path), params: { id: id(path) } });

// A D1 stand-in that keeps the bound rows, or fails on batch.
function fakeDB({ fail = false } = {}) {
  const rows = [];
  return { rows, prepare: () => ({ bind: (...a) => a }), batch: async stmts => { if (fail) throw new Error('D1 down'); rows.push(...stmts); } };
}
async function through(path, env, ua) {
  const waits = [];
  const res = await middleware({ request: req(path, ua), env, next: async () => go({ request: req(path, ua), params: { id: id(path) } }), waitUntil: p => waits.push(p) });
  await Promise.all(waits);
  return { res, waits };
}

test('redirect: a numeric id goes to the observation on iNaturalist with a 302', async () => {
  const res = await open('/go/inat/123456789?g=true-bugs');
  assert.equal(res.status, 302);
  assert.equal(res.headers.get('location'), 'https://www.inaturalist.org/observations/123456789');
});

test('redirect: anything else is not found, and nothing goes to another site', async () => {
  for (const p of ['/go/inat/abc', '/go/inat/12.5', '/go/inat/0', '/go/inat/-3', '/go/inat/' + '9'.repeat(16), '/go/inat/1%2F..%2Fevil']) {
    const res = await go({ request: req(p), params: { id: decodeURIComponent(id(p)) } });
    assert.equal(res.status, 404, p);
    assert.equal(res.headers.get('location'), null, p);
  }
  assert.equal((await go({ request: req('/go/inat/'), params: {} })).status, 404);
});

test('counter: a person who follows the link adds one inat_out for the group, and gets the same redirect', async () => {
  const db = fakeDB();
  const { res } = await through('/go/inat/42?g=bees-wasps-ants', { DB: db });
  assert.equal(res.status, 302);
  assert.equal(res.headers.get('location'), 'https://www.inaturalist.org/observations/42');
  assert.deepEqual(db.rows.map(([, dim, key]) => [dim, key]), [['inat_out', 'bees-wasps-ants']]);
  assert.ok(!JSON.stringify(db.rows).includes('42'), 'the observation id is not stored');
});

test('counter: a strange group key, a bot or a bad id adds nothing', async () => {
  for (const [path, ua] of [['/go/inat/42?g=Bad%20Key', FIREFOX], ['/go/inat/42?g=' + 'a'.repeat(60), FIREFOX], ['/go/inat/42', FIREFOX],
    ['/go/inat/42?g=birds', 'curl/8'], ['/go/inat/x?g=birds', FIREFOX]]) {
    const db = fakeDB();
    await through(path, { DB: db }, ua);
    assert.deepEqual(db.rows.filter(([, dim]) => dim === 'inat_out'), [], path);
  }
});

test('counter: a failing D1 or no binding never changes or delays the redirect', async () => {
  for (const env of [{ DB: fakeDB({ fail: true }) }, {}]) {
    const { res } = await through('/go/inat/42?g=birds', env);
    assert.equal(res.status, 302);
    assert.equal(res.headers.get('location'), 'https://www.inaturalist.org/observations/42');
  }
});
