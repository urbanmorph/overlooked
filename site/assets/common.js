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
  div.innerHTML = `<div class="wrap"><b>Development preview.</b> ${esc(summary.dev_note)} Do not cite these figures.</div>`;
  document.body.appendChild(div);
  document.body.style.paddingBottom = '64px';
}

export function sourceLine(summary) {
  const dois = (summary.dois || []).map(d => `<a class="mono" href="https://doi.org/${esc(d)}">doi:${esc(d)}</a>`).join(', ');
  return `Source: GBIF.org (${esc(monthName(summary.gbif_snapshot || summary.built))}), ${dois}. District boundaries: Local Government Directory, via bharatlas.`;
}

// If data cannot load, say so in plain words instead of leaving "Loading" on the page.
export function showLoadError(err) {
  console.error(err);
  const main = document.getElementById('main');
  const box = document.createElement('div');
  box.className = 'card pad';
  box.setAttribute('role', 'alert');
  box.style.margin = '24px 0';
  box.innerHTML = '<b>The data did not load.</b> Reload the page. If the problem continues, try again later.';
  main.prepend(box);
  for (const el of document.querySelectorAll('.loading')) el.textContent = 'Not available.';
}

// Main menu: one row that scrolls sideways on narrow screens. Show the current page, and fade the edge that has more links.
function setupNav() {
  const nav = document.querySelector('nav.main');
  if (!nav) return;
  const edges = () => {
    const max = nav.scrollWidth - nav.clientWidth;
    nav.classList.toggle('more-l', nav.scrollLeft > 1);
    nav.classList.toggle('more-r', nav.scrollLeft < max - 1);
  };
  const cur = nav.querySelector('[aria-current]');
  if (cur && nav.scrollWidth > nav.clientWidth) {
    const n = nav.getBoundingClientRect(), c = cur.getBoundingClientRect();
    nav.scrollLeft += c.left - n.left - (n.width - c.width) / 2;
  }
  edges();
  nav.addEventListener('scroll', edges, { passive: true });
  addEventListener('resize', edges);
  document.fonts?.ready.then(edges);
}
setupNav();
