// Place pages: /in (every place), /in/<place> (a place's groups) and /in/<place>/<group> ("Birds of Kerala"), written
// in the HTML by functions/in/[[path]].js for search engines and AI crawlers; /sitemaps/places.xml names those worth
// indexing. Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { handle } from '../functions/in/[[path]].js';
import { onRequest as sitemap } from '../functions/sitemaps/[name].js';
import { places, groupSlug, groupTitle, placePath, MIN_SPECIES } from '../functions/lib/places.js';
import { speciesPage } from '../functions/lib/species_page.js';

const SHELL = readFileSync(new URL('../site/in.html', import.meta.url), 'utf8');
const REAL_GROUPS = ['Birds', 'Mammals: large (cats, elephants, deer, primates...)', 'Mammals: bats', 'Mammals: rodents, shrews, hares',
  'Mammals: other (whales, dolphins...)', 'Reptiles', 'Amphibians', 'Fish', 'Insects: butterflies', 'Insects: moths',
  'Insects: dragonflies & damselflies', 'Insects: beetles', 'Insects: bees, wasps, ants', 'Insects: flies', 'Insects: true bugs',
  'Insects: other', 'Spiders & other arachnids', 'Molluscs', 'Crabs, shrimps & kin', 'Plants: orchids', 'Plants: grasses & sedges',
  'Plants: ferns & lycophytes', 'Plants: other flowering plants & conifers', 'Mosses & liverworts', 'Lichens', 'Fungi',
  'Algae & diatoms', 'Other'];

// The summary parts every reader takes from the list (tests/test_master.py keeps this fixture equal to the pipeline's).
const FX = JSON.parse(readFileSync(new URL('./fixtures/summary_model.json', import.meta.url)));
const S = {
  ...FX,
  groups: ['Birds', 'Amphibians', 'Insects: bees, wasps, ants'],
  states: [{ code: '32', name: 'Kerala' }, { code: '29', name: 'Karnataka' }, { code: '1', name: 'Jammu & Kashmir' }],
  provinces: [['5B', 'Western Ghats: Mountains', 'Western Ghats'], ['2A', 'Himalaya: North West', 'Himalaya']],
  recent_from: 2016,
};
// 14 birds in Kerala (3 threatened, 2 endemic), 4 amphibians in Kerala (so its page is noindex), a bird only in Karnataka
const SPECIES = [
  ...Array.from({ length: 11 }, (_, i) => ({ key: `B${i}`, name: `Avis ${String.fromCharCode(97 + i)}`, english: i === 0 ? 'Malabar Avis' : null,
    gi: 0, iucn: 'LC', endemic: false, open: true, states: ['32'], zones: ['Western Ghats'] })),
  { key: 'V1', name: 'Zus vu', english: null, gi: 0, iucn: 'VU', endemic: true, open: true, states: ['32'], zones: ['Western Ghats'] },
  { key: 'C1', name: 'Yus cr', english: 'Great Yus', gi: 0, iucn: 'CR', endemic: true, open: true, states: ['32', '29'], zones: [] },
  { key: 'E1', name: 'Xus en', english: null, gi: 0, iucn: 'EN', endemic: false, open: true, states: ['32'], zones: [] },
  { key: 'K1', name: 'Avis kar', english: null, gi: 0, iucn: 'LC', endemic: false, open: true, states: ['29'], zones: [] },
  ...Array.from({ length: 4 }, (_, i) => ({ key: `A${i}`, name: `Rana ${i}`, english: null, gi: 1, iucn: 'NE', endemic: false,
    open: true, states: ['32'], zones: ['Western Ghats'] })),
];
// Districts: Wayanad (Kerala) has the 14 Kerala birds, each with its latest record there; Aurangabad (Karnataka) one bird.
const DISTRICTS = [{ code: 595, name: 'Wayanad', state: '32', groups: [14, 0, 0] }, { code: 600, name: 'Aurangabad', state: '29', groups: [1, 0, 0] }];
const IN_DISTRICT = { 595: s => s.gi === 0 && s.states.includes('32'), 600: s => s.key === 'K1' };
const where = async (env, a) => ({
  S, week: '2026-11-09', unmarked: ['Insects: bees, wasps, ants'],
  rows: SPECIES.filter(s => (a.group == null || S.groups[s.gi] === a.group) && (a.state == null || s.states.includes(a.state))
    && (a.region == null || s.zones.includes(a.region)) && (a.district == null || IN_DISTRICT[a.district](s)))
    .map(s => (a.district == null ? s : { ...s, latest: s.iucn === 'CR' ? 2023 : 2019 })),
});
const counts = async () => {
  const z = () => S.groups.map(() => 0), C = { S, week: '2026-11-09', india: z(), states: { 32: z(), 29: z(), 1: z() }, zones: { 'Western Ghats': z(), Himalaya: z() } };
  for (const s of SPECIES) {
    C.india[s.gi]++;
    for (const st of s.states) C.states[st][s.gi]++;
    for (const zn of s.zones) C.zones[zn][s.gi]++;
  }
  return { ...C, districts: DISTRICTS };
};
const data = { where, counts };
const asset = async () => new Response(SHELL, { headers: { 'content-type': 'text/html; charset=utf-8' } });
const get = async (path, d = data) => {
  const r = await handle(new Request('https://yellide.com' + path), {}, asset, d);
  return { r, h: r.status === 200 || r.status === 404 ? await r.text() : '' };
};

