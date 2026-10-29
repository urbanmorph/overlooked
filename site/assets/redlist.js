// Red List assessments of the India list: what IUCN has assessed, and where an assessment waits or is out of date.
// The counts use IUCN's categories and the year of each assessment (IUCN's CC BY copy on GBIF) with the list's own
// records; nothing else from IUCN. Order and keys as summary.json "redlist".

import { sumGroups } from './common.js?v=9455fd8cc8';

export const REDLIST = [
  { key: 'assessed', label: () => 'Assessed by IUCN', note: () => 'species with a category on the IUCN Red List', share: true },
  { key: 'assessable', label: () => 'Not assessed, with open records in 5 or more states',
    note: () => 'enough open records for an assessor to start' },
  { key: 'out_of_date', label: S => `Assessed before ${S.recent_from}`,
    note: () => 'IUCN aims to assess each species again every 5 to 10 years' },
  { key: 'dd_newer', label: () => 'Data Deficient, with newer records',
    note: () => 'records with a place after the year of the assessment: data the assessor did not have' },
  { key: 'threatened_not_recent', label: () => 'Threatened, with no recent record',
    note: S => `Critically Endangered, Endangered or Vulnerable, with no record placed in a state since ${S.recent_from}` },
  { key: 'endemic_not_assessed', label: () => 'Endemic to India, not assessed',
    note: () => 'found only in India, so records from India decide its assessment' },
];

/** The rows for some groups: {key, label, note, value, of (documented, for the assessed share)}; [] without counts. */
export function redlist(S, gis) {
  if (!S.redlist) return [];
  const documented = sumGroups(S.india, gis, 0);
  return REDLIST.map(r => ({ key: r.key, label: r.label(S), note: r.note(S), value: sumGroups(S.redlist[r.key], gis),
    of: r.share ? documented : null }));
}
