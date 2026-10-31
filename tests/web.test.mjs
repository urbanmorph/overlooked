// The species web (site/assets/web.js): the seven gaps for one species, and the layout of its partners.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { KINDS, gapStates, tree, LAYERS, groupShares, pyramidHTML, glyphSVG, relatives } from '../site/assets/web.js';

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
  const iu = t => gapStates({ trend: t === 'Unknown' ? false : true, iucnTrend: t }, S)[2];
  assert.deepEqual([iu('Decreasing').state, iu('Decreasing').text], ['known', 'Population decreasing (IUCN Red List).']);
  assert.deepEqual([iu('Unknown').state, iu('Unknown').text], ['gap', 'Assessed by IUCN, but the population trend is not known.']);
  assert.match(gapStates({ trend: true, iucnTrend: null }, S)[2].text, /State of India/);
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

test('the group share per gap: known species of the group over its documented species, null when not measured', () => {
  const S = { india: [[200], [0]], gaps_known: [[196, 86, null, 72, 0, null, 32], [0, 0, 0, 0, 0, 0, 0]] };
  assert.deepEqual(groupShares(S, 0), [98, 43, null, 36, 0, null, 16]);
  assert.deepEqual(groupShares(S, 1), Array(7).fill(null));                   // no documented species
  assert.deepEqual(groupShares({ india: [[5]] }, 0), Array(7).fill(null));    // an older summary
});

test('the pyramid: three layers on the Linnean base, each block in its state with the group bar inside', () => {
  const gaps = ['Linnean', 'Wallacean', 'Prestonian', 'Darwinian', 'Raunkiæran', 'Hutchinsonian', 'Eltonian']
    .map((term, i) => ({ term, plain: `p${i}`, state: ['known', 'part', 'gap', 'na'][i % 4], text: 't' }));
  const html = pyramidHTML(gaps, [98, 43, null, 36, 0, null, 16], 'bats');
  assert.deepEqual(LAYERS, [[2, 4, 5, 6], [1, 3], [0]]);
  const order = [...html.matchAll(/data-i="(\d)"/g)].map(m => +m[1]);
  assert.deepEqual(order, [2, 4, 5, 6, 1, 3, 0]);
  assert.match(html, /class="blk known"[^>]*data-i="0"/);
  assert.match(html, /width:98%/);
  assert.match(html, /bats: not measured/);                                   // Prestonian, null share
  assert.equal((html.match(/<button/g) || []).length, 7);
});

test('the glyph: the same seven cells, small, in their states', () => {
  const svg = glyphSVG(['known', 'part', 'gap', 'na', 'known', 'known', 'gap']);
  assert.equal((svg.match(/<rect/g) || []).length, 7);
  assert.match(svg, /class="g-part"/);
  assert.match(svg, /class="g-na"/);
});

test('relatives: the same genus first, then the latest recorded; this species always in; capped', () => {
  // [key, name, year, latest, states, trend, dna, barcode, traits, precise, partners, interaction in India]
  const r = (key, name, year, last) => [key, name, year, last, 1, null, false, 0, false, 0, null, false];
  const rows = [r('A', 'Bus alpha', 1800, 1990), r('B', 'Cus beta', 1850, 2024), r('C', 'Aus gamma', 1900, 2020),
    r('D', 'Aus delta', 1820, null), r('E', 'Cus eps', 1700, 2025)];
  const R = relatives(rows, 'C', 'Aus gamma', { recent_from: 2016 }, 3);
  assert.deepEqual(R.rows.map(x => x.key), ['C', 'D', 'E']);                  // Aus first (latest first), then the latest other
  assert.equal(R.total, 5);
  assert.equal(R.rows[0].gaps.length, 7);
  assert.equal(R.rows[0].gaps[1], 'known');                                   // Wallacean: latest 2020 >= 2016
  assert.deepEqual(relatives(rows, 'A', 'Bus alpha', { recent_from: 2016 }, 2).rows.map(x => x.key), ['A', 'E']);
  assert.deepEqual(relatives(rows, 'Z', 'Aus zeta', { recent_from: 2016 }, 2).rows.map(x => x.key), ['C', 'D']);   // waits: genus still first
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
