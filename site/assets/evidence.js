// Evidence per species on the species page (pipeline/evidence.py): type specimens and photos from India, a DNA
// barcode, and names in Indian languages. undefined: not measured in this list; null: measured, none.

import { fmt } from './common.js?v=9455fd8cc8';

const LANGS = [['hi', 'Hindi'], ['bn', 'Bengali'], ['te', 'Telugu'], ['mr', 'Marathi'], ['ta', 'Tamil'], ['ur', 'Urdu'],
  ['gu', 'Gujarati'], ['kn', 'Kannada'], ['ml', 'Malayalam'], ['or', 'Odia'], ['pa', 'Punjabi'], ['as', 'Assamese'],
  ['mai', 'Maithili'], ['sat', 'Santali'], ['ks', 'Kashmiri'], ['ne', 'Nepali'], ['sd', 'Sindhi'], ['kok', 'Konkani'],
  ['gom', 'Konkani (Goa)'], ['doi', 'Dogri'], ['mni', 'Manipuri'], ['brx', 'Bodo'], ['sa', 'Sanskrit'], ['lus', 'Mizo'],
  ['tcy', 'Tulu'], ['bho', 'Bhojpuri']];
const ORDER = new Map(LANGS.map(([c], i) => [c, i]));
const NAME = new Map(LANGS);

/** "3 records" for a count; null when measured and none; undefined when not measured. */
export function countText(n, measured, unit) {
  if (!measured) return undefined;
  return n ? `${fmt(n)} ${unit}${n === 1 ? '' : 's'}` : null;
}

/** 2: a barcode from India (BOLD); 1: from elsewhere only; 0: none (null); undefined: not measured. */
export function barcodeText(b) {
  if (b === undefined || b === null) return undefined;
  return b === 2 ? 'A barcode from India' : b === 1 ? 'A barcode, but not from India' : null;
}

/** [[code, name]] -> [{lang, names}], one entry per language, languages in a fixed order. */
export function localNames(pairs) {
  const by = new Map();
  for (const [code, name] of pairs || []) by.set(code, [...(by.get(code) || []), name]);
  return [...by].sort((a, b) => (ORDER.get(a[0]) ?? 99) - (ORDER.get(b[0]) ?? 99))
    .map(([code, names]) => ({ lang: NAME.get(code) || code, names }));
}
