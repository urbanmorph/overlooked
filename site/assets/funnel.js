// The evidence funnel on the home page: from the species documented in India to where and when they are recorded.
// Each stage nests in the one before and belongs to the gap it measures: Linnean (is the species named and listed),
// Wallacean (do we know where it lives). Built from summary.json; history.json gives the change since the last list.

import { fmt } from './common.js';

// India rows of summary.json: [documented, open record, IUCN counts, threatened, open record in a state,
// of them recorded in a state since recent_from]. A state row: [open record, threatened, recorded since recent_from].
const INDIA = [
  { key: 'documented', gap: 'Linnean', at: 0, label: 'Documented in India' },
  { key: 'observed', gap: 'Wallacean', at: 1, label: 'With an open record',
    lost: n => `${fmt(n)} known only from checklists and papers: no open record yet` },
  { key: 'in_state', gap: 'Wallacean', at: 4, label: 'Open record placed in a state',
    lost: n => `${fmt(n)} with no record placed in a state` },
  { key: 'recent', gap: 'Wallacean', at: 5, label: 'Recorded in a state in the last 10 years',
    lost: (n, S) => `${fmt(n)} not recorded in a state since ${S.recent_from}` },
];
const STATE = [
  { key: 'observed', gap: 'Wallacean', at: 0, label: 'With an open record here' },
  { key: 'recent', gap: 'Wallacean', at: 2, label: 'Recorded here in the last 10 years',
    lost: (n, S) => `${fmt(n)} not recorded here since ${S.recent_from}` },
];

const sum = (rows, gis, at) => {
  let total = 0;
  for (const gi of gis) {
    const v = (rows?.[gi] || [])[at];
    if (v == null) return null;
    total += v;
  }
  return total;
};

/** The stages for some groups, for India or one state (a state code). A stage the summary does not have is left
 * out. Each stage: {key, gap, label, value, share (of the first stage), lost (to the stage before), lostText}.
 * unlisted: names not on the India list, known only from observations that wait (India only). */
export function funnel(S, gis, state = null) {
  const defs = state == null ? INDIA : STATE, rows = state == null ? S.india : S.by_state?.[state];
  const stages = [];
  for (const d of defs) {
    const value = sum(rows, gis, d.at);
    if (value == null) continue;
    const before = stages.at(-1), lost = before ? before.value - value : 0;
    stages.push({ key: d.key, gap: d.gap, label: d.label, value,
      share: stages.length ? (stages[0].value ? value / stages[0].value : 0) : 1, lost,
      lostText: before && d.lost ? d.lost(lost, S) : '' });
  }
  return { stages, unlisted: state == null && S.unlisted ? gis.reduce((a, gi) => a + (S.unlisted[gi] || 0), 0) : null };
}

/** One history.json measure summed over groups, oldest first; a list that lacks it is left out. */
export function sumSeries(H, measure, gis) {
  const i = H?.measures?.indexOf(measure) ?? -1;
  if (i < 0) return [];
  return H.lists.map(l => ({ period: l.period, value: sum(l.groups, gis, i) })).filter(p => p.value != null);
}
