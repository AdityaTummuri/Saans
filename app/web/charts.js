// Small chart builders: signal bars, the 24-hour air strip and the mini day track.

import { h, icon } from './dom.js';
import { t } from './i18n.js';

export const CATEGORIES = ['good', 'satisfactory', 'moderate', 'poor', 'very_poor', 'severe'];

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
      h('rect', {
        x: i * 4 + 0.5,
        y: 16 - height,
        width: 3,
        height,
        rx: 1,
        class: i < level ? 'on' : 'off',
      }),
    );
  }
  return svg;
}

/** A category chip: signal bars plus the label. */
export function categoryChip(category) {
  return h('span', { class: `chip cat-${category}` }, signal(category), t(`cat.${category}`));
}

/** Legend for the six NAQI bands plus day and night. */
export function legend() {
  return h(
    'ul',
    { class: 'legend', 'aria-label': t('air.legend') },
    CATEGORIES.map((c) => h('li', {}, categoryChip(c))),
  );
}

/**
 * The 24-hour air strip. Each hour is a list item with a bar (height = PM2.5), its value, the
 * hour and a stagnation cell. Peak and cleanest hours carry a text flag.
 */
export function airStrip(hours, fmtHour, fmtNum) {
  const max = Math.max(...hours.map((x) => x.pm25), 100);
  const peak = hours.reduce((a, b) => (b.pm25 > a.pm25 ? b : a));
  const best = hours
    .filter((x) => x.hour >= 6 && x.hour <= 21)
    .reduce((a, b) => (b.pm25 < a.pm25 ? b : a));

  const items = hours.map((x, i) => {
    const marked = x.hour === peak.hour || x.hour === best.hour;
    const label = t('air.hour_title', {
      time: fmtHour(x.hour),
      pm25: fmtNum(x.pm25),
      cat: t(`cat.${x.category}`),
      ssi: fmtNum(x.ssi),
    });
    return h(
      'li',
      {
        class: `hour cat-${x.category}${x.is_daytime ? '' : ' night'}${marked ? ' marked' : ''}`,
        vars: { '--i': i, '--v': x.pm25 / max, '--ssi': x.ssi / 100 },
        'aria-label': label,
        title: label,
      },
      h('span', { class: 'val', 'aria-hidden': 'true' }, fmtNum(x.pm25)),
      h('span', { class: 'bar', 'aria-hidden': 'true' }),
      h('span', { class: 'ssi', 'aria-hidden': 'true' }),
      h('span', { class: 'hr', 'aria-hidden': 'true' }, String(x.hour % 12 || 12)),
      h(
        'span',
        { class: 'dn', 'aria-hidden': 'true' },
        x.hour % 6 === 0 ? icon(x.is_daytime ? 'sun' : 'moon') : null,
      ),
    );
  });
  const flags = h(
    'div',
    { class: 'flags' },
    h('span', { class: 'flag flag-peak' }, icon('alert'), t('air.peak', { time: fmtHour(peak.hour) }), ' · ', `${fmtNum(peak.pm25)} ${t('air.unit')}`),
    h('span', { class: 'flag flag-best' }, icon('check'), t('air.best', { time: fmtHour(best.hour) }), ' · ', `${fmtNum(best.pm25)} ${t('air.unit')}`),
  );
  return h(
    'div',
    { class: 'strip' },
    flags,
    h('ol', { class: 'airstrip', 'aria-label': t('air.title') }, items),
  );
}

/** A thin 24-cell track coloured by category, with the old and new time marked. */
export function dayTrack(hours, oldStart, newStart, duration, shifted) {
  const span = (start, cls, label) =>
    h('span', {
      class: `mark ${cls}`,
      vars: { '--s': start / 24, '--w': Math.max(duration, 0.5) / 24 },
      role: 'img',
      'aria-label': label,
      title: label,
    });
  return h(
    'div',
    { class: 'track', role: 'group', 'aria-label': t('tl.track') },
    h(
      'div',
      { class: 'cells', 'aria-hidden': 'true' },
      hours.map((x) => h('span', { class: `cell cat-${x.category}` })),
    ),
    shifted ? span(oldStart, 'old', t('tl.old')) : null,
    span(newStart, 'new', t('tl.new')),
  );
}
