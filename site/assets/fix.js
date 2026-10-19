// "Records to fix" on the front page: GBIF records from India that the site cannot use in full, for data publishers.
// unlocated.json (records that cannot go in a district) and unresolved.json (records not named to species) are in the GBIF
// snapshot. The section follows the chosen state and group.

import { getJSON, fmt, esc, $ } from './common.js';

const HOLDERS = 10, ONLY = 20;
const PROBLEM = { none: 'have no coordinates', coarse: 'have coordinates uncertain by more than 25 km', issue: 'have coordinates that GBIF marks as possibly wrong' };
const sumBy = (arr, groups, keep, offset = 0) =>
  (keep ? groups.reduce((a, g, i) => a + (keep(g) ? arr[i + offset] || 0 : 0), 0) : arr[0] ?? 0);

export async function fixSection(snap) {
  const [u, un, manifest] = await Promise.all([
    getJSON(snap.file('unlocated.json')).catch(() => null),
    getJSON(snap.file('unresolved.json')).catch(() => null),
    getJSON(snap.latest.manifest).catch(() => null),
  ]);
  if (!u && !un) return { paint() {} };
  const dois = [u?.download?.doi, (manifest?.downloads || []).find(d => d.query === 'unresolved_cube' && un)?.doi].filter(Boolean);
  $('#fix-source').innerHTML = !dois.length ? '' : `Source: GBIF.org, ${dois.map(d => `<a class="mono" href="https://doi.org/${esc(d)}">doi:${esc(d)}</a>`).join(', ')}.`;
  $('#fix').hidden = false;

  // state: an LGD state code (string) or null for India; keep: a test on a group name, or null for all groups.
  function paint(state, keep, place, groupName) {
    $('#fix-sub').textContent = `${place} · ${groupName}`;
    const tiles = [];
    if (u) {
      const a = (state ? u.states[state] : u.india) || { r: [], s: [] };
      const recs = sumBy(a.r, u.groups, keep, 1), none = state ? 0 : sumBy(u.states.none?.r || [], u.groups, keep, 1);
      // Per problem: known for all groups only.
      const parts = keep ? [] : Object.entries(a.p || {}).filter(([k]) => PROBLEM[k]).map(([k, n]) => `${fmt(n)} ${PROBLEM[k]}`);
      tiles.push([recs, `records that cannot go on the map.${parts.length > 1 ? ` ${parts.join(', ')}.` : parts.length ? ` All ${PROBLEM[Object.keys(a.p)[0]]}.` : ''}${none ? ` ${fmt(none)} do not name one state.` : ''}`]);
    }
    if (un) {
      const a = (state ? un.states[state] : un.india) || { n: 0, g: [] };
      tiles.push([keep ? sumBy(a.g, un.groups, keep) : a.n, 'records named only to a genus or a higher level, not to species.']);
    }
    const only = u ? u.only_unlocated.rows.filter(r => !keep || keep(u.groups[r[2]])) : [];
    const onlyN = u ? sumBy(u.only_unlocated.g, u.groups, keep, 1) : 0;
    if (u) tiles.push([onlyN, 'species that GBIF has from India only in records that cannot go on the map (all of India).']);
    $('#fix-kpis').innerHTML = tiles.map(([n, t]) => `<div class="card kpi"><b>${fmt(n)}</b><span>${esc(t)}</span></div>`).join('');

    if (!u) { $('#fix-holders').innerHTML = $('#fix-only').innerHTML = ''; return; }
    const holders = state ? (u.state_holders[state] || []).map(([k, r]) => [k, u.titles[k], r, null]) : u.holders.slice(0, HOLDERS);
    $('#fix-holders').innerHTML = holders.length ? `<h3 class="pad fix-h">Datasets with the most records that cannot go on the map${state ? ` in ${esc(place)}` : ''}</h3>
      <div class="tablebox"><table class="sp-table"><thead><tr><th>Dataset</th><th>Records</th>${state ? '' : '<th>Species</th>'}</tr></thead><tbody>
      ${holders.map(([k, title, r, s]) => `<tr><td><a href="https://www.gbif.org/dataset/${encodeURIComponent(k)}">${esc(title || k)}</a></td>
        <td class="mono">${fmt(r)}</td>${state ? '' : `<td class="mono">${fmt(s)}</td>`}</tr>`).join('')}</tbody></table></div>
      <p class="pad muted note" style="padding-top:8px">All groups. Each dataset page on GBIF names the publisher and gives a contact.</p>` : '';
    $('#fix-only').innerHTML = only.length ? `<h3 class="pad fix-h">Species known from India only in records that cannot go on the map</h3>
      <div class="tablebox"><table class="sp-table"><thead><tr><th>Species</th><th>Group</th><th>Records</th><th>Years</th><th>States named</th></tr></thead><tbody>
      ${only.slice(0, ONLY).map(([k, name, gi, n, first, last, states]) => `<tr>
        <td><a href="https://www.gbif.org/species/${encodeURIComponent(k)}"><i>${esc(name)}</i></a></td><td>${esc(u.groups[gi])}</td>
        <td class="mono">${fmt(n)}</td><td class="mono">${first == null ? '–' : first === last ? first : `${first}–${last}`}</td><td class="mono">${fmt(states)}</td></tr>`).join('')}
      </tbody></table></div>
      <p class="pad muted note" style="padding-top:8px">Most records first. Exact coordinates on these records put the species on the map. Some of these records can give the wrong country: correct that too.${onlyN > ONLY ? ` The first ${ONLY} of ${fmt(onlyN)}.` : ''}</p>` : '';
  }
  return { paint };
}
