// Shared helpers. Data lives under /data/ (R2 through the Pages Function, or scripts/serve.py locally).

export const DATA = '/data/';
const cache = new Map();

export function getJSON(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(DATA + path).then(r => {
      if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
      return r.json();
    }));
  }
  return cache.get(path);
}

// latest.json names the current snapshot; every other file is relative to it.
export async function snapshot() {
  const latest = await getJSON('latest.json');
  return {
    latest,
    file: name => latest.base + name,
    summary: () => getJSON(latest.summary),
    boundaries: () => getJSON(latest.boundaries),
    stats: () => getJSON(latest.base + 'map_stats.json'),
  };
}

const nf = new Intl.NumberFormat('en-IN');
export const fmt = n => (n == null ? '–' : nf.format(n));
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const $ = (sel, el = document) => el.querySelector(sel);

export function monthName(iso) {
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
}

export function showDevBanner(summary) {
  if (!summary.dev) return;
  const div = document.createElement('div');
  div.className = 'dev';
  div.innerHTML = `<div class="wrap"><b>Development preview.</b> ${esc(summary.dev_note)} Figures are not for citation.</div>`;
  document.body.appendChild(div);
  document.body.style.paddingBottom = '64px';
}

export function sourceLine(summary) {
  const dois = (summary.dois || []).map(d => `<a class="mono" href="https://doi.org/${esc(d)}">doi:${esc(d)}</a>`).join(', ');
  return `Source: GBIF.org (${esc(monthName(summary.gbif_snapshot || summary.built))}), ${dois}. District boundaries: Local Government Directory, via bharatlas.`;
}
