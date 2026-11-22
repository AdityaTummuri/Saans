// Chart builders: signal bars, NAQI legend and scale, and the 24-hour forecast chart.
// Everything is built with createElement / createElementNS and text nodes.

import { h, icon } from './dom.js';
import { t } from './i18n.js';

export const CATEGORIES = ['good', 'satisfactory', 'moderate', 'poor', 'very_poor', 'severe'];
const EDGES = [0, 30, 60, 90, 120, 250];
const STRIPED = new Set(['poor', 'very_poor', 'severe']);

/** The NAQI band for a PM2.5 value (CPCB). */
export function categoryOf(value) {
  const i = EDGES.findLastIndex((edge) => value > edge);
  return CATEGORIES[Math.max(i, 0)];
}

/** Six bars, filled up to the category, so severity never relies on colour alone. */
export function signal(category, cls = '') {
  const level = CATEGORIES.indexOf(category) + 1;
  const svg = h('svg', {
    class: `signal cat-${category} ${cls}`.trim(),
    viewBox: '0 0 24 16',
    'aria-hidden': 'true',
    focusable: 'false',
  });
  for (let i = 0; i < 6; i += 1) {
    const height = 4 + i * 2;
    svg.append(
      h('rect', { x: i * 4 + 0.5, y: 16 - height, width: 3, height, rx: 1, class: i < level ? 'on' : 'off' }),
    );
  }
  return svg;
}

/** A category chip: signal bars plus the label. */
export function categoryChip(category) {
  return h('span', { class: `chip cat-${category}` }, signal(category), t(`cat.${category}`));
}

/** Legend for the six NAQI bands. */
export function legend() {
  return h(
    'ul',
    { class: 'legend', 'aria-label': t('air.legend') },
    CATEGORIES.map((c) => h('li', {}, categoryChip(c))),
  );
}

/** Six equal steps from Good to Severe with a marker on today's value. */
export function scaleBar(value) {
  const index = CATEGORIES.indexOf(categoryOf(value));
  const lo = EDGES[index];
  const hi = index === 5 ? 400 : EDGES[index + 1];
  const frac = Math.min(1, Math.max(0, (value - lo) / (hi - lo)));
  const position = (index + frac) / 6;
  return h(
    'div',
    { class: 'naqi-scale', role: 'img', 'aria-label': `${t('res.scale')}: ${t(`cat.${CATEGORIES[index]}`)}` },
    h('div', { class: 'marker', vars: { '--p': position }, 'aria-hidden': 'true' }, h('span', { class: 'pin' })),
    h(
      'ol',
      { class: 'segs', 'aria-hidden': 'true' },
      CATEGORIES.map((c, i) =>
        h('li', { class: `seg cat-${c}${i === index ? ' here' : ''}` }, h('span', { class: 'bar' }), h('span', { class: 'name' }, t(`cat.${c}`))),
      ),
    ),
  );
}

// --------------------------------------------------------------------------- forecast chart

let uid = 0;

/**
 * A host element that (re)builds its chart whenever its width changes. `build(width, height)`
 * returns a node. Redraws after the first reveal are marked static so they do not replay the
 * entrance animation.
 */
export function chartHost(build) {
  const host = h('div', { class: 'chart-host', 'data-reveal': '' });
  let lastWidth = 0;
  const paint = () => {
    const width = Math.floor(host.clientWidth);
    const height = Math.floor(host.clientHeight);
    if (width < 200 || height < 120 || Math.abs(width - lastWidth) < 6) return;
    lastWidth = width;
    if (host.dataset.in !== undefined) host.dataset.static = '';
    host.replaceChildren(build(width, height));
  };
  new ResizeObserver(paint).observe(host);
  return host;
}

