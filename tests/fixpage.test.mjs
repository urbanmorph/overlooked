// Records to fix has its own page (/fix); the home page links to it. Run: node --test tests/fixpage.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CATS } from '../site/assets/cats.js';

const page = name => readFileSync(new URL(`../site/${name}`, import.meta.url), 'utf8');

test('the records to fix are on their own page, with a state and a group to choose, not on the home page', () => {
  const fix = page('fix.html'), home = page('index.html');
  for (const id of ['fix-kpis', 'fix-holders', 'fix-only', 'fix-source', 'fstate', 'fgroup']) assert.ok(fix.includes(`id="${id}"`), id);
  assert.ok(!home.includes('id="fix-kpis"'));
  assert.ok(home.includes('href="/fix"'));
  assert.ok(page('sitemap.xml').includes('/fix</loc>'));
  for (const p of ['index.html', 'fix.html', 'changes.html']) assert.ok(page(p).includes('<a href="/fix"'), p);
});

test('one list of group families for the home page and the fix page', () => {
  assert.equal(CATS.length, 10);
  const birds = CATS.find(c => c[0] === 'birds');
  assert.ok(birds[2]('Birds') && !birds[2]('Fish'));
});
