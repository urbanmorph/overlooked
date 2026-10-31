// The seven gaps in what we know about species (the "shortfalls" of Hortal et al. 2015, Annual Review of Ecology,
// Evolution, and Systematics 46: 523-549), with what the master list measures of each today. A gap we do not
// measure yet says where its data would come from.

import { fmt, sumGroups } from './common.js?v=9455fd8cc8';

// Each gap is counted the same way as the species page's group bars: S.gaps_known[gi][i], the documented species of
// group gi where gap i is known (pipeline/master.py), over the documented species of the groups that measure it.
// note(S, gis, k): what the count is; source: where the data of a gap not measured yet would come from.
const partly = (k, gis) => (k.groups < gis.length ? `; measured for ${k.groups} of the ${gis.length} groups` : '');
export const GAPS = [
  { term: 'Linnean', plain: 'Which species exist', question: 'Is every species described and named?',
    note: (S, gis) => `of documented species have a known year of description. ${fmt(sumGroups(S.described_recent, gis) ?? 0)} described since ${S.recent_from}: the list is still growing${S.types == null ? ''
      : `. ${fmt(sumGroups(S.types, gis))} have a type specimen from India on GBIF; ${fmt(sumGroups(S.local_names, gis))} have a name in an Indian language on Wikidata`}` },
  { term: 'Wallacean', plain: 'Where species live', question: 'Do we know where each species lives?',
    note: S => `of documented species have a record placed in a state since ${S.recent_from}` },
  { term: 'Prestonian', plain: 'How many there are', question: 'Do we know how many of each species there are, and if that changes?',
    note: (S, gis, k) => `of documented species have a known population trend, rising, stable or falling (IUCN Red List assessments; State of India\u2019s Birds 2023 for birds)${partly(k, gis)}`,
    source: 'IUCN Red List population trends (IUCN 2026, version 2026-1); State of India\u2019s Birds for birds' },
  { term: 'Darwinian', plain: 'How species are related', question: 'Do we know each species’ place in the tree of life?',
    note: (S, gis, k) => `of documented species have a DNA sequence or sample from India on GBIF, or a DNA barcode from India on BOLD${partly(k, gis)}${S.barcodes == null ? ''
      : `. ${fmt(sumGroups(S.barcodes, gis))} have a DNA barcode on BOLD (${fmt(sumGroups(S.barcodes_india, gis))} from India)`}`,
    source: 'GBIF and BOLD Systems' },
  { term: 'Raunkiæran', plain: 'What species are like', question: 'Do we know each species’ traits: size, life cycle, when it flowers or breeds?',
    note: (S, gis, k) => `of documented species have a record placed in India with a life stage, a sex, or flowers or fruits (on GBIF, mostly iNaturalist annotations)${partly(k, gis)}`,
    source: 'iNaturalist annotations, through GBIF' },
  { term: 'Hutchinsonian', plain: 'What conditions species need', question: 'Do we know the climate and habitat each species can live in?',
    note: (S, gis, k) => `of documented species have records placed to 1 km or better at 10 or more places in India: enough to relate a species to climate maps${partly(k, gis)}`,
    source: 'exact records on GBIF, with climate maps' },
  { term: 'Eltonian', plain: 'How species interact', question: 'Do we know what each species eats, pollinates or lives on?',
    note: (S, gis, k) => `of documented species have an interaction recorded in India (GloBI)${partly(k, gis)}${S.interactions == null ? '' : `; ${fmt(sumGroups(S.interactions, gis))} have one recorded anywhere`}`,
    source: 'GloBI, the Global Biotic Interactions database' },
];

/** Gap i for some groups: {value, of, groups}: the documented species where it is known, the documented species, over
 * the groups that measure it (`groups` of them); null when none does. */
export function known(S, gis, i) {
  let value = 0, of = 0, groups = 0;
  for (const gi of gis) {
    const v = S.gaps_known?.[gi]?.[i];
    if (v == null) continue;
    value += v; of += S.india?.[gi]?.[0] || 0; groups += 1;
  }
  return groups ? { value, of, groups } : null;
}

/** Each gap for some groups (India): {term, plain, question, value (null: not measured), of, note, source}. */
export function gaps(S, gis) {
  return GAPS.map((g, i) => {
    const k = known(S, gis, i);
    return { ...g, value: k ? k.value : null, of: k ? k.of : null, note: k ? g.note(S, gis, k) : '' };
  });
}

/** The text for a gap with no count: not measured yet for these groups, with where its data would come from. */
export const gapAbsent = g => `Not measured yet for these groups.${g.source ? ` Data: ${g.source}.` : ''}`;
