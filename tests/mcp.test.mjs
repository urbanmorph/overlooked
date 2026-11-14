// The agent server (functions/lib/mcp.js, at /mcp): MCP over Streamable HTTP, stateless and read-only, on the
// published master list. The fixture is a small list in a fake R2 bucket, with the index in the layout the pipeline
// writes (pipeline/master.py mcp_files; the layout comes from meta.json, as there).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { handle, shardOf, _reset } from '../functions/lib/mcp.js';
import { hashOf } from '../site/assets/species_model.js';

// The summary parts every reader takes from the list (tests/test_master.py keeps this fixture equal to the pipeline's).
const FX = JSON.parse(readFileSync(new URL('./fixtures/summary_model.json', import.meta.url)));

const BASE = 'layers/master/2026-11-02/b1/';
const FIELDS = {
  group: [0, 'u8', null], status: [1, 'u8', null], iucn: [2, 'u8', null], suborder: [3, 'u8', 255],
  labels: [4, 'u32', null], states_lo: [8, 'u32', null], states_hi: [12, 'u32', null],
  provinces: [16, 'u32', 4294967295], described: [20, 'u16', 0], last_year: [22, 'u16', 0],
  order: [24, 'u16', 65535], family: [26, 'u16', 65535], text: [28, 'u32', null],
};
const IUCN = ['CR', 'EN', 'VU', 'NT', 'LC', 'DD', 'NE', 'EW', 'EX'];
const PROVINCES = [['5A', 'Western Ghats: Malabar Plains', 'Western Ghats'], ['5B', 'Western Ghats: Mountains', 'Western Ghats'],
  ['2D', 'Himalaya: East', 'Himalaya'], ['6C', 'Deccan Peninsula: Eastern Highlands', 'Deccan Peninsula']];
const SUMMARY = {
  ...FX, iucn: IUCN,
  period: '2026-11-02', groups: ['Birds', 'Reptiles', 'Mammals: bats', 'Mammals: rodents, shrews, hares'],
  states: [{ code: '29', name: 'Karnataka' }, { code: '32', name: 'Kerala' }],
  labels: [{ code: 'rg' }, { code: 'end' }], iucn: IUCN, sources: ['ZSI', 'GBIF'],
  orders: ['Passeriformes', 'Squamata'], suborders: ['Serpentes', 'Sauria'], provinces: PROVINCES,
  recent_from: 2016, waiting: { places: { india: 6681 } },
  licence: 'CC BY 4.0, Sathya Sankaran', attribution: 'Overlooked. Sources: GBIF.org', disclaimer: 'Not an authority.',
};
// [key, name, english, group, status, iucn, endemic, states (bits), provinces (bits or null), described, last, order, suborder, family]
const SPECIES = [
  ['K1', 'Aus bus', 'Malabar Aus', 0, 1, 'EN', true, 0b10, 0b11, 1758, 2020, 0, null, 0],
  ['K2', 'Cus dus', '', 0, 0, 'LC', false, 0, null, 1900, null, 0, null, 0],
  ['K3', 'Naja naja', 'Spectacled Cobra', 1, 1, 'LC', false, 0b01, 0b1100, 1758, 2024, 1, 0, 1],
  ['K4', 'Calotes versicolor', 'Garden Lizard', 1, 1, 'NE', false, 0b11, 0b0010, 1802, 2010, 1, 1, 2],
  ['K5', 'Eus fus', '', 2, 1, 'CR', true, 0b01, 0b0001, 2015, 2015, null, null, null],
  ['K6', 'Gus hus', 'Hus rat', 3, 0, 'VU', true, 0, null, 2019, null, null, null, null],
];
const FAMILIES = ['Cettiidae', 'Elapidae', 'Agamidae'];

