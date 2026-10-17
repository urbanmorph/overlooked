import { snapshot, getJSON, fmt, esc, $, monthName, showDevBanner, sourceLine, showLoadError } from './common.js';

const KINDS = [
  ['all', 'All'], ['recorded_again', 'Recorded again'], ['first_in_state', 'First in a state'],
  ['now_quiet', 'Not recorded in 30 years'], ['withdrawn', 'Withdrawn'],
];
const LABEL = { recorded_again: 'Recorded again', first_in_state: 'First record in a state', now_quiet: 'Not recorded in 30 years', withdrawn: 'Withdrawn' };
const DOT = { recorded_again: 'var(--accent)', first_in_state: 'var(--blue)', now_quiet: 'var(--quiet)', withdrawn: '#6B7771' };
const PAGE = 50;

try {
  const snap = await snapshot();
  const [summary, boundaries, ch] = await Promise.all([snap.summary(), snap.boundaries(), getJSON(snap.file('changes.json')).catch(() => ({ baseline: true }))]);
  showDevBanner(summary);
  $('#source').innerHTML = sourceLine(summary);
  $('#runline').textContent = `Module 02 · snapshot ${summary.run_id}${ch.previous ? ' compared with ' + ch.previous : ''}`;
  if (ch.baseline) {
    $('#baseline').hidden = false;
  } else {
    $('#feed').hidden = false;
    const dist = new Map(boundaries.districts.map(d => [d.id, d]));
    const state = new Map(boundaries.districts.map(d => [d.state_lgd, d.state]));
    const taxon = k => summary.taxon_ids === 'gbif' ? `https://www.gbif.org/species/${encodeURIComponent(k)}` : `https://www.catalogueoflife.org/data/taxon/${encodeURIComponent(k)}`;
    const rows = ch.rows.map(r => ({ kind: r[0], key: r[1], name: r[2], gi: r[3], d: r[4], s: r[5], before: r[6], now: r[7], reason: r[8] }));
    let kind = 'all', page = 0;
    const text = r => {
      const where = r.d != null ? `${dist.get(r.d)?.name || r.d}, ${state.get(r.s) || ''}` : r.s != null ? state.get(r.s) : 'India';
      if (r.kind === 'recorded_again') return `In ${where}. Previous public record ${r.before}; now ${r.now}.`;
      if (r.kind === 'first_in_state') return `First public record in ${where} (${r.now}).`;
      if (r.kind === 'now_quiet') return `The latest public record in India (${r.now}) is now more than 30 years old.`;
      return `No longer has a record in ${where}. The source removed, moved or renamed the records.`;
    };
    function render() {
      const view = kind === 'all' ? rows : rows.filter(r => r.kind === kind);
      const slice = view.slice(page * PAGE, page * PAGE + PAGE);
      $('#items').innerHTML = slice.map(r => `<li>
          <span class="dot" style="background:${DOT[r.kind]}"></span>
          <div><div class="kind" style="color:${DOT[r.kind]}">${LABEL[r.kind]}</div>
          <div><a href="/species?key=${encodeURIComponent(r.key)}" style="font-style:italic">${esc(r.name)}</a> · ${esc(summary.groups[r.gi] || '')}</div>
          <div class="note" style="margin:2px 0 0">${esc(text(r))}</div></div>
          <div class="note why">${esc(r.reason)}</div></li>`).join('') || '<li class="muted" style="padding:24px">No changes of this kind.</li>';
      $('#pinfo').textContent = view.length ? `Showing ${fmt(page * PAGE + 1)} to ${fmt(page * PAGE + slice.length)} of ${fmt(view.length)}` : '';
      $('#prev').disabled = page === 0; $('#next').disabled = (page + 1) * PAGE >= view.length;
      $('#chips').innerHTML = KINDS.map(([k, l]) => `<button type="button" class="chip" aria-pressed="${k === kind}" data-k="${k}">${l} <span class="mono">${fmt(k === 'all' ? rows.length : (ch.counts[k] || 0))}</span></button>`).join('');
    }
    $('#chips').addEventListener('click', e => { const b = e.target.closest('button'); if (b) { kind = b.dataset.k; page = 0; render(); } });
    $('#prev').addEventListener('click', () => { page--; render(); });
    $('#next').addEventListener('click', () => { page++; render(); });
    render();
    $('#groups').innerHTML = ch.groups.filter(g => g.before != null && g.now > g.before)
      .sort((a, b) => (b.now - b.before) - (a.now - a.before)).slice(0, 12)
      .map(g => `<tr><td>${esc(g.group)}</td><td class="n mono">${fmt(g.before)}</td><td class="n mono" style="color:var(--quiet)">${fmt(g.now)}</td></tr>`).join('')
      || '<tr><td colspan="3" class="muted">No group changed.</td></tr>';
  }
} catch (err) {
  showLoadError(err);
}
