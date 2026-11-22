// Data visuals for the results: dose gauges, cigarette icons, before/after bars, commute bars,
// room columns and the airing strip. Numbers that should count up carry data-count.

import { categoryOf, signal } from './charts.js';
import { h, icon } from './dom.js';
import { t } from './i18n.js';

const pct = (v) => Math.min(1, Math.max(0, v));

/** A number that counts up when its card enters the viewport. */
export function counter(value, fmt, decimals = 0, cls = '') {
  return h('span', { class: `count ${cls}`.trim(), 'data-count': value, 'data-dec': decimals }, fmt(value));
}

/** Two concentric rings: outer is today's routine, inner is the plan, centre is the cut. */
export function doseGauge(member, maxDose, fmtNum) {
  const cut = Math.max(0, Math.round(member.pct_change));
  const ring = (radius, share, cls) =>
    h('circle', { class: `g-ring ${cls}`, cx: 80, cy: 80, r: radius, pathLength: 100, vars: { '--off': 100 - pct(share) * 100 }, transform: 'rotate(-90 80 80)' });
  const svg = h('svg', { class: 'gauge-svg', viewBox: '0 0 160 160', 'aria-hidden': 'true', focusable: 'false' },
    h('circle', { class: 'track', cx: 80, cy: 80, r: 66 }),
    h('circle', { class: 'track', cx: 80, cy: 80, r: 48 }),
    ring(66, member.dose_baseline_ug / maxDose, 'now'),
    ring(48, member.dose_plan_ug / maxDose, 'plan'));
  return h('div', { class: 'gauge', role: 'img', 'aria-label': t('led.ring', { pct: fmtNum(cut) }) },
    svg,
    h('div', { class: 'gauge-core', 'aria-hidden': 'true' },
      icon('lungs'),
      h('strong', {}, counter(cut, fmtNum), h('small', {}, '%')),
      h('span', {}, t('led.cut'))),
  );
}

/** Cigarette-equivalent as icons; the last one is cut to the fraction. */
export function cigarettes(n) {
  const whole = Math.min(10, Math.floor(n));
  const frac = Math.min(10, n) - whole;
  const items = Array.from({ length: whole }, (_, i) => h('span', { class: 'cig', vars: { '--i': i } }, icon('cigarette')));
  if (frac >= 0.1 && whole < 10) items.push(h('span', { class: 'cig part', vars: { '--i': whole, '--f': frac } }, icon('cigarette')));
  return h('div', { class: 'cigs', 'aria-hidden': 'true' }, items);
}

/** Old-time and new-time PM2.5 as two bars on a shared scale. */
export function beforeAfter(item, fmtHour, fmtNum) {
  const max = Math.max(item.pm25_before, item.pm25_after, 1);
  const row = (key, clock, value, cls) => {
    const cat = categoryOf(value);
    return h('div', { class: `ba-row ${cls}` },
      h('span', { class: 'ba-lab' }, t(key), h('b', {}, fmtHour(clock))),
      h('span', { class: `ba-bar cat-${cat}`, vars: { '--w': value / max }, 'aria-hidden': 'true' }),
      h('span', { class: 'ba-val' }, signal(cat), counter(value, fmtNum), h('small', {}, t('air.unit'))));
  };
  return h('div', { class: 'ba', 'data-reveal': '' },
    row('tl.old', item.original_start, item.pm25_before, 'old'),
    row('tl.new', item.planned_start, item.pm25_after, 'new'));
}

/** Commute modes side by side: time, dose and CO2, with the lowest dose called out in text. */
export function commuteBars(comp, fmtNum, fmtDec) {
  const maxDose = Math.max(...comp.options.map((o) => o.dose_ug), 1);
  const lowest = Math.min(...comp.options.map((o) => o.dose_ug));
  return h('article', { class: 'commute-card', 'data-reveal': '' },
    h('h3', {}, comp.name),
    h('ul', { class: 'cbars' },
      comp.options.map((o, i) =>
        h('li', { class: `cbar${o.current ? ' current' : ''}${o.dose_ug === lowest ? ' lowest' : ''}`, vars: { '--i': i } },
          h('div', { class: 'cmode' },
            h('span', { class: 'mode' }, icon(o.mode), t(`mode.${o.mode}`)),
            o.current ? h('span', { class: 'chip solid' }, t('commute.current')) : null,
            o.dose_ug === lowest ? h('span', { class: 'chip best' }, icon('check'), t('commute.best')) : null),
          h('span', { class: 'cmeter', 'aria-hidden': 'true' }, h('span', { class: 'meter', vars: { '--w': o.dose_ug / maxDose } })),
          h('p', { class: 'cvals' },
            h('span', {}, t('commute.min', { n: fmtNum(o.duration_min) })),
            h('strong', {}, counter(o.dose_ug, fmtNum), ' µg'),
            h('span', {}, t('commute.kg', { n: fmtDec(o.co2_kg, 1) }) + ' CO₂'))))));
}

/** Outside vs indoor columns for one room, on a scale shared by all rooms. */
export function roomChart(room, max, fmtNum) {
  const cols = [
    ['home.s_out', room.outdoor_pm25, 'out'],
    ['home.s_now', room.indoor_now, 'now'],
    ['home.s_pur', room.indoor_with_purifier, 'pur'],
    ['home.s_seal', room.indoor_purifier_sealed, 'seal'],
  ];
  const label = t('home.chart', {
    room: room.room, o: fmtNum(room.outdoor_pm25), a: fmtNum(room.indoor_now),
    b: fmtNum(room.indoor_with_purifier), c: fmtNum(room.indoor_purifier_sealed),
  });
  return h('div', { class: 'rchart', role: 'img', 'aria-label': label },
    h('div', { class: 'rplot', 'aria-hidden': 'true' },
      h('span', { class: 'target', vars: { '--t': 30 / max } }),
      h('ul', { class: 'cols' },
        cols.map(([key, value, cls], i) => {
          const cat = categoryOf(value);
          return h('li', { class: `col ${cls} cat-${cat}`, vars: { '--v': value / max, '--i': i } },
            h('span', { class: 'val' }, signal(cat), counter(value, fmtNum)),
            h('span', { class: 'bar' }));
        }))),
    h('ul', { class: 'rlabels', 'aria-hidden': 'true' }, cols.map(([key]) => h('li', {}, t(key)))),
    h('p', { class: 'target-key', 'aria-hidden': 'true' }, h('i', {}), t('home.target')));
}

/** The day's outdoor PM2.5 as small bars, with the best airing hour marked. */
export function ventStrip(hours, best, fmtShort) {
  const max = Math.max(...hours.map((x) => x.pm25), 1);
  return h('div', { class: 'vent-strip', role: 'img', 'aria-label': t('home.vent_chart') },
    h('ol', { 'aria-hidden': 'true' },
      hours.map((x, i) => h('li', { class: x.hour === best ? 'best' : '', vars: { '--v': x.pm25 / max, '--i': i } },
        x.hour === best ? icon('check') : null, h('span', {})))),
    h('p', { class: 'vent-at', 'aria-hidden': 'true' }, icon('clock'), fmtShort(best)));
}