function index() {
  const text = [], rows = new DataView(new ArrayBuffer(32 * SPECIES.length));
  let at = 0;
  SPECIES.forEach(([key, name, en, g, st, iucn, end, states, prov, desc, last, order, sub, fam], i) => {
    const o = i * 32;
    rows.setUint8(o, g); rows.setUint8(o + 1, st); rows.setUint8(o + 2, IUCN.indexOf(iucn)); rows.setUint8(o + 3, sub ?? 255);
    rows.setUint32(o + 4, (1 << 0) | (end ? 1 << 1 : 0), true); rows.setUint32(o + 8, states, true); rows.setUint32(o + 12, 0, true);
    rows.setUint32(o + 16, prov ?? 4294967295, true); rows.setUint16(o + 20, desc ?? 0, true); rows.setUint16(o + 22, last ?? 0, true);
    rows.setUint16(o + 24, order ?? 65535, true); rows.setUint16(o + 26, fam ?? 65535, true); rows.setUint32(o + 28, at, true);
    const line = new TextEncoder().encode(`${key}\t${name}\t${en}\n`);
    text.push(line); at += line.length;
  });
  const t = new Uint8Array(at); let p = 0; for (const l of text) { t.set(l, p); p += l.length; }
  return { rows: rows.buffer, text: t.buffer };
}

function files() {
  const { rows, text } = index();
  const sp = Array(32).fill(null);
  Object.assign(sp, { 0: 'Aus bus', 1: 0, 2: 3, 3: 1, 4: 1, 5: 3, 6: 0b10, 7: 555, 8: 4, 9: [[1, 4]], 10: 1758,
    11: 'L., 1758', 12: null, 13: 2021, 14: 'https://doi.org/10.2305/x', 15: 3, 16: true, 17: 12, 18: 1, 19: 5, 20: 2,
    21: [['ml', 'aus pakshi']], 22: true, 23: true, 24: 11, 25: 2, 26: 2019, 27: 'Decreasing', 28: 'Cettiidae',
    29: 'Passeriformes', 30: null, 31: ['5A', '5B'] });
  return {
    'layers/master/latest.json': { period: '2026-11-02', base: BASE },
    [BASE + 'summary.json']: SUMMARY,
    [BASE + 'mcp/meta.json']: { version: 1, rows: SPECIES.length, row_bytes: 32, fields: FIELDS, families: FAMILIES },
    [BASE + 'mcp/rows.bin']: rows,
    [BASE + 'mcp/text.txt']: text,
    [BASE + 'search/ma.json']: { rows: [['Malabar Aus', 'K1', 0, 1, 1, 3, 3, 1758, 'Aus bus']] },
    [BASE + 'search/au.json']: { rows: [['Aus bus', 'K1', 0, 1, 1, 3, 3, 1758], ['Malabar Aus', 'K1', 0, 1, 1, 3, 3, 1758, 'Aus bus']] },
    [BASE + 'search/zu.json']: { rows: [['Zus zus', '', 0, 2, 6, 0, 0, null]] },
    [BASE + `sp/${shardOf('K1')}.json`]: { K1: sp },
    // Districts: [code, name, state code, species per group]; Aurangabad is a name in two states.
    [BASE + 'd/places.json']: { rows: [[101, 'Ernakulam', '32', [1, 1, 1, 0]], [102, 'Aurangabad', '32', [0, 0, 0, 0]],
      [201, 'Aurangabad', '29', [0, 1, 0, 0]]] },
    [BASE + 'd/101.json']: { rows: [['K1', 2010, 2019, 5], ['K4', 2005, 2010, 1], ['K5', 2015, 2015, 1]] },
    [BASE + 'd/201.json']: { rows: [['K3', 2022, 2024, 3]] },
    [BASE + `en/${hashOf('K1') % 64}.json`]: { K1: 'Malabar Aus' },
    [BASE + `pic/${shardOf('K1')}.json`]: { K1: ['https://p/1.jpg', 'https://inat/1', 'Ann', 'CC BY-NC 4.0', 'iNaturalist (India)', 'Malabar Aus'] },
    'layers/newspecies/latest.json': { period: '2026-10-26', file: 'layers/newspecies/2026-10-26/new_species.json' },
    'layers/newspecies/2026-10-26/new_species.json': {
      first_year: 2007, sources: ['Plazi TreatmentBank (CC0)', 'ZSI Animal Discoveries'],
      lookups: { sources: [['Plazi'], ['ZSI Animal Discoveries']], journal: ['Zootaxa', ''], state: ['Kerala', 'Karnataka'], link: ['https://tb.plazi.org/', ''],
        group: ['Mammals: bats', 'Reptiles'], status: ['recorded', 'none', 'later_papers'] },
      columns: { name: ['Eus fus', 'Gus hus', 'Old one'], year: [2015, 2019, 2008], sources: [0, 1, 0], journal: [0, 1, 0],
        state: [0, 1, 0], link: [0, 1, 0], group: [0, 1, 0], key: ['K5', 'K6', null], status: [0, 1, 1],
        latest_after: [2015, null, null], any_record: [1, 0, 0], link_rest: ['ABC', '', 'X'] },
    },
  };
}

