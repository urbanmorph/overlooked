// The seven gaps in what we know about species (the "shortfalls" of Hortal et al. 2015, Annual Review of Ecology,
// Evolution, and Systematics 46: 523-549), with what the master list measures of each today. A gap we do not
// measure yet says where its data would come from.

import { fmt, sumGroups } from './common.js?v=9455fd8cc8';

// measure(S, gis) -> {value, of?}: a count, and the species it is a share of. note(S, gis): what the count is.
export const GAPS = [
  { term: 'Linnean', plain: 'Which species exist', question: 'Is every species described and named?',
    measure: (S, gis) => ({ value: sumGroups(S.described_recent, gis) }),
    note: S => `species on the India list described since ${S.recent_from}: the list is still growing` },
  { term: 'Wallacean', plain: 'Where species live', question: 'Do we know where each species lives?',
    measure: (S, gis) => ({ value: sumGroups(S.india, gis, 5), of: sumGroups(S.india, gis, 0) }),
    note: S => `of documented species recorded in a state since ${S.recent_from}` },
  { term: 'Prestonian', plain: 'How many there are', question: 'Do we know how many of each species there are, and if that changes?',
    source: 'IUCN Red List population trends (IUCN has to permit us to publish counts from them); State of India\u2019s Birds for birds' },
  { term: 'Darwinian', plain: 'How species are related', question: 'Do we know each species’ place in the tree of life?',
    measure: (S, gis) => ({ value: sumGroups(S.dna, gis), of: sumGroups(S.india, gis, 0) }),
    note: () => 'of documented species have a DNA sequence or sample from India on GBIF' },
  { term: 'Raunkiæran', plain: 'What species are like', question: 'Do we know each species’ traits: size, life cycle, when it flowers or breeds?',
    measure: (S, gis) => ({ value: sumGroups(S.traits, gis), of: sumGroups(S.india, gis, 0) }),
    note: () => 'of documented species have a record placed in India with a life stage, a sex, or flowers or fruits (on GBIF, mostly iNaturalist annotations)',
    source: 'iNaturalist annotations, through GBIF' },
  { term: 'Hutchinsonian', plain: 'What conditions species need', question: 'Do we know the climate and habitat each species can live in?',
    source: 'exact records with climate maps' },
  { term: 'Eltonian', plain: 'How species interact', question: 'Do we know what each species eats, pollinates or lives on?',
    measure: (S, gis) => ({ value: sumGroups(S.interactions_india, gis), of: sumGroups(S.india, gis, 0) }),
    note: (S, gis) => `of documented species have an interaction recorded in India (GloBI); ${fmt(sumGroups(S.interactions, gis))} have one recorded anywhere`,
    source: 'GloBI, the Global Biotic Interactions database' },
];

/** Each gap for some groups (India): {term, plain, question, value (null: not measured), of, note, source}. */
export function gaps(S, gis) {
  return GAPS.map(g => {
    const m = g.measure ? g.measure(S, gis) : { value: null };
    const measured = m.value != null && (m.of === undefined || m.of != null);
    return { ...g, value: measured ? m.value : null, of: measured ? m.of : null, note: measured && g.note ? g.note(S, gis) : '' };
  });
}

/** The text for a gap with no count: left out by the filters (a count the group files cannot give), or not measured
 * yet, with where its data would come from. */
export const gapAbsent = (g, filtered) => (g.measure && filtered ? 'Not counted when filters are on.' : `Not measured yet. Data: ${g.source}.`);
