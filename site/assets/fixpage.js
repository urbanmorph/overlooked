// The Records to fix page: GBIF records from India that the site cannot use in full, for a state and a group family
// chosen on the page. The address keeps the choice, so a view can be shared with a data publisher.

import { getJSON, snapshot, esc, $, showLoadError } from './common.js';
import { fixSection } from './fix.js';
import { CATS } from './cats.js';

try {
  const [snap, latest] = await Promise.all([snapshot(), getJSON('layers/master/latest.json')]);
  const [S, fix] = await Promise.all([getJSON(latest.base + 'summary.json'), fixSection(snap)]);
  const states = new Map(S.states.map(s => [String(s.code), s.name]));
  $('#fstate').insertAdjacentHTML('beforeend', S.states.map(s => `<option value="${esc(s.code)}">${esc(s.name)}</option>`).join(''));
  $('#fgroup').insertAdjacentHTML('beforeend', CATS.map(([k, name]) => `<option value="${k}">${esc(name)}</option>`).join(''));
  const asked = new URL(location.href).searchParams;
  $('#fstate').value = states.has(asked.get('state')) ? asked.get('state') : '';
  $('#fgroup').value = CATS.some(c => c[0] === asked.get('group')) ? asked.get('group') : '';
  function paint() {
    const code = $('#fstate').value || null, cat = CATS.find(c => c[0] === $('#fgroup').value);
    const u = new URL(location.href);
    for (const [k, v] of [['state', code], ['group', cat?.[0]]]) (v ? u.searchParams.set(k, v) : u.searchParams.delete(k));
    history.replaceState(null, '', u);
    fix.paint(code, cat ? cat[2] : null, code ? states.get(code) : 'India', cat ? cat[1] : 'All groups');
  }
  $('#fstate').addEventListener('change', paint);
  $('#fgroup').addEventListener('change', paint);
  paint();
} catch (err) {
  showLoadError(err);
}
