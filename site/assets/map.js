// District map: pre-simplified SVG paths coloured by a value per district. No map library.

import { esc, fmt } from './common.js';

const RAMP = ['--q0', '--q1', '--q2', '--q3', '--q4'];

export function drawMap(box, boundaries, { onPick, label } = {}) {
  const [x, y, w, h] = boundaries.viewBox;
  const byState = new Map();
  for (const d of boundaries.districts) {
    if (!byState.has(d.state_lgd)) byState.set(d.state_lgd, []);
    byState.get(d.state_lgd).push(d);
  }
  let svg = `<svg viewBox="${x} ${y} ${w} ${h}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(label || 'Map of India by district')}">`;
  for (const [s, ds] of byState) {
    svg += `<g data-state="${s}">` + ds.map(d => `<path data-id="${d.id}" d="${d.d}"/>`).join('') + '</g>';
  }
  box.innerHTML = svg + '</svg><div class="tip" hidden></div>';
  const el = box.querySelector('svg');
  const tip = box.querySelector('.tip');
  const paths = new Map([...el.querySelectorAll('path')].map(p => [+p.dataset.id, p]));
  const info = new Map(boundaries.districts.map(d => [d.id, d]));
  const full = [x, y, w, h];
  let values = new Map(), tipText = () => '';

  el.addEventListener('pointermove', e => {
    const p = e.target.closest('path');
    if (!p) { tip.hidden = true; return; }
    const d = info.get(+p.dataset.id);
    const r = box.getBoundingClientRect();
    tip.style.left = `${e.clientX - r.left}px`;
    tip.style.top = `${e.clientY - r.top}px`;
    tip.innerHTML = `<b>${esc(d.name)}</b>, ${esc(d.state)}<br>${tipText(d.id, values.get(d.id))}`;
    tip.hidden = false;
  });
  el.addEventListener('pointerleave', () => { tip.hidden = true; });
  el.addEventListener('click', e => {
    const p = e.target.closest('path');
    if (p && onPick) onPick(info.get(+p.dataset.id));
  });

  return {
    info,
    // values: Map id -> number or null (null = no records). Breaks are quantiles of the non-zero values.
    paint(vals, text) {
      values = vals; tipText = text || ((id, v) => (v == null ? 'No public records' : fmt(v)));
      const nz = [...vals.values()].filter(v => v > 0).sort((a, b) => a - b);
      const q = f => nz[Math.min(nz.length - 1, Math.floor(f * nz.length))];
      const breaks = nz.length ? [q(.2), q(.4), q(.6), q(.8)] : [];
      const style = getComputedStyle(document.documentElement);
      const colours = RAMP.map(v => style.getPropertyValue(v).trim());
      const zero = style.getPropertyValue('--zero').trim(), none = style.getPropertyValue('--none').trim();
      for (const [id, p] of paths) {
        const v = vals.get(id);
        let c = none;
        if (v === 0) c = zero;
        else if (v > 0) c = colours[breaks.filter(b => v > b).length];
        p.setAttribute('fill', c);
      }
      return breaks;
    },
    select(id) {
      for (const p of el.querySelectorAll('path.sel')) p.classList.remove('sel');
      if (id != null && paths.has(id)) { const p = paths.get(id); p.classList.add('sel'); p.parentNode.appendChild(p); }
    },
    focusState(state) {
      for (const g of el.querySelectorAll('g')) {
        for (const p of g.children) p.classList.toggle('dim', state != null && +g.dataset.state !== state);
      }
      if (state == null) { el.setAttribute('viewBox', full.join(' ')); return; }
      const g = el.querySelector(`g[data-state="${state}"]`);
      if (!g) return;
      const b = g.getBBox(), m = Math.max(b.width, b.height) * 0.08 + 10;
      el.setAttribute('viewBox', `${b.x - m} ${b.y - m} ${b.width + 2 * m} ${b.height + 2 * m}`);
    },
  };
}

export function legendHTML(breaks, what) {
  const lo = breaks.length ? fmt(Math.max(1, Math.ceil(breaks[0]))) : '1';
  const hi = breaks.length ? fmt(Math.ceil(breaks[3])) : '';
  return `<span>${esc(what)}</span>
    <span class="ramp">${RAMP.map(v => `<i style="background:var(${v})"></i>`).join('')}</span>
    <span class="mono">${lo} → ${hi}+</span>
    <span class="lbl"><i class="sw" style="background:var(--zero)"></i>none</span>
    <span class="lbl"><i class="sw" style="background:#fff"></i>no records</span>`;
}
