// Shortlists (experimental): iNaturalist observations that wait for a name, each with a few names for a person to
// check (layers/shortlist/, contract in docs/shortlist_data.md). Bands and an order of names only, never scores.
// Each card links out through /go/inat/<id>, a redirect that counts links followed per group (docs/metrics.md).

import { getJSON, fmt, esc, $, monthName, showLoadError } from './common.js';

// The bands the page shows; rows in any other band (expert) are not shown.
const BANDS = {
  quick: { label: 'Quick to confirm', rank: 'species', list: 'names', max: 3 },
  genus: { label: 'Genus first', rank: 'genus', list: 'genera', max: 5 },
};
const VERDICT = {
  'Quick to confirm': 'Up to 3 species to check, the most likely first.',
  'Genus first': 'The model is less sure of the species in this group. Check the genus first: the list shows up to 5 genera.',
};
const LICENCE = { cc0: 'CC0', 'cc-by': 'CC BY', 'cc-by-nc': 'CC BY-NC', 'cc-by-sa': 'CC BY-SA', 'cc-by-nc-sa': 'CC BY-NC-SA', 'cc-by-nd': 'CC BY-ND', 'cc-by-nc-nd': 'CC BY-NC-ND' };
const ITALIC = new Set(['genus', 'subgenus', 'section', 'complex', 'species', 'hybrid', 'subspecies', 'variety', 'form']);
const SPECIES_LEVEL = new Set(['species', 'hybrid', 'subspecies', 'variety', 'form']);
const OBS_ID = /^[1-9]\d{0,11}$/;
const GROUP_KEY = /^[a-z]{1,20}(-[a-z]{1,20}){0,4}$/;   // the keys functions/lib/metrics.js counts
const PAGE = 24;
// How the sample is drawn (experiments/corpus_v0/live.py) and the size of the queue it comes from (docs/plan.md, step 6).
const SAMPLE = { perGroup: 1000, days: 120, queue: 'about 29 lakh' };

/** The band, its label and the names to show for one row, or null when the row is not shown. */
export function shortlistOf(r) {
  const b = BANDS[r.band];
  const names = b ? (r[b.list] || []).slice(0, b.max) : [];
  return names.length ? { band: r.band, label: b.label, rank: b.rank, names } : null;
}

/** The rows the page shows, in the file's order (priority), for a state code and a band (null: all). */
export const filterRows = (rows, { state = null, band = null } = {}) =>
  rows.filter(r => shortlistOf(r) && (state == null || r.state === state) && (band == null || r.band === band));

/** Shown rows per band. */
export function bandCounts(rows) {
  const c = Object.fromEntries(Object.keys(BANDS).map(b => [b, 0]));
  for (const r of rows) if (shortlistOf(r)) c[r.band]++;
  return c;
}

/** The files that hold a group's rows: groups over 300 KB are split into pages (<key>.json, <key>.2.json, ...). */
export function groupFiles(run, g) {
  if (!g) return [];
  const base = `layers/shortlist/${encodeURIComponent(run)}/g/${encodeURIComponent(g.key)}`;
  return Array.from({ length: g.pages || 1 }, (_, i) => `${base}${i ? `.${i + 1}` : ''}.json`);
}

/** Text that says the page shows a small sample of the queue, not all of it. */
export function sampleNote(latest) {
  return `This page shows ${fmt(latest.rows)} of ${SAMPLE.queue} observations from India that wait for a name on iNaturalist. ` +
    `For each group, we took up to ${fmt(SAMPLE.perGroup)} observations uploaded in the ${SAMPLE.days} days before ${monthName(latest.run)}. ` +
    'We keep some recent observations back to test the lists, so some groups are small. If the page is useful, we will add more.';
}

/** The counted link to an observation, or null for an id that is not an iNaturalist observation id. */
export function goHref(id, group) {
  const s = String(id ?? '');
  if (!OBS_ID.test(s)) return null;
  return `/go/inat/${s}${GROUP_KEY.test(group || '') ? `?g=${group}` : ''}`;
}

/** The photo credit as HTML: the attribution as iNaturalist gives it, and the licence if the text does not name it. */
export function photoCredit(r) {
  const who = (r.attribution || '').trim(), lic = LICENCE[r.licence];
  if (!who) return `Photo: author on iNaturalist${lic ? ` · ${lic}` : ''}`;
  return esc(`Photo ${who}${lic && !who.includes(`(${lic})`) ? ` · ${lic}` : ''}`);
}

/** A name as HTML: genus and below in italics, the rank named above species. */
export function taxonHTML(t) {
  if (!t || !t.name) return 'No name yet';
  const name = ITALIC.has(t.rank) ? `<i>${esc(t.name)}</i>` : esc(t.name);
  return SPECIES_LEVEL.has(t.rank) ? name : `${name} (${esc(t.rank || 'higher rank')})`;
}

