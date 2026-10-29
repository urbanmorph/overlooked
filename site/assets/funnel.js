// "Where species live: how far our knowledge goes" (the Wallacean gap): each species of the India list counted once,
// at the furthest step we know about it. The segments add up to the documented species, and each one is a degree of
// the gap: only in checklists and papers, no record with a place, no recent record. Built from summary.json;
// history.json gives the changes.

import { sumGroups } from './common.js?v=9455fd8cc8';

// The steps, least known first. view: the map view a segment selects (checklists give no states: none).
export const STEPS = [
  { key: 'k1', view: null, name: 'Only in checklists and papers',
    long: 'Documented, but no open record yet: known from checklists, papers and specimens that are not online.' },
  { key: 'k2', view: 'observed', name: 'Open record, no place',
    long: 'An open record, but none placed in a state.' },
  { key: 'k3', view: 'observed', name: 'Placed, not recent',
    long: 'An open record placed in a state, but none in the last 10 years.' },
  { key: 'k4', view: 'recent', name: 'Recorded in the last 10 years',
    long: 'An open record placed in a state in the last 10 years.' },
];
const STEP = Object.fromEntries(STEPS.map(s => [s.key, s]));
// When a summary lacks the years (lists from before 29 October 2026, or a state with filters on).
const OBS = { key: 'obs', view: 'observed', name: 'With an open record', long: 'At least one open record.' };
const HERE = { k3: { name: 'Open record here, not recent', long: 'An open record in this state, but none in the last 10 years.' },
  k4: { name: 'Recorded here in the last 10 years', long: 'An open record in this state in the last 10 years.' } };

/** The segments for some groups, for India or one state (a state code). India rows of summary.json: [documented,
 * open record, IUCN counts, threatened, open record in a state, of them recent]; a state row: [open record,
 * threatened, recent]. Returns {base, segments: [{key, view, name, long, value, share}], unlisted (India only)}. */
export function knowledge(S, gis, state = null) {
  const seg = (def, value, base) => ({ ...def, value, share: base ? value / base : 0 });
  if (state != null) {
    const rows = S.by_state?.[state], obs = sumGroups(rows, gis, 0) ?? 0, recent = sumGroups(rows, gis, 2);
    const segments = recent == null ? [seg(OBS, obs, obs)]
      : [seg({ ...STEP.k3, ...HERE.k3 }, obs - recent, obs), seg({ ...STEP.k4, ...HERE.k4 }, recent, obs)];
    return { base: obs, segments, unlisted: null };
  }
  const doc = sumGroups(S.india, gis, 0), obs = sumGroups(S.india, gis, 1), placed = sumGroups(S.india, gis, 4), recent = sumGroups(S.india, gis, 5);
  const segments = placed == null || recent == null ? [seg(STEP.k1, doc - obs, doc), seg(OBS, obs, doc)]
    : [seg(STEP.k1, doc - obs, doc), seg(STEP.k2, obs - placed, doc), seg(STEP.k3, placed - recent, doc), seg(STEP.k4, recent, doc)];
  return { base: doc, segments, unlisted: S.unlisted ? gis.reduce((a, gi) => a + (S.unlisted[gi] || 0), 0) : null };
}

/** Each India segment's change since the list before, from history.json, summed over groups: {k1: n or null, ...}. */
export function segmentChanges(H, gis) {
  if (!H?.lists?.length || H.lists.length < 2) return {};
  const at = m => H.measures.indexOf(m);
  const parts = l => {
    const v = m => (at(m) < 0 ? null : sumGroups(l.groups, gis, at(m)));
    const [d, o, p, r] = ['documented', 'observed', 'in_state', 'recent'].map(v);
    const minus = (a, b) => (a == null || b == null ? null : a - b);
    return { k1: minus(d, o), k2: minus(o, p), k3: minus(p, r), k4: r };
  };
  const [before, now] = H.lists.slice(-2).map(parts);
  return Object.fromEntries(Object.keys(now).map(k => [k, now[k] == null || before[k] == null ? null : now[k] - before[k]]));
}