function bucket(store = files()) {
  const gets = [];
  return {
    gets,
    async get(key) {
      gets.push(key);
      if (!(key in store)) return null;
      const v = store[key];
      return v instanceof ArrayBuffer
        ? { arrayBuffer: async () => v, json: async () => { throw new Error('binary'); } }
        : { json: async () => structuredClone(v), arrayBuffer: async () => new TextEncoder().encode(JSON.stringify(v)).buffer };
    },
  };
}

let env;
async function rpc(body, { method = 'POST', headers = {}, db } = {}) {
  env = env || { DATA: bucket() };
  if (db) env.DB = db;
  const waits = [];
  const r = await handle(new Request('https://x/mcp', {
    method, headers: { 'content-type': 'application/json', accept: 'application/json, text/event-stream', ...headers },
    body: method === 'POST' ? JSON.stringify(body) : undefined,
  }), env, p => waits.push(p));
  await Promise.all(waits);
  return r;
}
const call = async (name, args = {}) => {
  const r = await rpc({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } });
  return (await r.json()).result;
};
const out = async (name, args) => (await call(name, args)).structuredContent;
const fresh = () => { env = { DATA: bucket() }; _reset(); };

test('shardOf matches the pipeline (site_data.shard_of)', () => {
  assert.deepEqual(['K1', '8M9J', 'Cervidae'].map(shardOf), [97, 477, 310]);
});

test('initialize: the protocol version the client asks for, tools and resources, and how to use them', async () => {
  fresh();
  const r = await rpc({ jsonrpc: '2.0', id: 0, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 't', version: '1' } } });
  assert.equal(r.status, 200);
  assert.equal(r.headers.get('content-type'), 'application/json');
  assert.equal(r.headers.get('access-control-allow-origin'), '*');
  const { result } = await r.json();
  assert.equal(result.protocolVersion, '2025-06-18');
  assert.deepEqual(Object.keys(result.capabilities).sort(), ['resources', 'tools']);
  assert.equal(result.serverInfo.name, 'yellide');
  assert.match(result.instructions, /not an authority/i);
  const old = await (await rpc({ jsonrpc: '2.0', id: 0, method: 'initialize', params: { protocolVersion: '1999-01-01' } })).json();
  assert.equal(old.result.protocolVersion, '2025-06-18');      // one we know, for the client to accept or not
});

test('notifications get 202 and no body; GET is not offered (no server stream); OPTIONS answers CORS', async () => {
  fresh();
  const n = await rpc({ jsonrpc: '2.0', method: 'notifications/initialized' });
  assert.equal(n.status, 202);
  assert.equal(await n.text(), '');
  assert.equal((await rpc(null, { method: 'GET' })).status, 405);
  const o = await rpc(null, { method: 'OPTIONS' });
  assert.equal(o.status, 204);
  assert.match(o.headers.get('access-control-allow-headers'), /mcp-protocol-version/i);
});

test('a browser that opens /mcp gets the page with the instructions (the same address for people and agents)', async () => {
  fresh();
  let asked;
  env.ASSETS = { fetch: async r => { asked = new URL(r.url ?? r).pathname; return new Response('<!doctype html>page', { headers: { 'content-type': 'text/html' } }); } };
  const r = await rpc(null, { method: 'GET', headers: { accept: 'text/html,application/xhtml+xml' } });
  assert.equal(r.status, 200);
  assert.equal(asked, '/mcp');      // the asset path (/mcp.html redirects to /mcp, which is this function)
  assert.equal(await r.text(), '<!doctype html>page');
  assert.equal((await rpc(null, { method: 'GET', headers: { accept: 'text/event-stream' } })).status, 405);
});

