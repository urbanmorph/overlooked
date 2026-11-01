// Names to check on the Records to fix page (site/assets/review.js; data: pipeline/name_review.py review/names.json).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reviewRowHTML, issueHref } from '../site/assets/review.js';

const row = ['4Q34B', 'Pteropus vampyrus', 17, ['Pteropus giganteus'],
  ['Pteropus faunulus', 'Pteropus hypomelanus', 'Pteropus medius', 'Pteropus melanotus', 'Pteropus a', 'Pteropus b']];

test('a name to check: the species, the old names that reach it, its relatives on Indian checklists, a way to answer', () => {
  const h = reviewRowHTML(row);
  assert.match(h, /href="\/species\?key=4Q34B"><i>Pteropus vampyrus<\/i>/);
  assert.match(h, /<i>Pteropus giganteus<\/i>/);
  assert.match(h, /<i>Pteropus medius<\/i>/);
  assert.match(h, /and 1 more/);                                   // at most 5 relatives shown
  assert.match(h, /open records in 17 states/);
  assert.match(h, /href="https:\/\/github\.com\/urbanmorph\/overlooked\/issues\/new\?/);
  assert.doesNotMatch(reviewRowHTML(['K', 'Aus <b>', 0, ['Aus c'], ['Aus d']]), /<b>/);   // escaped
});

test('the answer opens a GitHub issue with the species named', () => {
  const u = new URL(issueHref(row));
  assert.equal(u.searchParams.get('title'), 'Name to check: Pteropus vampyrus');
  assert.match(u.searchParams.get('body'), /Pteropus giganteus/);
});
