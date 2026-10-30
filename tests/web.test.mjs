// The species web (site/assets/web.js): the seven gaps for one species, and the layout of its partners.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { KINDS, gapStates, layout } from '../site/assets/web.js';

const S = { recent_from: 2016, traits: [0], niche: [0], types: [0], trend_known: [null] };

test('each gap for one species: known, part known, open or not measured', () => {
  const g = gapStates({ year: 1825, latest: 2026, trend: null, dna: false, barcode: 1, traits: false, precise: 40,
    partners: 233, interactionsIndia: true }, S);
  assert.deepEqual(g.map(x => [x.term, x.state]), [['Linnean', 'known'], ['Wallacean', 'known'], ['Prestonian', 'na'],
    ['Darwinian', 'part'], ['Raunkiæran', 'gap'], ['Hutchinsonian', 'known'], ['Eltonian', 'known']]);
  const old = gapStates({ year: null, latest: 1990, trend: false, dna: false, barcode: 0, traits: true, precise: 3,
    partners: 4, interactionsIndia: false }, S);
  assert.deepEqual(old.map(x => x.state), ['gap', 'part', 'gap', 'gap', 'known', 'gap', 'part']);
  const none = gapStates({ year: 2001, latest: null, trend: undefined, dna: true, barcode: undefined, traits: undefined,
    precise: undefined, partners: null, interactionsIndia: false }, { recent_from: 2016 });
  assert.deepEqual(none.map(x => x.state), ['known', 'gap', 'na', 'known', 'na', 'na', 'gap']);
  assert.ok(g.every(x => x.text.length > 0));
});

test('partners sit in their kind of link, most records nearest the centre, the rest counted', () => {
  const p = (name, n, india) => [name, null, n, india, ['eats']];
  const web = { n: { eats: 40, hosts: 1 }, p: { eats: Array.from({ length: 30 }, (_, i) => p(`E${i}`, 100 - i, i % 2)), hosts: [p('H', 2, 0)] } };
  const L = layout(web, { cap: 12 });
  const eats = L.nodes.filter(n => n.kind === 'eats');
  assert.equal(eats.length, 12);
  assert.equal(L.sectors.find(s => s.kind === 'eats').more, 28);              // 40 in all, 12 drawn
  assert.ok(Math.hypot(eats[0].x, eats[0].y) < Math.hypot(eats[11].x, eats[11].y));
  assert.ok(eats[0].r > eats[11].r && eats[1].india === true && eats[0].india === false);
  const [a, b] = L.sectors;
  assert.ok(a.a1 <= b.a0, 'sectors do not overlap');
  assert.deepEqual(L.sectors.map(s => s.kind), KINDS.filter(k => web.n[k.k]).map(k => k.k));
  assert.deepEqual(layout({ n: {}, p: {} }).nodes, []);
});

test('the map: a district by its latest GBIF record, else its state by an open record', async () => {
  const { whereFill } = await import('../site/assets/web.js');
  const districts = [{ id: 1, state_lgd: 32 }, { id: 2, state_lgd: 32 }, { id: 3, state_lgd: 29 }, { id: 4, state_lgd: 9 }];
  const states = new Map([[32, { obs: true, wait: 6 }], [29, { obs: true, wait: 0 }], [9, { obs: false, wait: 2 }]]);
  const v = whereFill(districts, [[1, 2012, 2026, 28], [2, 1890, 1950, 3]], states, 2016);
  assert.deepEqual([1, 2, 3, 4].map(id => v.get(id).cls), ['recent', 'old', 'state', 'none']);
  assert.deepEqual(v.get(1), { cls: 'recent', first: 2012, latest: 2026, n: 28, obs: true, wait: 6 });
  assert.equal(v.get(4).wait, 2);
});
