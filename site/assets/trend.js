// Weekly totals of the master list (layers/master/<period>/history.json): the numbers, their change since the list
// before, the geometry of a line chart, and the tile that shows one measure. changes.js and explore.js draw them.

import { fmt, esc } from './common.js';

export const MEASURES = [
  { key: 'documented', label: 'Species documented in India' },
  { key: 'observed', label: 'With an open record you can check online' },
  { key: 'threatened', label: 'Threatened (IUCN CR, EN or VU)' },
  { key: 'waiting_species', label: 'Species named in observations not yet confirmed' },
  { key: 'waiting_observations', label: 'Observations named to species, not yet confirmed' },
];

/** One measure over time, oldest first: [{period, value}]. group: a group index, or null for all of India. */
export function series(history, measure, group = null) {
  if (!history) return [];
  const i = history.measures.indexOf(measure);
  return history.lists.map(l => ({ period: l.period, value: (group == null ? l.india : l.groups[group])[i] }));
}

/** The latest value and its change since the list before (null when there is no list before). */
export function change(points) {
  const now = points.at(-1)?.value ?? null;
  const before = points.length > 1 ? points.at(-2).value : null;
  return { now, before, delta: now == null || before == null ? null : now - before };
}

/** Screen positions for a line in a w x h box: x spread evenly, y from a range padded by 10% of the values' span
 * (or of the value, when they are all equal), so a small change still shows. path: an SVG path. */
export function geometry(points, { w, h, pad = 0 }) {
  const v = points.map(p => p.value);
  const lo = Math.min(...v), hi = Math.max(...v);
  const room = (hi - lo || Math.abs(hi) || 1) * 0.1;
  const min = lo - room, max = hi + room;
  const xs = v.map((_, i) => (v.length === 1 ? w / 2 : pad + (i * (w - 2 * pad)) / (v.length - 1)));
  const ys = v.map(x => pad + (h - 2 * pad) * (1 - (x - min) / (max - min)));
  const path = xs.map((x, i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join('');
  return { xs, ys, min, max, path };
}

/** Index of the x closest to a pointer position, or -1 when there are none. */
export function nearest(xs, x) {
  let best = -1, d = Infinity;
  xs.forEach((p, i) => { if (Math.abs(p - x) < d) { d = Math.abs(p - x); best = i; } });
  return best;
}

/** A change with its sign: +12, -3, 0. */
export const signed = d => (d > 0 ? `+${fmt(d)}` : fmt(d));

/** A stat tile: the latest value, its change since the list before, and a small line. A button (pressed or not) that
 * picks the chart's measure, or a link when href is given. */
export function tile(m, pts, { pressed = false, href = null } = {}) {
  const c = change(pts), g = geometry(pts, { w: 200, h: 28, pad: 3 });
  const body = `<b>${fmt(c.now)}</b><span>${esc(m.label)}</span>
    <span class="delta">${c.delta == null ? 'First week' : `${signed(c.delta)} since the last list`}</span>
    <svg class="spark" viewBox="0 0 200 28" preserveAspectRatio="none" aria-hidden="true"><path d="${g.path}" fill="none" stroke="var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
  return href ? `<a class="card kpi" href="${esc(href)}">${body}</a>`
    : `<button type="button" class="card kpi" aria-pressed="${pressed}" data-m="${m.key}">${body}</button>`;
}
