import { test } from 'node:test';
import assert from 'node:assert/strict';
import { barcodeText, countText, localNames, shortlistLink } from '../site/assets/evidence.js';

test('a count of records, none, or not measured', () => {
  assert.equal(countText(3, true, 'record'), '3 records');
  assert.equal(countText(1, true, 'record'), '1 record');
  assert.equal(countText(null, true, 'record'), null);
  assert.equal(countText(undefined, false, 'record'), undefined);
});

test('a DNA barcode from India, from elsewhere only, or none', () => {
  assert.match(barcodeText(2), /from India/);
  assert.match(barcodeText(1), /not from India/);
  assert.equal(barcodeText(0), null);
  assert.equal(barcodeText(undefined), undefined);
});

test('local names grouped by language, in the order of the languages list', () => {
  assert.deepEqual(localNames([['ta', 'மயில்'], ['hi', 'मोर'], ['hi', 'मयूर'], ['xx', 'y']]),
    [{ lang: 'Hindi', names: ['मोर', 'मयूर'] }, { lang: 'Tamil', names: ['மயில்'] }, { lang: 'xx', names: ['y'] }]);
  assert.deepEqual(localNames(null), []);
});

test('the shortlist observations a species is on: a count and a link to them, or nothing', () => {
  const l = shortlistLink({ 'Aus bus': ['true-bugs', 12], 'Cus dus': ['moths', 1] }, 'Aus bus');
  assert.deepEqual(l, { n: 12, href: '/shortlist?group=true-bugs&name=Aus+bus' });
  assert.equal(shortlistLink({ 'Aus bus': ['true-bugs', 12] }, 'Gus hus'), null);
  assert.equal(shortlistLink(null, 'Aus bus'), null);
});
