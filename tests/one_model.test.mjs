// Every page and server function reads and shows a species one way: site/assets/species_model.js, with the facts the
// pipeline publishes in summary.json (row fields, status and IUCN words, threatened codes, the endemic label). This
// test fails when a file keeps its own copy again, so the pages cannot drift apart. Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const MODEL = 'site/assets/species_model.js';
function files(dir) {
  return readdirSync(join(ROOT, dir)).flatMap(f => {
    const rel = `${dir}/${f}`;
    return statSync(join(ROOT, rel)).isDirectory() ? files(rel) : rel.endsWith('.js') ? [rel] : [];
  });
}
const CODE = [...files('site/assets'), ...files('functions')].filter(f => f !== MODEL);

// [what, pattern, files allowed to have it and why]
const COPIES = [
  ['an HTML escape of its own', /const esc\s*=/, []],
  // The AI shortlist names candidates for a taxonomist to check: plain Latin names with no key, kept as they are.
  ['species-name markup of its own (use speciesName, speciesText or speciesInline)', /<i>\$\{esc\((?:name|r\.name|n|latin)\)\}<\/i>/,
    ['site/assets/shortlist.js']],
  // The agent server's tool descriptions are fixed text an agent reads before any list is loaded.
  ['the threatened codes', /['"]?CR['"]?,\s*['"]?EN['"]?,\s*['"]?VU\b/, ['functions/lib/mcp.js']],
  ['IUCN category words', /Critically Endangered/, []],
  ['status words', /No open record yet['"],\s*['"]Open record/, []],
  ['the endemic label lookup', /code === ['"]end['"]/, []],
  ['the shard hash', /0x811c9dc5/i, []],
  ['the English name read by position from the picture files', /pic\??\.\[5\]/, []],
];

test('no page or server function keeps its own copy of a species rule, word or markup', () => {
  const found = [];
  for (const f of CODE) {
    const text = readFileSync(join(ROOT, f), 'utf8');
    for (const [what, re, allowed] of COPIES) if (re.test(text) && !allowed.includes(f)) found.push(`${f}: ${what}`);
  }
  assert.deepEqual(found, []);
});

test('the shared module is where those rules live', () => {
  const text = readFileSync(join(ROOT, MODEL), 'utf8');
  for (const name of ['esc', 'speciesName', 'speciesText', 'speciesTitle', 'speciesInline', 'iucnBadge', 'model', 'shardOf', 'englishOf', 'fillEnglish', 'nameMatches']) {
    assert.match(text, new RegExp(`export (const|function|async function) ${name}\\b`), name);
  }
});
