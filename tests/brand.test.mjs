// The site is called yellide since 11 Nov 2026 (it was Overlooked): the wordmark, page titles and the MCP server
// carry the name; the icons stay, and the footer still credits The Overlooked Species. Run: node --test tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createHash } from 'node:crypto';

const OLD_OG = '2ab46ffd8c79';   // the Overlooked share image

const read = (f) => fs.readFileSync(new URL('../' + f, import.meta.url), 'utf8');
const PAGES = fs.readdirSync(new URL('../site/', import.meta.url)).filter((f) => f.endsWith('.html') && !/^google/.test(f));

test('every page wears the yellide wordmark with "species of India", the same icon, and a yellide title', () => {
  for (const f of PAGES) {
    const h = read('site/' + f);
    assert.ok(h.includes('<b>yellide</b><span>species of India</span>'), f);
    assert.ok(h.includes('<link rel="icon" href="/favicon.svg"') && h.includes('<link rel="apple-touch-icon" href="/apple-touch-icon.png">'), f);
    assert.match(h.match(/<title>([^<]*)<\/title>/)[1], /yellide/, f);
    assert.ok(!/Overlooked(?! Species| until November 2026)/.test(h.replace(/<script type="application\/ld\+json">.*?<\/script>/s, "")), `${f} still says Overlooked`);
    assert.ok(h.includes('The Overlooked Species'), `${f} credits The Overlooked Species`);
  }
});

test('on a phone the wordmark drops its "species of India" line', () => {
  assert.match(read('site/assets/style.css'), /@media \(max-width: 560px\) \{ \.brand span \{ display: none \} \}/);
});

test('species pages, the MCP server and the data credit the site as yellide', () => {
  for (const f of ['functions/lib/mcp.js', 'functions/lib/species_page.js', 'site/assets/species.js', 'site/llms.txt', 'pipeline/site_data.py', 'scripts/pages.py'])
    assert.ok(!/(?<!formerly )Overlooked(?! Species| until November 2026)|overlooked:\/\//.test(read(f)), f);
});

test('search engines and AI answers learn the old name: alternateName in the site and dataset schema, a footer line, llms.txt, README', () => {
  const ld = (f) => JSON.parse(read('site/' + f).match(/<script type="application\/ld\+json">(.*?)<\/script>/s)[1]);
  const site = ld('index.html');
  assert.equal(site.name, 'yellide');
  assert.deepEqual(site.alternateName, ['Overlooked', 'Overlooked India']);
  assert.ok(site.sameAs.includes('https://github.com/urbanmorph/overlooked'));
  assert.ok(ld('method.html').alternateName.includes('Overlooked'));
  for (const f of PAGES) assert.ok(read('site/' + f).includes('was called Overlooked until November 2026'), f);
  assert.match(read('site/llms.txt'), /^# yellide\n\n> [^\n]*formerly Overlooked/);
  assert.match(read('README.md'), /^# yellide\n/);
});

test('the share image is the yellide one', () => {
  const png = fs.readFileSync(new URL('../site/og.png', import.meta.url));
  assert.equal(png.readUInt32BE(16), 1200);
  assert.equal(png.readUInt32BE(20), 630);
  assert.notEqual(createHash('sha256').update(png).digest('hex').slice(0, 12), OLD_OG);
});
