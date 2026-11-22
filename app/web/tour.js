// The guided demo tour: scrolls through the results in story order with a caption bar.
// Space or Escape pauses, arrow keys step, Escape again (or the End button) stops it.

import { clear, h, icon } from './dom.js';
import { t } from './i18n.js';

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const FORM_FIELD = 'input, textarea, select, [contenteditable="true"]';
const INTERACTIVE = `${FORM_FIELD}, button, a[href], summary`;

/**
 * steps: [{ el: () => Element | null, key: 'tour.s1', ms: 7000, pan: false }]
 * Returns { start, stop, refresh, active }.
 */
export function createTour({ steps, onStop }) {
  let root = null;
  let index = 0;
  let playing = false;
  let timer = 0;
  let panFrame = 0;
  let remaining = 0;
  let startedAt = 0;
  let returnFocus = null;
  let cancelWait = () => {};
  const refs = {};

  const usable = () => steps.filter((s) => s.el());

  // ------------------------------------------------------------------ building the bar

  function build() {
    refs.count = h('p', { class: 'tour-count' });
    refs.title = h('p', { class: 'tour-title' });
    refs.text = h('p', { class: 'tour-text' });
    refs.fill = h('span', { class: 'fill' });
    refs.back = button('tour-back', 'chevron-left', 'tour.prev', () => go(index - 1));
    refs.toggle = button('tour-toggle', 'pause', 'tour.pause', () => (playing ? pause() : resume()));
    refs.next = button('tour-next', 'chevron-right', 'tour.next', () => go(index + 1), true);
    refs.exit = h('button', { type: 'button', class: 'tour-exit', onclick: () => stop() }, icon('x'), h('span', { class: 'sr-only' }));
    refs.keys = h('p', { class: 'tour-keys' });
    root = h('section', { class: 'tour', role: 'region', 'aria-label': t('tour.label') },
      h('div', { class: 'tour-progress', 'aria-hidden': 'true' }, refs.fill),
      h('div', { class: 'tour-main' },
        h('div', { class: 'tour-copy', 'aria-live': 'polite', 'aria-atomic': 'true' }, refs.count, refs.title, refs.text),
        h('div', { class: 'tour-controls' }, refs.back, refs.toggle, refs.next, refs.exit)),
      refs.keys);
    document.body.append(root);
  }

  function button(cls, glyph, key, onclick, iconLast = false) {
    const label = h('span', {});
    const el = h('button', { type: 'button', class: `tour-btn ${cls}`, onclick }, iconLast ? [label, icon(glyph)] : [icon(glyph), label]);
    el.labelEl = label;
    return el;
  }

  function paintText() {
    if (!root) return;
    const list = usable();
    const step = list[index];
    root.setAttribute('aria-label', t('tour.label'));
    refs.count.textContent = t('tour.step', { n: String(index + 1), total: String(list.length) });
    refs.title.textContent = t(`${step.key}.t`);
    refs.text.textContent = t(`${step.key}.d`);
    refs.back.labelEl.textContent = t('tour.prev');
    refs.back.disabled = index === 0;
    refs.next.labelEl.textContent = t(index === list.length - 1 ? 'tour.finish' : 'tour.next');
    refs.toggle.labelEl.textContent = t(playing ? 'tour.pause' : 'tour.play');
    refs.toggle.replaceChild(icon(playing ? 'pause' : 'play'), refs.toggle.querySelector('svg'));
    refs.toggle.setAttribute('aria-pressed', String(!playing));
    refs.exit.setAttribute('aria-label', t('tour.exit'));
    refs.exit.querySelector('span').textContent = t('tour.exit');
    refs.keys.textContent = t('tour.keys');
  }

  // ------------------------------------------------------------------ timing and scrolling

  function startProgress(ms) {
    refs.fill.style.setProperty('--ms', `${ms}ms`);
    refs.fill.classList.remove('run');
    void refs.fill.offsetWidth; // restart the CSS animation
    refs.fill.classList.add('run');
    refs.fill.classList.toggle('paused', !playing);
  }

  function schedule(ms) {
    clearTimeout(timer);
    remaining = ms;
    startedAt = performance.now();
    timer = setTimeout(() => go(index + 1), ms);
  }

  function cancelPan() {
    cancelAnimationFrame(panFrame);
    panFrame = 0;
    cancelWait();
  }

  const ease = (k) => (k < 0.5 ? 2 * k * k : 1 - ((-2 * k + 2) ** 2) / 2);
  const maxScroll = () => document.documentElement.scrollHeight - window.innerHeight;

  /** Glide the page to a scroll position; resolves the duration used so callers can chain. */
  function glide(to, ms, delay = 0) {
    cancelPan();
    const target = Math.min(Math.max(0, to), maxScroll());
    if (reduced()) {
      window.scrollTo(0, target);
      return;
    }
    const begin = performance.now() + delay;
    let from = null;
    const tick = (now) => {
      if (now < begin) {
        panFrame = requestAnimationFrame(tick);
        return;
      }
      from ??= window.scrollY;
      const k = Math.min(1, (now - begin) / ms);
      window.scrollTo(0, from + (target - from) * ease(k));
      if (k < 1) panFrame = requestAnimationFrame(tick);
    };
    panFrame = requestAnimationFrame(tick);
  }

  /** Scroll position that leaves the section's content 96px below the top, clear of the header. */
  const topOf = (el) => {
    if (el.id === 'top') return 0;
    const pad = Number.parseFloat(getComputedStyle(el).paddingTop) || 0;
    return el.getBoundingClientRect().top + window.scrollY + pad - 96;
  };

  /** After arriving, drift down through a section that is taller than the screen. */
  function panThrough(el, ms, travel) {
    const room = 150; // the caption bar covers the bottom of the screen
    const end = el.getBoundingClientRect().bottom + window.scrollY - window.innerHeight + room;
    const start = topOf(el);
    if (end - start < 60) return;
    const delay = travel + 900;
    const length = Math.max(1200, ms - delay - 800);
    const wait = setTimeout(() => {
      if (playing) glide(end, length);
    }, delay);
    cancelWait = () => clearTimeout(wait);
  }

  function go(next) {
    const list = usable();
    if (next >= list.length) {
      stop('finished');
      return;
    }
    index = Math.max(0, next);
    const step = list[index];
    const el = step.el();
    paintText();
    const ms = step.ms ?? 7000;
    const target = topOf(el);
    const travel = Math.min(1900, 650 + Math.abs(target - window.scrollY) * 0.28);
    startProgress(ms);
    glide(target, travel);
    if (playing) {
      schedule(ms);
      if (el.id !== 'top') panThrough(el, ms, travel);
    } else {
      clearTimeout(timer);
      remaining = ms;
    }
  }

  function pause() {
    if (!playing) return;
    playing = false;
    remaining = Math.max(500, remaining - (performance.now() - startedAt));
    clearTimeout(timer);
    cancelPan();
    refs.fill.classList.add('paused');
    paintText();
  }

  function resume() {
    if (playing) return;
    playing = true;
    refs.fill.classList.remove('paused');
    schedule(remaining || 4000);
    paintText();
  }

  // ------------------------------------------------------------------ input

  function onKey(event) {
    if (!root || event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (event.key === 'Escape') {
      event.preventDefault();
      if (playing) pause();
      else stop();
    } else if (event.key === ' ' || event.code === 'Space') {
      if (target.closest?.(INTERACTIVE)) return; // let buttons and fields handle Space
      event.preventDefault();
      playing ? pause() : resume();
    } else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      if (target.closest?.(FORM_FIELD)) return;
      event.preventDefault();
      go(index + (event.key === 'ArrowRight' ? 1 : -1));
    } else if (['PageDown', 'PageUp', 'Home', 'End', 'ArrowDown', 'ArrowUp'].includes(event.key) && !target.closest?.(FORM_FIELD)) {
      pause(); // the viewer is scrolling by hand
    }
  }

  const onManualScroll = () => pause();

  // ------------------------------------------------------------------ lifecycle

  function start() {
    if (root) return;
    if (usable().length === 0) return;
    returnFocus = document.activeElement;
    build();
    document.documentElement.dataset.tour = 'on';
    document.addEventListener('keydown', onKey);
    window.addEventListener('wheel', onManualScroll, { passive: true });
    window.addEventListener('touchmove', onManualScroll, { passive: true });
    playing = true;
    index = 0;
    go(0);
    refs.toggle.focus({ preventScroll: true });
  }

  function stop(reason = 'stopped') {
    if (!root) return;
    clearTimeout(timer);
    cancelPan();
    document.removeEventListener('keydown', onKey);
    window.removeEventListener('wheel', onManualScroll);
    window.removeEventListener('touchmove', onManualScroll);
    root.remove();
    clear(refs.count);
    root = null;
    playing = false;
    delete document.documentElement.dataset.tour;
    const back = returnFocus && document.contains(returnFocus) ? returnFocus : document.getElementById('results');
    back?.focus?.({ preventScroll: true });
    onStop?.(reason);
  }

  return { start, stop, refresh: paintText, get active() { return root !== null; } };
}