test('every group, state and zone has its own slug; a group drops its bracket', () => {
  const gs = REAL_GROUPS.map(groupSlug);
  assert.equal(new Set(gs).size, gs.length);
  assert.equal(groupSlug('Mammals: large (cats, elephants, deer, primates...)'), 'mammals-large');
  assert.equal(groupSlug('Insects: bees, wasps, ants'), 'insects-bees-wasps-ants');
  assert.equal(groupTitle('Insects: bees, wasps, ants'), 'Bees, wasps and ants');
  const ps = places(S).map(p => p.slug);
  assert.deepEqual(ps, ['india', 'jammu-kashmir', 'karnataka', 'kerala', 'western-ghats', 'himalaya']);
  // A district: its name and its state's, as two states can have a district of the same name.
  assert.deepEqual(places(S, DISTRICTS).slice(6).map(p => [p.slug, p.title]), [['aurangabad-karnataka', 'Aurangabad, Karnataka'], ['wayanad-kerala', 'Wayanad, Kerala']]);
  assert.equal(places(S).find(p => p.slug === 'jammu-kashmir').title, 'Jammu and Kashmir');
  assert.equal(placePath('kerala', 'Birds'), '/in/kerala/birds');
});

test('a group in a place: title and heading say it, the counts, the threatened by category, the endemic, every species linked', async () => {
  const { r, h } = await get('/in/kerala/birds');
  assert.equal(r.status, 200);
  assert.match(h, /<title>Birds of Kerala: 14 species, 3 threatened · yellide<\/title>/);
  assert.match(h, /<h1 class="page">Birds of Kerala<\/h1>/);
  assert.equal((h.match(/<h1\b/g) || []).length, 1);
  assert.ok(h.includes('<link rel="canonical" href="https://yellide.com/in/kerala/birds">'));
  assert.match(h, /<meta name="description" content="14 birds on the India list have an open record placed in Kerala, 3 of them threatened \(1 Critically Endangered, 1 Endangered and 1 Vulnerable\) and 2 endemic to India\./);
  const thr = h.match(/<section[^>]*id="threatened"[^>]*>(.*?)<\/section>/s)[1];
  assert.deepEqual([...thr.matchAll(/href="([^"]+)"/g)].map(m => m[1]), ['/species/C1/yus-cr', '/species/E1/xus-en', '/species/V1/zus-vu']);
  assert.match(thr, /<i>Yus cr<\/i><\/a> <span class="iucn i-CR"[^>]*>CR<\/span><span class="en">Great Yus<\/span>/);   // species_model speciesName
  assert.match(h.match(/<section[^>]*id="endemic"[^>]*>(.*?)<\/section>/s)[1], /Yus cr.*Zus vu/s);
  const all = h.match(/<section[^>]*id="all"[^>]*>(.*?)<\/section>/s)[1];
  assert.equal((all.match(/href="\/species\//g) || []).length, 14);
  assert.ok(all.includes('href="/?state=32&amp;group=birds"'), 'see them on the map');
  assert.ok(!h.includes('noindex'));
  assert.ok(h.includes('href="/in/karnataka/birds"') && h.includes('href="/in/india/birds"'), 'the group elsewhere');
  assert.ok(h.includes('href="/in/kerala/amphibians"'), 'other groups here');
  assert.ok(!h.includes('href="/in/jammu-kashmir/birds"'), 'no link to a place with none');
  const ld = JSON.parse(h.match(/<script type="application\/ld\+json">(.*?)<\/script>/s)[1]);
  assert.equal(ld['@graph'][0]['@type'], 'CollectionPage');
  assert.deepEqual(ld['@graph'][1].itemListElement.map(i => i.name), ['Places', 'Kerala', 'Birds']);
});

test('few species: the page still answers, marked noindex; a group with no endemic mark says so instead of "0 endemic"', async () => {
  const { r, h } = await get('/in/kerala/amphibians');
  assert.equal(r.status, 200);
  assert.ok(4 < MIN_SPECIES && h.includes('<meta name="robots" content="noindex">'));
  const bees = await get('/in/india/insects-bees-wasps-ants');
  assert.equal(bees.r.status, 200);
  assert.match(bees.h, /No species on the list is recorded here yet/);
});

test('a zone reads as a region; India counts every species on the list', async () => {
  const wg = await get('/in/western-ghats/birds');
  assert.match(wg.h, /<h1 class="page">Birds of the Western Ghats<\/h1>/);
  assert.match(wg.h, /12 birds on the India list have a GBIF record placed in the Western Ghats/);
  const india = await get('/in/india/birds');
  assert.match(india.h, /<h1 class="page">Birds of India<\/h1>/);
  assert.match(india.h, /15 birds are on the India list/);
});

test('a place: its groups with their counts, linked; /in: every place', async () => {
  const { h } = await get('/in/kerala');
  assert.match(h, /<h1 class="page">Species of Kerala<\/h1>/);
  assert.ok(h.includes('href="/in/kerala/birds"') && h.includes('href="/in/kerala/amphibians"'));
  assert.ok(!h.includes('href="/in/kerala/insects-bees-wasps-ants"'), 'no link to a group with none here');
  const idx = await get('/in');
  assert.match(idx.h, /<h1 class="page">Species of India, by state, district and region<\/h1>/);
  for (const p of ['/in/india', '/in/kerala', '/in/karnataka', '/in/western-ghats']) assert.ok(idx.h.includes(`href="${p}"`), p);
});

test('a district: its species with the year of the latest record there, threatened ones too, and how to read the list', async () => {
  const { r, h } = await get('/in/wayanad-kerala/birds');
  assert.equal(r.status, 200);
  assert.match(h, /<h1 class="page">Birds of Wayanad, Kerala<\/h1>/);
  assert.match(h, /14 birds on the India list have a GBIF record placed in Wayanad, Kerala, 3 of them threatened/);
  const thr = h.match(/<section[^>]*id="threatened"[^>]*>(.*?)<\/section>/s)[1];
  assert.match(thr, /Yus cr<\/i><\/a> <span class="iucn i-CR"[^>]*>CR<\/span> <span class="yr">latest record 2023<\/span>/);
  assert.match(h, /does not show that it lives there now/);
  assert.match(h, /Wild Life \(Protection\) Act, 1972/);
  assert.doesNotMatch(h, /tell us/i);
  const ld = JSON.parse(h.match(/<script type="application\/ld\+json">(.*?)<\/script>/s)[1]);
  assert.deepEqual(ld['@graph'][1].itemListElement.map(i => i.name), ['Places', 'Kerala', 'Wayanad', 'Birds']);
  assert.ok(h.includes('href="/in/kerala/birds"'), 'the state');
  assert.ok(!h.includes('href="/in/aurangabad-karnataka/birds"'), 'districts of other states are on their state\'s pages');
  const st = await get('/in/kerala/birds');
  assert.doesNotMatch(st.h, /latest record/);                       // a state lists no district years
  assert.ok(!st.h.includes('href="/in/wayanad-kerala/birds"'), 'a state page links its districts on its own page');
});

test('a state lists its districts; a district page has its groups and the same notes', async () => {
  const { h } = await get('/in/kerala');
  const d = h.match(/<section[^>]*id="districts"[^>]*>(.*?)<\/section>/s)[1];
  assert.ok(d.includes('href="/in/wayanad-kerala"') && !d.includes('aurangabad'));
  const hub = await get('/in/wayanad-kerala');
  assert.match(hub.h, /<h1 class="page">Species of Wayanad, Kerala<\/h1>/);
  assert.ok(hub.h.includes('href="/in/wayanad-kerala/birds"'));
  assert.match(hub.h, /does not show that it lives there now/);
});

test('an unknown place or group is a noindex 404; a trailing slash or extra parts send to the page for good', async () => {
  for (const p of ['/in/atlantis', '/in/kerala/dragons']) {
    const { r, h } = await get(p);
    assert.equal(r.status, 404, p);
    assert.ok(h.includes('noindex'));
  }
  for (const [p, to] of [['/in/kerala/', '/in/kerala'], ['/in/kerala/birds/', '/in/kerala/birds'], ['/in/kerala/birds/x', '/in/kerala/birds'], ['/in/', '/in']]) {
    const { r } = await get(p);
    assert.equal(r.status, 301, p);
    assert.equal(r.headers.get('location'), 'https://yellide.com' + to);
  }
});

test('when the data cannot be read: 503, try again later, not a page that says nothing', async () => {
  const { r } = await get('/in/kerala/birds', { where: async () => { throw new Error('R2 down'); }, counts });
  assert.equal(r.status, 503);
  assert.ok(r.headers.get('retry-after'));
});

test('/sitemaps/places.xml: /in, every place and every group in a place with enough species; nothing thin', async () => {
  const r = await sitemap({ request: new Request('https://yellide.com/sitemaps/places.xml'), env: {}, params: { name: 'places.xml' }, counts });
  assert.equal(r.status, 200);
  const urls = [...(await r.text()).matchAll(/<loc>([^<]+)<\/loc>/g)].map(m => m[1].replace('https://yellide.com', ''));
  assert.deepEqual(urls, ['/in', '/in/india', '/in/india/birds', '/in/kerala', '/in/kerala/birds', '/in/western-ghats', '/in/western-ghats/birds',
    '/in/wayanad-kerala', '/in/wayanad-kerala/birds']);
  assert.match(readFileSync(new URL('../site/sitemap.xml', import.meta.url), 'utf8'), /https:\/\/yellide\.com\/sitemaps\/places\.xml/);
});

test('a species page links the pages of its group in the states where it has an open record; the footer links /in', () => {
  const html = readFileSync(new URL('../site/species.html', import.meta.url), 'utf8');
  const s = { key: 'C1', name: 'Yus cr', english: 'Great Yus', group: 'Birds', iucn: { category: 'CR' }, sources: [],
    states_with_open_record: ['Kerala', 'Jammu & Kashmir'] };
  const h = speciesPage(html, 'C1', { S, s, week: '2026-11-09' });
  assert.ok(h.includes('href="/in/kerala/birds"') && h.includes('href="/in/jammu-kashmir/birds"'));
  assert.match(h, /Birds of Kerala/);
  assert.ok(SHELL.includes('href="/in"'), 'the footer links the places');
});

test('a state\'s pages link the same place on the sister sites: its cities\' sky on mugilu, its ward maps on bharatlas', async () => {
  for (const path of ['/in/kerala/birds', '/in/kerala']) {
    const { h } = await get(path);
    const s = h.match(/<section class="place-links sister"[^>]*>(.*?)<\/section>/s)?.[1] || '';
    assert.match(s, /<h2>Kerala today<\/h2>/, path);
    assert.ok(s.includes('<a href="https://mugilu.live/c/thiruvananthapuram">Thiruvananthapuram</a>'), path);
    assert.ok(s.includes('<a href="https://mugilu.live/c/kochi">Kochi</a>'), path);
    assert.match(s, /Air, heat and warnings now \(mugilu\)/);
    assert.ok(s.includes('<a href="https://bharatlas.com/view/wards_kochi">Kochi</a>'), path);
    assert.match(s, /Ward maps \(bharatlas\)/);
  }
  const ka = (await get('/in/karnataka')).h;
  assert.ok(ka.includes('https://bharatlas.com/view/wards_bengaluru_gba'));
  for (const path of ['/in/india/birds', '/in/western-ghats/birds', '/in'])          // only states are one place on all three
    assert.ok(!(await get(path)).h.includes('class="place-links sister"'), path);
});