test('bad JSON, unknown methods and unknown tools are JSON-RPC errors', async () => {
  fresh();
  const bad = await handle(new Request('https://x/mcp', { method: 'POST', body: '{' }), env, () => {});
  assert.equal((await bad.json()).error.code, -32700);
  assert.equal((await (await rpc({ jsonrpc: '2.0', id: 2, method: 'nope' })).json()).error.code, -32601);
  assert.equal((await (await rpc({ jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'nope' } })).json()).error.code, -32602);
  assert.deepEqual((await (await rpc({ jsonrpc: '2.0', id: 4, method: 'ping' })).json()).result, {});
});

test('tools/list: five read-only tools with input schemas', async () => {
  fresh();
  const { result } = await (await rpc({ jsonrpc: '2.0', id: 1, method: 'tools/list' })).json();
  assert.deepEqual(result.tools.map(t => t.name), ['find_species', 'get_species', 'count_species', 'list_species', 'new_species']);
  for (const t of result.tools) {
    assert.equal(t.inputSchema.type, 'object');
    assert.equal(t.annotations.readOnlyHint, true);
    assert.ok(t.description.length > 40);
  }
});

test('every answer carries the week, licence, attribution and disclaimer', async () => {
  fresh();
  const r = await call('count_species', {});
  assert.equal(r.isError, undefined);
  for (const k of ['week', 'licence', 'attribution', 'disclaimer']) assert.ok(r.structuredContent[k], k);
  assert.equal(r.structuredContent.week, '2026-11-02');
  assert.deepEqual(JSON.parse(r.content[0].text), r.structuredContent);
});

test('find_species: Latin or English name, any word of the English name; one row per species', async () => {
  fresh();
  const a = await out('find_species', { name: 'aus' });
  assert.deepEqual(a.species.map(s => [s.key, s.name, s.english]), [['K1', 'Aus bus', 'Malabar Aus']]);
  assert.equal(a.species[0].group, 'Birds');
  assert.equal(a.species[0].iucn, 'EN');
  assert.equal(a.species[0].url, 'https://yellide.com/species/K1/aus-bus');
  assert.equal((await out('find_species', { name: 'Malabar a' })).species[0].key, 'K1');
  const z = await out('find_species', { name: 'Zus' });
  assert.equal(z.species[0].key, null);
  assert.match(z.species[0].status, /not on the India list/i);
  assert.deepEqual((await out('find_species', { name: 'qq' })).species, []);    // no search file: none
  // A Latin name found in its own search file takes its English name from the picture file.
  env.DATA = bucket({ ...files(), [BASE + 'search/au.json']: { rows: [['Aus bus', 'K1', 0, 1, 1, 3, 3, 1758]] } });
  _reset();
  assert.equal((await out('find_species', { name: 'aus b' })).species[0].english, 'Malabar Aus');
});

test('get_species: status, IUCN with year, DOI and trend, states, evidence, photo with credit, waiting observations', async () => {
  fresh();
  const s = await out('get_species', { key: 'K1' });
  assert.equal(s.name, 'Aus bus');
  assert.equal(s.english, 'Malabar Aus');
  assert.equal(s.group, 'Birds');
  assert.equal(s.family, 'Cettiidae');
  assert.equal(s.order, 'Passeriformes');
  assert.deepEqual(s.iucn, { category: 'EN', year: 2021, doi: 'https://doi.org/10.2305/x', trend: 'Decreasing' });
  assert.equal(s.endemic, true);
  assert.equal(s.open_record, true);
  assert.deepEqual(s.states_with_open_record, ['Kerala']);
  assert.deepEqual(s.regions, ['5A Western Ghats: Malabar Plains', '5B Western Ghats: Mountains']);
  assert.deepEqual(s.described, { year: 1758, authority: 'L., 1758' });
  assert.deepEqual(s.sources, ['ZSI', 'GBIF']);
  assert.equal(s.photo.credit, 'Ann, CC BY-NC 4.0, iNaturalist (India)');
  assert.deepEqual(s.names_in_indian_languages, [['ml', 'aus pakshi']]);
  assert.equal(s.waiting_for_a_name.observations_in_india, 4);
  assert.match(s.waiting_for_a_name.identify, /taxon_id=555&place_id=6681/);
  const miss = await call('get_species', { key: 'NOPE' });
  assert.equal(miss.isError, true);
});

