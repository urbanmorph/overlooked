// District map: pre-simplified SVG paths coloured by a value per district. No map library.

import { esc, fmt } from './common.js?v=9455fd8cc8';

const RAMP = ['--q0', '--q1', '--q2', '--q3', '--q4'];

export function drawMap(box, boundaries, { onPick, label, pickLabel = 'Open' } = {}) {
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

  // Mouse: the tip follows the pointer and a click picks the district.
  // Touch and pen: the first tap shows the tip with a button; the button, or a second tap on the same district, picks it.
  let armed = null, lastType = 'mouse';
  const hl = id => { for (const p of el.querySelectorAll('path.hl')) p.classList.remove('hl'); const p = paths.get(id); if (p) { p.classList.add('hl'); p.parentNode.appendChild(p); } };
  function hide() { tip.hidden = true; tip.classList.remove('touch'); armed = null; hl(null); }
  function show(d, clientX, clientY, touch) {
    tip.innerHTML = `<b>${esc(d.name)}</b>, ${esc(d.state)}<br>${tipText(d.id, values.get(d.id))}`
      + (touch && onPick ? `<br><button class="b" type="button">${esc(pickLabel)}</button>` : '');
    tip.classList.toggle('touch', touch);
    tip.hidden = false;
    // Keep the tip inside the map box: above the point if it fits, else below it.
    const r = box.getBoundingClientRect(), x = clientX - r.left, y = clientY - r.top;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = `${Math.max(0, Math.min(x - w / 2, r.width - w))}px`;
    tip.style.top = `${y - h - 12 >= 0 ? y - h - 12 : y + 16}px`;
  }
  function pick(d) { hide(); if (onPick) onPick(d); }

  el.addEventListener('pointerdown', e => { lastType = e.pointerType || 'mouse'; });
  el.addEventListener('pointermove', e => {
    if (e.pointerType !== 'mouse') return;
    const p = e.target.closest('path');
    if (!p) { tip.hidden = true; return; }
    show(info.get(+p.dataset.id), e.clientX, e.clientY, false);
  });
  el.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') tip.hidden = true; });
  el.addEventListener('click', e => {
    const p = e.target.closest('path');
    if (!p) { hide(); return; }
    const d = info.get(+p.dataset.id);
    if (lastType === 'mouse') { pick(d); return; }
    if (armed === d.id) { pick(d); return; }
    armed = d.id; hl(d.id);
    show(d, e.clientX, e.clientY, true);
  });
  tip.addEventListener('click', e => { if (e.target.closest('button') && armed != null) pick(info.get(armed)); });
  document.addEventListener('pointerdown', e => { if (armed != null && !box.contains(e.target)) hide(); });

  return {
    info,
    // values: Map id -> number or null (null = no records). Breaks are quantiles of the non-zero values.
    paint(vals, text) {
      const nz = [...vals.values()].filter(v => v > 0).sort((a, b) => a - b);
      const q = f => nz[Math.min(nz.length - 1, Math.floor(f * nz.length))];
      const breaks = nz.length ? [q(.2), q(.4), q(.6), q(.8)] : [];
      this.fill(vals, v => (v === 0 ? '--zero' : v > 0 ? RAMP[breaks.filter(b => v > b).length] : '--none'),
        text || ((id, v) => (v == null ? 'No public records' : fmt(v))));
      return breaks;
    },
    // vals: Map id -> value; colourOf(value) -> a CSS variable name. A view can set its own colours on a parent.
    fill(vals, colourOf, text) {
      values = vals; tipText = text;
      const style = getComputedStyle(box), cache = new Map();
      const colour = v => { if (!cache.has(v)) cache.set(v, style.getPropertyValue(v).trim()); return cache.get(v); };
      for (const [id, p] of paths) p.setAttribute('fill', colour(colourOf(vals.get(id))));
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
