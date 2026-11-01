// Names to check, on the Records to fix page: species on the India list only through an older name that the Catalogue
// of Life places under them, with a relative on an Indian checklist (pipeline/name_review.py, review/names.json). A
// person who knows the group says whether the records are another species'; the answer comes as a GitHub issue.

import { fmt, esc } from './common.js?v=9455fd8cc8';

const NEAR = 5;
const REPO = 'https://github.com/urbanmorph/overlooked';
const names = list => list.map(n => `<i>${esc(n)}</i>`).join(', ');
const OUTSIDE = 'The IUCN Red List range map does not include India';
const IUCN_CITE = 'IUCN (2026). The IUCN Red List of Threatened Species. Version 2026-1.';

/** A new GitHub issue about one name, with the facts filled in. */
export function issueHref([key, name, , old, near, outside]) {
  const body = `Species: ${name} (https://overlooked-india.pages.dev/species?key=${key})\n`
    + `Older names that reach it: ${old.join(', ')}\nRelatives on Indian checklists: ${near.join(', ')}\n`
    + (outside ? `${OUTSIDE} (${IUCN_CITE})\n` : '') + '\n'
    + 'Are the records from India this species, or one of its relatives? Your answer, and a source if you have one:\n';
  return `${REPO}/issues/new?${new URLSearchParams({ title: `Name to check: ${name}`, body })}`;
}

/** One name to check as a list item. row: [key, name, states with an open record, [older names], [relatives],
 *  whether IUCN's range map leaves out India]. */
export function reviewRowHTML(row) {
  const [key, name, states, old, near, outside] = row;
  const more = near.length - NEAR;
  return `<li><a href="/species?key=${encodeURIComponent(key)}"><i>${esc(name)}</i></a>`
    + ` <span class="muted">open records in ${fmt(states)} state${states === 1 ? '' : 's'}</span><br>`
    + (outside ? `<b>${OUTSIDE}.</b> <span class="muted" title="${esc(IUCN_CITE)}">(IUCN 2026-1)</span> ` : '')
    + `Reached by ${names(old)}. Relatives on Indian checklists: ${names(near.slice(0, NEAR))}${more > 0 ? ` and ${fmt(more)} more` : ''}.`
    + ` <a href="${esc(issueHref(row))}" target="_blank" rel="noopener">Tell us</a></li>`;
}
