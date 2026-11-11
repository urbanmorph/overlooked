// The Records to fix page: GBIF records from India that the site cannot use in full, for a state and a group family
// chosen on the page. The address keeps the choice, so a view can be shared with a data publisher.

import { getJSON, snapshot, esc, fmt, $, showLoadError, stateOptions, setParams } from './common.js?v=0f213c3aa5';
import { fixSection } from './fix.js?v=b42cf62242';
import { reviewRowHTML, matchesRow } from './review.js?v=01c58d2bfb';
import { CATS } from './cats.js?v=7d886060d4';

try {
  const [snap, latest] = await Promise.all([snapshot(), getJSON('layers/master/latest.json')]);
  const [S, fix] = await Promise.all([getJSON(latest.base + 'summary.json'), fixSection(snap)]);
  const states = new Map(S.states.map(s => [String(s.code), s.name]));
  $('#fstate').insertAdjacentHTML('beforeend', stateOptions(S));
  $('#fgroup').insertAdjacentHTML('beforeend', CATS.map(([k, name]) => `<option value="${k}">${esc(name)}</option>`).join(''));
  const asked = new URL(location.href).searchParams;
  $('#fstate').value = states.has(asked.get('state')) ? asked.get('state') : '';
  $('#fgroup').value = CATS.some(c => c[0] === asked.get('group')) ? asked.get('group') : '';
  function paint() {
    const code = $('#fstate').value || null, cat = CATS.find(c => c[0] === $('#fgroup').value);
    setParams([['state', code], ['group', cat?.[0]]]);
    fix.paint(code, cat ? cat[2] : null, code ? states.get(code) : 'India', cat ? cat[1] : 'All groups');
  }
  $('#fstate').addEventListener('change', paint);
  $('#fgroup').addEventListener('change', paint);
  paint();
  names(latest).catch(() => {});
} catch (err) {
  showLoadError(err);
}

// Names to check (review.js), from the master list's review/names.json; a list without the file shows nothing. The box
// keeps the rows whose Latin or common names have the words typed.
async function names(latest) {
  const doc = await getJSON(latest.base + 'review/names.json');
  if (!doc.rows.length) return;
  let rows = doc.rows, shown = 0;
  const more = () => {
    $('#names-list').insertAdjacentHTML('beforeend', rows.slice(shown, shown + 25).map(reviewRowHTML).join(''));
    shown += 25;
    $('#names-more').hidden = shown >= rows.length;
  };
  $('#names-sub').textContent = `${fmt(doc.rows.length)} names. The strongest come first. Tell us what you know: each name has a link that opens a note on GitHub.`;
  $('#names-more').addEventListener('click', more);
  const filter = () => {             // also on load: words typed before the list came keep their effect
    rows = doc.rows.filter(r => matchesRow(r, $('#names-q').value));
    shown = 0;
    $('#names-list').replaceChildren();
    $('#names-none').hidden = rows.length > 0;
    more();
  };
  $('#names-q').addEventListener('input', filter);
  filter();
  $('#names').hidden = false;
}
