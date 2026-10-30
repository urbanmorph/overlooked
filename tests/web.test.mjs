// The species web (site/assets/web.js): the seven gaps for one species, and the layout of its partners.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { KINDS, gapStates, tree, ringSVG } from '../site/assets/web.js';

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

test('the tree: a branch per kind of link in a fixed order, the partners with most records first, the rest counted', () => {
  const p = (name, n, india, key = null) => [name, key, n, india, ['eats']];
  const web = { n: { hosts: 1, eats: 40 }, p: { eats: Array.from({ length: 30 }, (_, i) => p(`E${i}`, 100 - i, i % 2)), hosts: [p('H', 2, 0, 'K9')] } };
  const T = tree(web, { top: 8 });
  assert.deepEqual(T.map(b => b.kind), ['eats', 'hosts']);                       // KINDS order, not the data's
  assert.equal(T[0].rows.length, 30);
  assert.deepEqual(T[0].rows.slice(0, 8).map(r => r.shown), Array(8).fill(true));
  assert.equal(T[0].rows[8].shown, false);
  assert.equal(T[0].total, 40);
  assert.equal(T[0].rows[0].bar, 1);                                            // bars scale to the kind's largest
  assert.ok(Math.abs(T[0].rows[29].bar - 71 / 100) < 1e-9);
  assert.deepEqual(T[1].rows[0], { name: 'H', key: 'K9', n: 2, india: false, types: ['eats'], bar: 1, shown: true });
  assert.deepEqual(tree({ n: {}, p: {} }), []);
  assert.deepEqual(KINDS.map(k => k.k), ['eats', 'eaten', 'flowers', 'lives', 'hosts', 'other']);
});

test('the ring: one segment per gap, its state as a class, the name at the centre', () => {
  const svg = ringSVG([{ term: 'Linnean', state: 'known', text: 'x' }, { term: 'Wallacean', state: 'gap', text: 'y' }], 'Aus bus');
  assert.equal((svg.match(/<path/g) || []).length, 2);
  assert.match(svg, /class="g-known"/);
  assert.match(svg, /class="g-gap"/);
  assert.match(svg, />Aus</);
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
