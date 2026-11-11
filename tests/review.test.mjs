// Names to check on the Records to fix page (site/assets/review.js; data: pipeline/name_review.py review/names.json).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { reviewRowHTML, issueHref, matchesRow } from '../site/assets/review.js';

const row = ['4Q34B', 'Pteropus vampyrus', 17, ['Pteropus giganteus'],
  ['Pteropus faunulus', 'Pteropus hypomelanus', 'Pteropus medius', 'Pteropus melanotus', 'Pteropus a', 'Pteropus b'], true,
  'Large Flying Fox', [null, null, 'Indian Flying Fox', null, null, null]];

test('a name to check: the species, the old names that reach it, its relatives on Indian checklists, a way to answer', () => {
  const h = reviewRowHTML(row);
  assert.match(h, /href="\/species\/4Q34B\/pteropus-vampyrus"><i>Pteropus vampyrus<\/i>/);
  assert.match(h, /<i>Pteropus giganteus<\/i>/);
  assert.match(h, /<i>Pteropus medius<\/i>/);
  assert.match(h, /and 1 more/);                                   // at most 5 relatives shown
  assert.match(h, /open records in 17 states/);
  assert.match(h, /href="https:\/\/github\.com\/urbanmorph\/overlooked\/issues\/new\?/);
  assert.doesNotMatch(reviewRowHTML(['K', 'Aus <b>', 0, ['Aus c'], ['Aus d'], false]), /<b>/);   // escaped
});

test('a species whose IUCN range map leaves out India says so, with the IUCN citation', () => {
  assert.match(reviewRowHTML(row), /IUCN Red List range map does not include India/);
  assert.match(reviewRowHTML(row), /2026-1/);
  assert.doesNotMatch(reviewRowHTML([...row.slice(0, 5), false]), /IUCN/);
});

test('the answer opens a GitHub issue with the species named', () => {
  const u = new URL(issueHref(row));
  assert.equal(u.searchParams.get('title'), 'Name to check: Pteropus vampyrus');
  assert.match(u.searchParams.get('body'), /Pteropus giganteus/);
  assert.match(u.searchParams.get('body'), /IUCN Red List range map does not include India/);
});

test('a row shows the common names of the species and of its relatives where known', () => {
  const h = reviewRowHTML(row);
  assert.match(h, /<i>Pteropus vampyrus<\/i><\/a> Large Flying Fox/);
  assert.match(h, /<i>Pteropus medius<\/i> \(Indian Flying Fox\)/);
  assert.match(h, /<i>Pteropus faunulus<\/i>,/);                       // no common name: none shown
  assert.doesNotMatch(reviewRowHTML(['K', 'Aus bus', 1, ['Aus c'], ['Aus d'], false, '<b>x', ['<b>y']]), /<b>/);
  assert.match(reviewRowHTML(['K', 'Aus bus', 1, ['Aus c'], ['Aus d'], false]), /Aus bus/);   // older files: no names
});

test('the filter matches the Latin or common name of the species, its older names and its relatives', () => {
  for (const q of ['vampyrus', 'large flying', 'GIGANTEUS', 'indian flying fox', '  fox ']) assert.ok(matchesRow(row, q), q);
  assert.ok(matchesRow(row, ''));
  assert.ok(!matchesRow(row, 'pigeon'));
  assert.ok(matchesRow([...row.slice(0, 6), 'Sri Lanka Green-Pigeon', []], 'green pigeon'));   // a hyphen as a space
  assert.ok(matchesRow([...row.slice(0, 6), "Pallas's Leaf Warbler", []], 'pallass leaf'));     // no apostrophes
});