test('count_species: India, a state, a region (WII zone or province), IUCN, endemic, snakes', async () => {
  fresh();
  const all = await out('count_species', {});
  assert.deepEqual(all.counts, { documented: 6, open_record: 4, threatened: 3, recorded_since_2016: 2, endemic: 3 });
  assert.deepEqual(all.by_iucn, { CR: 1, EN: 1, VU: 1, LC: 2, NE: 1 });
  assert.equal((await out('count_species', { state: 'kerala' })).counts.documented, 2);         // Aus bus, Calotes
  assert.equal((await out('count_species', { region: 'Western Ghats' })).counts.documented, 3);  // 5A or 5B
  assert.equal((await out('count_species', { region: '6C' })).counts.documented, 1);
  assert.equal((await out('count_species', { iucn: ['threatened'], endemic: true })).counts.documented, 3);
  assert.equal((await out('count_species', { group: 'mammals' })).counts.documented, 2);         // both mammal groups
  assert.equal((await out('count_species', { suborder: 'snakes' })).counts.documented, 1);
  assert.equal((await out('count_species', { order: 'squamata', state: 'Karnataka' })).counts.documented, 2);
  assert.equal((await out('count_species', { family: 'agamidae' })).counts.documented, 1);
  assert.match((await out('count_species', { region: 'Western Ghats' })).note, /GBIF record/);
});

test('endemic: the answer names the groups no source marks yet, so 0 there reads as not marked', async () => {
  fresh();
  const r = await out('count_species', { endemic: true, group: 'reptiles' });
  assert.equal(r.counts.documented, 0);
  assert.match(r.note, /no endemic mark yet: Reptiles/);
  assert.doesNotMatch(r.note, /Birds/);           // Aus bus is marked
});

test('unknown filter values are tool errors that name the valid values', async () => {
  fresh();
  const r = await call('count_species', { state: 'Atlantis' });
  assert.equal(r.isError, true);
  assert.match(r.content[0].text, /Karnataka/);
  const eg = await call('list_species', { region: 'Eastern Ghats' });
  assert.equal(eg.isError, true);
  assert.match(eg.content[0].text, /6C/);
  assert.equal((await call('list_species', { iucn: ['XX'] })).isError, true);
});

test('list_species: filters, pages with a cursor, and the total', async () => {
  fresh();
  const r = await out('list_species', { iucn: ['threatened'], limit: 2 });
  assert.equal(r.total, 3);
  assert.deepEqual(r.species.map(s => s.name), ['Aus bus', 'Eus fus']);
  assert.ok(r.next_cursor);
  const r2 = await out('list_species', { iucn: ['threatened'], limit: 2, cursor: r.next_cursor });
  assert.deepEqual(r2.species.map(s => s.name), ['Gus hus']);
  assert.equal(r2.next_cursor, null);
  const row = r.species[0];
  assert.deepEqual(row, { key: 'K1', name: 'Aus bus', english: 'Malabar Aus', group: 'Birds', family: 'Cettiidae',
    iucn: 'EN', endemic: true, open_record: true, latest_record_year: 2020, described: 1758,
    url: 'https://yellide.com/species/K1/aus-bus' });
  assert.deepEqual((await out('list_species', { recorded_since: 2020 })).species.map(s => s.key), ['K1', 'K3']);
  assert.deepEqual((await out('list_species', { described_since: 2015 })).species.map(s => s.key), ['K5', 'K6']);
  assert.deepEqual((await out('list_species', { open_record: false })).species.map(s => s.key), ['K2', 'K6']);
  assert.deepEqual((await out('list_species', { suborder: 'lizards' })).species.map(s => s.key), ['K4']);
  assert.equal((await out('list_species', { limit: 500 })).species.length, 6);   // capped at 100, here all 6
});