/** Catmull-Rom spline through the points, as a cubic Bezier path. */
function smoothPath(points) {
  let d = `M${points[0].x.toFixed(1)},${points[0].y.toFixed(1)}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
  }
  return d;
}

/**
 * The 24-hour PM2.5 chart on the NAQI bands.
 * mode "air": peak and cleanest flags plus a stagnation strip.
 * mode "moves": the activities that moved, drawn as before-to-after markers on the line.
 */
export function forecastChart({ hours, timeline = [], mode = 'air', fmtHour, fmtShort, fmtNum }) {
  return (W, totalH) => {
    const id = `fc${(uid += 1)}`;
    const narrow = W < 560;
    const stripH = mode === 'air' ? 44 : 0;
    const H = totalH - stripH;
    const m = { l: narrow ? 34 : 46, r: narrow ? 8 : 108, t: 16, b: 46 };
    const pw = W - m.l - m.r;
    const ph = H - m.t - m.b;
    const values = hours.map((x) => x.pm25);
    const ymax = Math.max(120, Math.ceil((Math.max(...values) * 1.12) / 50) * 50);
    const last = hours.length - 1;
    const X = (index) => m.l + (index / last) * pw;
    const Y = (v) => m.t + (1 - Math.min(v, ymax) / ymax) * ph;
    const points = hours.map((x, i) => ({ x: X(i), y: Y(x.pm25) }));
    const indexOfHour = new Map(hours.map((x, i) => [x.hour, i]));
    const fractional = (clock) => {
      const base = indexOfHour.get(Math.floor(clock) % 24);
      return base === undefined ? null : Math.min(last, base + (clock - Math.floor(clock)));
    };
    const valueAt = (index) => {
      const lo = Math.floor(index);
      const hi = Math.min(last, lo + 1);
      return values[lo] + (values[hi] - values[lo]) * (index - lo);
    };

    const svg = h('svg', { class: 'chart-svg', viewBox: `0 0 ${W} ${H}`, width: W, height: H, 'aria-hidden': 'true', focusable: 'false' });
    const defs = h('defs');
    for (const cat of STRIPED) {
      const gap = cat === 'poor' ? 11 : cat === 'very_poor' ? 8 : 5;
      defs.append(
        h('pattern', { id: `${id}-${cat}`, width: gap, height: gap, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
          h('rect', { class: 'stripe', width: 2, height: gap })),
      );
    }
    defs.append(
      h('linearGradient', { id: `${id}-area`, x1: 0, y1: 0, x2: 0, y2: 1 }, h('stop', { class: 'g0', offset: '0%' }), h('stop', { class: 'g1', offset: '100%' })),
    );
    svg.append(defs);

    // NAQI zones, y ticks and right-hand band names
    const zones = h('g', { class: 'zones' });
    const bounds = [...EDGES, ymax];
    CATEGORIES.forEach((cat, i) => {
      const lo = bounds[i];
      const hi = Math.min(bounds[i + 1], ymax);
      if (lo >= ymax) return;
      const y0 = Y(hi);
      const hgt = Y(lo) - y0;
      zones.append(h('rect', { class: `zone cat-${cat}`, x: m.l, y: y0, width: pw, height: hgt }));
      if (STRIPED.has(cat)) zones.append(h('rect', { class: 'zone-stripes', x: m.l, y: y0, width: pw, height: hgt, fill: `url(#${id}-${cat})` }));
      if (!narrow) zones.append(h('text', { class: 'zone-label', x: m.l + pw + 10, y: y0 + hgt / 2 + 4 }, t(`cat.${cat}`)));
      if (i > 0) {
        zones.append(h('line', { class: 'tick-line', x1: m.l, x2: m.l + pw, y1: Y(lo), y2: Y(lo) }));
        zones.append(h('text', { class: 'tick-label', x: m.l - 6, y: Y(lo) + 4, 'text-anchor': 'end' }, fmtNum(lo)));
      }
    });
    svg.append(zones);

    // night shading
    let runStart = null;
    const night = h('g', { class: 'nights' });
    hours.forEach((x, i) => {
      if (!x.is_daytime && runStart === null) runStart = i;
      if ((x.is_daytime || i === last) && runStart !== null) {
        const end = x.is_daytime ? i - 1 : i;
        const x0 = Math.max(m.l, X(runStart - 0.5));
        const x1 = Math.min(m.l + pw, X(end + 0.5));
        night.append(h('rect', { class: 'night', x: x0, y: m.t, width: x1 - x0, height: ph }));
        runStart = null;
      }
    });
    svg.append(night);

    // axis labels with sun / moon
    const step = W < 420 ? 6 : W < 700 ? 4 : 3;
    const axis = h('g', { class: 'axis' });
    hours.forEach((x, i) => {
      if (x.hour % step !== 0) return;
      const anchor = i === 0 ? 'start' : i === last ? 'end' : 'middle';
      axis.append(h('text', { class: 'axis-label', x: X(i), y: m.t + ph + 20, 'text-anchor': anchor }, fmtShort(x.hour)));
      if (x.hour % 6 === 0) {
        const glyph = h('svg', { class: 'icon dn', x: X(i) - 7, y: m.t + ph + 26, width: 14, height: 14, 'aria-hidden': 'true' });
        glyph.append(h('use', { href: `icons.svg#${x.is_daytime ? 'sun' : 'moon'}` }));
        axis.append(glyph);
      }
    });
    svg.append(axis);

    // the line, its area and the hourly dots
    const line = smoothPath(points);
    svg.append(
      h('path', { class: 'area', d: `${line} L${points.at(-1).x.toFixed(1)},${m.t + ph} L${points[0].x.toFixed(1)},${m.t + ph} Z`, fill: `url(#${id}-area)` }),
      h('path', { class: 'line', d: line, pathLength: 1 }),
    );
    const dots = h('g', { class: 'dots' });
    hours.forEach((x, i) => {
      dots.append(h('circle', { class: `dot cat-${x.category}`, cx: points[i].x, cy: points[i].y, r: narrow ? 3 : 4, vars: { '--i': i } }));
    });
    svg.append(dots);

    const overlay = h('div', { class: 'overlay' });

    if (mode === 'air') {
      const peak = hours.reduce((a, b) => (b.pm25 > a.pm25 ? b : a));
      const best = hours.filter((x) => x.hour >= 6 && x.hour <= 21).reduce((a, b) => (b.pm25 < a.pm25 ? b : a));
      const flag = (x, kind, cls, glyph, key) => {
        const i = hours.indexOf(x);
        const px = X(i);
        const py = Y(x.pm25);
        const down = kind === 'peak' ? py - 52 < m.t : py + 62 < m.t + ph;
        svg.append(h('circle', { class: `mk-ring ring-${kind}`, cx: px, cy: py, r: 9 }));
        overlay.append(
          h('div', { class: `callout flag ${cls}`, vars: { '--x': px / W, '--y': py / H, '--tx': alignX(px, W), '--ty': down ? '16px' : 'calc(-100% - 16px)' } },
            icon(glyph), h('span', {}, `${t(key, { time: fmtHour(x.hour) })} · ${fmtNum(x.pm25)} ${t('air.unit')}`)),
        );
      };
      flag(peak, 'peak', 'flag-peak', 'alert', 'air.peak');
      flag(best, 'best', 'flag-best', 'check', 'air.best');
    } else {
      const moved = timeline.filter((x) => x.shifted);
      moved.forEach((item, n) => {
        const a = fractional(item.original_start);
        const b = fractional(item.planned_start);
        if (a === null || b === null) return;
        const ax = X(a);
        const ay = Y(valueAt(a));
        const bx = X(b);
        const by = Y(valueAt(b));
        const cx = (ax + bx) / 2;
        const cy = Math.min(ay, by) - 56 - (n % 2) * 14;
        svg.append(h('path', { class: 'hop', d: `M${ax.toFixed(1)},${ay.toFixed(1)} Q${cx.toFixed(1)},${cy.toFixed(1)} ${bx.toFixed(1)},${by.toFixed(1)}`, pathLength: 1, vars: { '--n': n } }));
        // arrow head along the end tangent
        const ang = Math.atan2(by - cy, bx - cx);
        const tip = [bx - Math.cos(ang) * 11, by - Math.sin(ang) * 11];
        const size = 7;
        const wing = (d) => `${(tip[0] - Math.cos(ang + d) * size).toFixed(1)},${(tip[1] - Math.sin(ang + d) * size).toFixed(1)}`;
        svg.append(h('polygon', { class: 'hop-head', points: `${tip[0].toFixed(1)},${tip[1].toFixed(1)} ${wing(0.5)} ${wing(-0.5)}`, vars: { '--n': n } }));
        svg.append(
          h('circle', { class: 'mk-old', cx: ax, cy: ay, r: 8, vars: { '--n': n } }),
          h('circle', { class: 'mk-new', cx: bx, cy: by, r: 9, vars: { '--n': n } }),
        );
        const apexY = 0.25 * ay + 0.5 * cy + 0.25 * by;
        overlay.append(
          h('div', { class: 'callout shift-pill', vars: { '--x': cx / W, '--y': apexY / H, '--tx': alignX(cx, W, 110), '--ty': 'calc(-100% - 8px)', '--n': n } },
            h('strong', {}, item.name), h('span', {}, t('tl.moved', { from: fmtHour(item.original_start), to: fmtHour(item.planned_start) }))),
        );
      });
    }

    // hover readout
    const scrub = h('line', { class: 'scrub', y1: m.t, y2: m.t + ph, x1: 0, x2: 0 });
    svg.append(scrub);
    const readout = h('div', { class: 'readout', 'aria-hidden': 'true' });
    const hit = h('rect', { class: 'hit', x: m.l, y: m.t, width: pw, height: ph });
    svg.append(hit);
    const show = (event) => {
      const box = svg.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * W;
      const i = Math.min(last, Math.max(0, Math.round(((px - m.l) / pw) * last)));
      const x = hours[i];
      scrub.setAttribute('x1', X(i));
      scrub.setAttribute('x2', X(i));
      scrub.dataset.on = '';
      readout.textContent = `${fmtHour(x.hour)} · ${fmtNum(x.pm25)} ${t('air.unit')} · ${t(`cat.${x.category}`)}`;
      readout.style.setProperty('--x', String(X(i) / W));
      readout.style.setProperty('--tx', alignX(X(i), W, 90));
      readout.dataset.on = '';
    };
    const hide = () => {
      delete scrub.dataset.on;
      delete readout.dataset.on;
    };
    hit.addEventListener('pointermove', show);
    hit.addEventListener('pointerleave', hide);
    overlay.append(readout);

    const body = h('div', { class: 'chart', vars: { '--ml': `${m.l}px`, '--mr': `${m.r}px` } }, h('div', { class: 'plot', vars: { '--ph': `${H}px` } }, svg, overlay));

    if (mode === 'air') {
      body.append(
        h('div', { class: 'ssi', 'aria-hidden': 'true' },
          h('span', { class: 'ssi-label' }, t('air.stagnation')),
          h('div', { class: 'ssi-cells' }, hours.map((x, i) => h('i', { vars: { '--s': x.ssi / 100, '--i': i } }))),
        ),
      );
    }

    // the same data for assistive technology
    const peakHour = hours.reduce((a, b) => (b.pm25 > a.pm25 ? b : a));
    const bestHour = hours.filter((x) => x.hour >= 6 && x.hour <= 21).reduce((a, b) => (b.pm25 < a.pm25 ? b : a));
    const summary = mode === 'air'
      ? t('air.chart', { peak: `${fmtNum(peakHour.pm25)} ${t('air.unit')}`, pt: fmtHour(peakHour.hour), best: `${fmtNum(bestHour.pm25)} ${t('air.unit')}`, bt: fmtHour(bestHour.hour) })
      : t('tl.chart', { n: fmtNum(timeline.filter((x) => x.shifted).length) });
    body.append(
      h('p', { class: 'sr-only' }, summary),
      h('table', { class: 'sr-only' },
        h('caption', {}, t('air.title')),
        h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, t('air.col_hour')), h('th', { scope: 'col' }, t('air.col_pm')), h('th', { scope: 'col' }, t('air.col_band')))),
        h('tbody', {}, hours.map((x) => h('tr', {}, h('th', { scope: 'row' }, fmtHour(x.hour)), h('td', {}, fmtNum(x.pm25)), h('td', {}, t(`cat.${x.category}`))))),
      ),
    );
    return body;
  };
}

/** Horizontal alignment for an overlay label that must not leave the chart. */
function alignX(px, width, half = 100) {
  if (px < half) return '-14px';
  if (px > width - half) return 'calc(-100% + 14px)';
  return '-50%';
}