async function main() {
  try {
    const [latest, master] = await Promise.all([getJSON('layers/shortlist/latest.json'), getJSON('layers/master/latest.json')]);
    const S = await getJSON(master.base + 'summary.json');
    const groups = latest.groups || [];
    const stName = new Map(S.states.map(s => [String(s.code), s.name]));
    $('#runline').textContent = `Shortlists of ${monthName(latest.run)} · ${latest.model}`;
    $('#sample').textContent = sampleNote(latest);

    // State held in the URL so a view can be shared.
    const url = new URL(location.href);
    const pick = (k, ok) => (ok(url.searchParams.get(k)) ? url.searchParams.get(k) : null);
    const st = {
      group: pick('group', k => groups.some(g => g.key === k)) || groups[0]?.key,
      state: pick('state', k => stName.has(k || '')),
      band: pick('band', k => k in BANDS),
      shown: PAGE,
    };
    const saveURL = () => {
      const u = new URL(location.href);
      for (const [k, v] of [['group', st.group === groups[0]?.key ? null : st.group], ['state', st.state], ['band', st.band]]) {
        if (v) u.searchParams.set(k, v); else u.searchParams.delete(k);
      }
      history.replaceState(null, '', u);
    };

    $('#sl-group').innerHTML = groups.map(g => `<option value="${esc(g.key)}">${esc(g.name)} · ${esc(g.verdict)}</option>`).join('');
    $('#state').insertAdjacentHTML('beforeend', S.states.map(s => `<option value="${esc(s.code)}">${esc(s.name)}</option>`).join(''));
    $('#sl-group').value = st.group || '';
    $('#state').value = st.state || '';

    let rows = [];
    const card = r => {
      const s = shortlistOf(r), href = goHref(r.id, st.group);
      const photo = /^https:\/\//.test(r.photo || '') ? `<img src="${esc(r.photo)}" alt="Photo of the observation" loading="lazy" decoding="async">` : 'No photo';
      return `<li class="card sl">
        <div class="sl-photo">${photo}</div>
        <p class="sl-credit">${photoCredit(r)}</p>
        <div class="sl-body">
          <span><span class="badge ${s.band === 'quick' ? 'st-ok' : 'st-paper'}">${s.label}</span></span>
          <p>On iNaturalist now: ${taxonHTML(r.now)}</p>
          <p class="sl-h">${s.rank === 'species' ? 'Species' : 'Genera'} to check, the most likely first</p>
          <ol class="sl-names">${s.names.map(n => `<li><i>${esc(n)}</i></li>`).join('')}</ol>
          <p class="note">Observed ${r.observed ? esc(monthName(r.observed)) : 'on a date not given'}${r.place ? ` · ${esc(r.place)}` : ''}</p>
          ${href ? `<a class="b go" href="${esc(href)}" target="_blank" rel="noopener">Identify on iNaturalist</a>` : ''}
        </div></li>`;
    };
    const view = () => filterRows(rows, st);
    const pager = v => {
      $('#pinfo').textContent = v.length ? `Showing ${fmt(Math.min(st.shown, v.length))} of ${fmt(v.length)} in this sample` : '';
      $('#more').hidden = st.shown >= v.length;
    };
    function render() {
      const g = groups.find(x => x.key === st.group);
      const t = g?.t1;
      $('#ginfo').innerHTML = g ? `<b>${esc(g.verdict)}.</b> ${esc(VERDICT[g.verdict] || '')}${t ? ` In our test on ${fmt(t.n)} photos with a confirmed name, the first name was right for ${esc(t.top1)}%, and the list had the right ${g.verdict === 'Genus first' ? 'genus' : 'species'} for ${esc(t.cov90)}%.` : ''}` : '';
      const c = bandCounts(filterRows(rows, { state: st.state }));
      $('#bands').innerHTML = [[null, 'All', c.quick + c.genus], ...Object.entries(BANDS).map(([k, b]) => [k, b.label, c[k]])]
        .map(([k, l, n]) => `<button type="button" class="chip" aria-pressed="${st.band === k}" data-b="${k || ''}">${l} <span class="mono">${fmt(n)}</span></button>`).join('');
      const v = view();
      $('#list').innerHTML = v.slice(0, st.shown).map(card).join('')
        || `<li class="card pad empty muted">No observation here${st.state || st.band ? ' with these choices. Choose another state or band.' : ' in this run.'}</li>`;
      pager(v);
    }
    async function load() {
      $('#list').innerHTML = '<li class="loading">Loading…</li>';
      $('#pinfo').textContent = '';
      $('#more').hidden = true;
      const group = st.group;
      const pages = await Promise.all(groupFiles(latest.run, groups.find(g => g.key === group)).map(getJSON));
      if (group !== st.group) return;   // another group was chosen while this one loaded
      rows = pages.flatMap(p => p.rows);
      render();
    }

    $('#sl-group').addEventListener('change', e => { st.group = e.target.value; st.shown = PAGE; saveURL(); load().catch(showLoadError); });
    $('#state').addEventListener('change', e => { st.state = e.target.value || null; st.shown = PAGE; saveURL(); render(); });
    $('#bands').addEventListener('click', e => {
      const b = e.target.closest('button');
      if (b) { st.band = b.dataset.b || null; st.shown = PAGE; saveURL(); render(); }
    });
    // Add the next cards below the ones on screen, so nothing above them moves.
    $('#more').addEventListener('click', () => {
      const v = view(), from = st.shown;
      st.shown += PAGE;
      $('#list').insertAdjacentHTML('beforeend', v.slice(from, st.shown).map(card).join(''));
      pager(v);
    });
    // A photo that iNaturalist no longer serves: say so in its box, which keeps its size.
    $('#list').addEventListener('error', e => {
      if (e.target.tagName === 'IMG') e.target.replaceWith('The photo did not load. See it on iNaturalist.');
    }, true);
    await load();
  } catch (err) {
    showLoadError(err);
  }
}
if (typeof document !== 'undefined') main();   // not in node tests