test('new_species: described from India since a year, with the paper and records since', async () => {
  fresh();
  const r = await out('new_species', { since: 2010 });
  assert.equal(r.total, 2);
  const e = r.species[0];
  assert.deepEqual(e, { name: 'Eus fus', key: 'K5', year: 2015, group: 'Mammals: bats', type_locality_state: 'Kerala',
    journal: 'Zootaxa', link: 'https://tb.plazi.org/ABC', sources: ['Plazi'],
    records_since_description: 'recorded', latest_record_after: 2015,
    url: 'https://yellide.com/species/K5/eus-fus' });
  assert.equal(r.species[1].link, null);
  assert.deepEqual((await out('new_species', { since: 2007, group: 'reptiles' })).species.map(s => s.name), ['Gus hus']);
  assert.deepEqual((await out('new_species', { since: 2007, state: 'Kerala' })).species.map(s => s.name), ['Eus fus', 'Old one']);
  assert.equal((await call('new_species', { since: 1990 })).isError, true);
});

test('resources: about, groups, states and regions', async () => {
  fresh();
  const { result } = await (await rpc({ jsonrpc: '2.0', id: 1, method: 'resources/list' })).json();
  assert.deepEqual(result.resources.map(r => r.uri), ['yellide://about', 'yellide://groups', 'yellide://states', 'yellide://districts', 'yellide://regions']);
  const read = async uri => (await (await rpc({ jsonrpc: '2.0', id: 1, method: 'resources/read', params: { uri } })).json()).result.contents[0];
  assert.match((await read('yellide://about')).text, /open record/);
  assert.deepEqual(JSON.parse((await read('yellide://states')).text), ['Karnataka', 'Kerala']);
  const regions = JSON.parse((await read('yellide://regions')).text);
  assert.deepEqual(regions.zones['Western Ghats'], ['5A', '5B']);
  assert.deepEqual(JSON.parse((await read('yellide://districts')).text), { Karnataka: ['Aurangabad'], Kerala: ['Aurangabad', 'Ernakulam'] });
});

test('the data is read once per isolate and week: a second call reads no index again', async () => {
  fresh();
  await call('count_species', {});
  const before = env.DATA.gets.length;
  await call('list_species', { state: 'Kerala' });
  assert.deepEqual(env.DATA.gets.slice(before), []);
});

test('shards are read each time (an isolate keeps only the index files); a failed read is tried again', async () => {
  fresh();
  await call('get_species', { key: 'K1' });
  const before = env.DATA.gets.length;
  await call('get_species', { key: 'K1' });
  assert.deepEqual(env.DATA.gets.slice(before).sort(), [BASE + `pic/${shardOf('K1')}.json`, BASE + `sp/${shardOf('K1')}.json`]);
  fresh();
  const ok = env.DATA.get;
  let fail = true;
  env.DATA.get = async k => { if (fail && k.endsWith('rows.bin')) throw new Error('R2 down'); return ok.call(env.DATA, k); };
  const r = await rpc({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'count_species', arguments: {} } });
  assert.equal((await r.json()).error.code, -32603);
  fail = false;
  assert.equal((await out('count_species', {})).counts.documented, 6);
});

test('years must be years', async () => {
  fresh();
  assert.equal((await call('list_species', { recorded_since: 'abc' })).isError, true);
  assert.equal((await call('new_species', { since: 'x' })).isError, true);
});

test('tool calls are counted by tool name (metrics), never with their arguments', async () => {
  fresh();
  const seen = [];
  const db = { prepare: () => ({ bind: (...a) => a }), batch: async q => { seen.push(...q); } };
  await rpc({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'find_species', arguments: { name: 'aus' } } }, { db });
  assert.equal(seen.length, 1);
  assert.deepEqual(seen[0].slice(1), ['mcp', 'find_species']);
});

test('a district: by name or LGD code, with the years and records there; threatened species too, with the exact year', async () => {
  fresh();
  const c = await out('count_species', { district: 'ernakulam' });
  assert.deepEqual(c.counts, { documented: 3, open_record: 3, threatened: 2, recorded_since_2016: 1, endemic: 2 });  // 2019 there
  assert.match(c.note, /GBIF record of it is placed in the district/);
  assert.match(c.note, /does not show that it lives there now/);
  assert.match(c.note, /Wild Life \(Protection\) Act/);
  assert.equal((await out('count_species', { district: 101 })).counts.documented, 3);
  const l = await out('list_species', { district: 'Ernakulam', iucn: ['threatened'] });
  assert.deepEqual(l.species.map(s => [s.key, s.in_district]), [
    ['K1', { first_year: 2010, latest_year: 2019, records: 5 }], ['K5', { first_year: 2015, latest_year: 2015, records: 1 }]]);
  assert.deepEqual((await out('list_species', { district: 'Ernakulam', recorded_since: 2016 })).species.map(s => s.key), ['K1']);
  assert.equal((await out('list_species', {})).species[0].in_district, undefined);      // no district: no district years
});

test('a district name in two states needs the state; an unknown district is a tool error', async () => {
  fresh();
  const both = await call('count_species', { district: 'Aurangabad' });
  assert.equal(both.isError, true);
  assert.match(both.content[0].text, /Karnataka/);
  assert.match(both.content[0].text, /Kerala/);
  assert.deepEqual((await out('list_species', { district: 'Aurangabad', state: 'Karnataka' })).species.map(s => s.key), ['K3']);
  assert.equal((await out('count_species', { district: 'Aurangabad', state: 'Kerala' })).counts.documented, 0);   // no file: none
  assert.match((await call('count_species', { district: 'Ernakulam', state: 'Karnataka' })).content[0].text, /Unknown district "Ernakulam" in Karnataka/);
  const no = await call('count_species', { district: 'Atlantis' });
  assert.equal(no.isError, true);
  assert.match(no.content[0].text, /yellide:\/\/districts/);
});

test('no tool takes or gives a point or coordinates', async () => {
  fresh();
  const { result } = await (await rpc({ jsonrpc: '2.0', id: 1, method: 'tools/list' })).json();
  const FINE = /lat|lon|lng|coord|point|pincode|block|village|radius|near|bbox|geo/i;
  for (const t of result.tools) {
    for (const p of Object.keys(t.inputSchema.properties || {})) assert.doesNotMatch(p, FINE, `${t.name}.${p}`);
  }
  const s = await out('get_species', { key: 'K1' });
  const keys = JSON.stringify(s).match(/"([a-z_]+)":/g).map(k => k.slice(1, -2));
  for (const k of keys) assert.doesNotMatch(k, /lat|lon|lng|coord|cell/i, k);
});

test('places through bharatlas: the instructions say how, and answers say "recorded in", not "found here"', async () => {
  fresh();
  const { result } = await (await rpc({ jsonrpc: '2.0', id: 0, method: 'initialize', params: { protocolVersion: '2025-06-18' } })).json();
  assert.match(result.instructions, /bharatlas/);
  assert.match(result.instructions, /locate/);
  assert.match(result.instructions, /recorded in/i);
  assert.match(result.instructions, /lgd_districts/);
  assert.match(result.instructions, /district/);
  const both = await out('count_species', { state: 'Kerala', region: 'Western Ghats' });
  assert.match(both.note, /records in the state and records in the region/);
  assert.match(both.note, /not always in the part where they meet/);
});

test('/.well-known/mcp.json: points agents at /mcp and names the tools tools/list gives', async () => {
  const m = JSON.parse(readFileSync(new URL('../site/.well-known/mcp.json', import.meta.url)));
  assert.equal(m.name, 'yellide');
  assert.equal(m.homepage, 'https://yellide.com');
  assert.deepEqual(m.remotes, [{ type: 'streamable-http', url: 'https://yellide.com/mcp' }]);
  const { result } = await (await rpc({ jsonrpc: '2.0', id: 1, method: 'tools/list' })).json();
  assert.deepEqual(m.tools, result.tools.map((t) => t.name));
});
