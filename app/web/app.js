// Saans front end: vanilla JS. All text is rendered with textContent / text nodes.

import { categoryChip, categoryOf, chartHost, forecastChart, legend, scaleBar } from './charts.js';
import { $, $$, clear, h, icon } from './dom.js';
import { initFx, setCount, smogField, watch } from './fx.js';
import { getLanguage, setLanguage, t } from './i18n.js';
import { createTour } from './tour.js';
import { beforeAfter, cigarettes, commuteBars, counter, doseGauge, roomChart, ventStrip } from './viz.js';

const KEYS = { lang: 'saans.lang', household: 'saans.household', large: 'saans.large' };
const AGE_BANDS = ['infant', 'child', 'teen', 'adult', 'older'];
const CONDITIONS = ['asthma', 'copd', 'heart_disease', 'pregnancy'];
const KIND_ICON = {
  shift_activity: 'shuffle',
  mask: 'mask',
  mode_switch: 'metro',
  departure_shift: 'clock',
  recirculation: 'car',
  purifier: 'purifier',
  cr_box: 'purifier',
  seal_gaps: 'window',
  skip_source: 'flame',
  stop_burning: 'flame',
};
const SOURCE_ICON = { waste_burning: 'flame', coal_heating: 'flame', firecrackers: 'flame' };
const LADDER_PREVIEW = 6;

const state = {
  household: null,
  plan: null, // the /api/plan response
  filter: 'all',
  expanded: false,
  busy: false,
};
const askLog = []; // [{role, text, badge}]
let heroField = null; // canvas smog in the hero
let resField = null; // canvas smog behind today's reading

// --------------------------------------------------------------------------- storage

function store(key, value) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    /* storage can be blocked; the app works without it */
  }
}

function recall(key) {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function saveHousehold() {
  store(KEYS.household, state.household ? JSON.stringify(state.household) : null);
}

// --------------------------------------------------------------------------- formatting

const locale = () => (getLanguage() === 'hi' ? 'hi-IN' : 'en-IN');
const fmtNum = (n) => new Intl.NumberFormat(locale(), { maximumFractionDigits: 0 }).format(n);
const fmtDec = (n, d = 1) =>
  new Intl.NumberFormat(locale(), { minimumFractionDigits: d, maximumFractionDigits: d }).format(n);

const dayPart = (h24) =>
  h24 >= 4 && h24 < 12 ? 'सुबह' : h24 < 16 && h24 >= 12 ? 'दोपहर' : h24 >= 16 && h24 < 20 ? 'शाम' : 'रात';

/** 12-hour time with a Hindi day-part prefix, matching the server's wording. */
function fmtHour(hour) {
  const minutes = Math.round(hour * 60) % (24 * 60);
  const h24 = Math.floor(minutes / 60);
  const m = minutes % 60;
  const h12 = h24 % 12 || 12;
  const base = `${h12}:${String(m).padStart(2, '0')} ${h24 < 12 ? 'am' : 'pm'}`;
  return getLanguage() === 'hi' ? `${dayPart(h24)} ${base}` : base;
}

/** Short hour for chart axes: "6 am" or "सुबह 6". */
function fmtShort(hour) {
  const h24 = Math.round(hour) % 24;
  const h12 = h24 % 12 || 12;
  return getLanguage() === 'hi' ? `${dayPart(h24)} ${fmtNum(h12)}` : `${fmtNum(h12)} ${h24 < 12 ? 'am' : 'pm'}`;
}

const hoursToTime = (hours) => {
  const total = Math.min(Math.round(hours * 60), 24 * 60 - 1);
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
};
const timeToHours = (value) => {
  if (!/^\d{2}:\d{2}$/.test(value)) return null;
  if (value === '23:59') return 24;
  const [hh, mm] = value.split(':').map(Number);
  return Math.min(hh + mm / 60, 23.99);
};

function listNames(names) {
  if (names.length <= 1) return names.join('');
  const joiner = getLanguage() === 'hi' ? ' और ' : ' and ';
  return `${names.slice(0, -1).join(', ')}${joiner}${names.at(-1)}`;
}

/** Collapse a list of clock hours into readable ranges, merging across midnight. */
function hourRanges(hours) {
  const set = new Set(hours);
  if (set.size === 0) return t('prof.none');
  if (set.size >= 22) return t('led.all_day');
  const ranges = [];
  for (let hr = 0; hr < 24; hr += 1) {
    if (!set.has(hr)) continue;
    const last = ranges.at(-1);
    if (last && last.end === hr) last.end = hr + 1;
    else ranges.push({ start: hr, end: hr + 1 });
  }
  if (ranges.length > 1 && ranges[0].start === 0 && ranges.at(-1).end === 24) {
    const first = ranges.shift();
    ranges.at(-1).end = first.end;
  }
  return ranges.map((r) => `${fmtHour(r.start)}–${fmtHour(r.end % 24)}`).join(', ');
}

const announce = (message) => {
  const live = $('#live');
  live.textContent = '';
  requestAnimationFrame(() => {
    live.textContent = message;
  });
};

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const scrollToEl = (el) => el.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });

// --------------------------------------------------------------------------- API

class ApiError extends Error {
  constructor(code, status) {
    super(code);
    this.code = code;
    this.status = status;
  }
}

async function api(path, { method = 'POST', body } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError('network', 0);
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* an error page without JSON */
  }
  if (!response.ok) throw new ApiError(data?.error ?? 'generic', response.status);
  return data;
}

const errorText = (err) => {
  const key = `err.${err instanceof ApiError ? err.code : 'generic'}`;
  const text = t(key);
  return text === key ? t('err.generic') : text;
};

function showError(el, message) {
  el.textContent = message;
  el.hidden = false;
}
const hideError = (el) => {
  el.hidden = true;
  el.textContent = '';
};

function setBusy(button, busy, busyKey) {
  const label = button.querySelector('span');
  button.disabled = busy;
  button.setAttribute('aria-busy', String(busy));
  if (!label) return;
  if (busy) {
    label.dataset.prev = label.textContent;
    label.textContent = t(busyKey);
  } else if (label.dataset.prev) {
    label.textContent = label.dataset.i18n ? t(label.dataset.i18n) : label.dataset.prev;
    delete label.dataset.prev;
  }
}

// --------------------------------------------------------------------------- i18n

function applyI18n() {
  document.documentElement.lang = getLanguage();
  document.documentElement.dataset.lang = getLanguage();
  for (const el of $$('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const el of $$('[data-i18n-attr]')) {
    for (const pair of el.dataset.i18nAttr.split(';')) {
      const [attr, key] = pair.split(':');
      el.setAttribute(attr, t(key));
    }
  }
  const largeOn = document.documentElement.dataset.large === 'on';
  $('#large-btn').setAttribute('aria-pressed', String(largeOn));
  paintOrb();
}

async function changeLanguage() {
  const next = getLanguage() === 'hi' ? 'en' : 'hi';
  setLanguage(next);
  store(KEYS.lang, next);
  applyI18n();
  if (state.household) {
    state.household.language = next;
    saveHousehold();
    renderProfile();
  }
  if (state.plan) {
    renderResults();
    tour.refresh();
    await requestPlan({ quiet: true });
    tour.refresh();
  }
}

// --------------------------------------------------------------------------- profile editor

const field = (labelText, control, cls = '') =>
  h('label', { class: `field ${cls}`.trim() }, h('span', {}, labelText), control);

function select(options, value, onChange) {
  const el = h(
    'select',
    {},
    options.map(([v, label]) => h('option', { value: v, selected: v === value }, label)),
  );
  el.value = value;
  el.addEventListener('change', () => onChange(el.value));
  return el;
}

function textInput(value, onInput, attrs = {}) {
  const el = h('input', { type: 'text', maxlength: 60, ...attrs });
  el.value = value;
  el.addEventListener('input', () => onInput(el.value));
  return el;
}

function numberInput(value, onInput, attrs = {}) {
  const el = h('input', { type: 'number', inputmode: 'decimal', ...attrs });
  el.value = String(value);
  el.addEventListener('input', () => {
    const n = Number.parseFloat(el.value);
    if (Number.isFinite(n)) onInput(n);
  });
  return el;
}

function timeInput(hours, onInput, attrs = {}) {
  const el = h('input', { type: 'time', ...attrs });
  el.value = hoursToTime(hours);
  el.addEventListener('input', () => {
    const v = timeToHours(el.value);
    if (v !== null) onInput(v);
  });
  return el;
}

function memberNames(ids) {
  return ids.map((id) => state.household.members.find((m) => m.id === id)?.name ?? id);
}

function removeMember(id) {
  const hh = state.household;
  hh.members = hh.members.filter((m) => m.id !== id);
  hh.activities = hh.activities
    .map((a) => ({ ...a, member_ids: a.member_ids.filter((m) => m !== id) }))
    .filter((a) => a.member_ids.length);
  hh.trips = hh.trips
    .map((tr) => ({ ...tr, member_ids: tr.member_ids.filter((m) => m !== id) }))
    .filter((tr) => tr.member_ids.length);
  for (const room of hh.home.rooms) room.occupant_ids = room.occupant_ids.filter((m) => m !== id);
  saveHousehold();
  renderProfile();
}

function memberCard(member) {
  const conditions = h(
    'fieldset',
    { class: 'checks' },
    h('legend', {}, t('prof.conditions')),
    CONDITIONS.map((c) => {
      const box = h('input', { type: 'checkbox', checked: member.conditions.includes(c) });
      box.addEventListener('change', () => {
        member.conditions = box.checked
          ? [...new Set([...member.conditions, c])]
          : member.conditions.filter((x) => x !== c);
        saveHousehold();
      });
      return h('label', { class: 'check' }, box, h('span', {}, t(`cond.${c}`)));
    }),
  );
  const remove = h(
    'button',
    {
      type: 'button',
      class: 'icon-btn danger',
      'aria-label': t('prof.remove', { name: member.name }),
      disabled: state.household.members.length <= 1,
      onclick: () => removeMember(member.id),
    },
    icon('trash'),
  );
  return h(
    'article',
    { class: 'edit-card' },
    h('div', { class: 'edit-head' }, h('span', { class: 'avatar' }, member.name.slice(0, 1).toUpperCase()), remove),
    field(t('prof.member_name'), textInput(member.name, (v) => { member.name = v || ' '; saveHousehold(); })),
    field(
      t('prof.age'),
      select(AGE_BANDS.map((a) => [a, t(`age.${a}`)]), member.age_band, (v) => {
        member.age_band = v;
        saveHousehold();
      }),
    ),
    conditions,
  );
}

function activityCard(act) {
  const flexible = h('input', { type: 'checkbox', checked: act.window_start !== null && act.window_start !== undefined });
  const winStart = timeInput(act.window_start ?? act.start_hour, (v) => { act.window_start = v; saveHousehold(); });
  const winEnd = timeInput(act.window_end ?? Math.min(act.start_hour + act.duration_h, 24), (v) => { act.window_end = v; saveHousehold(); });
  const windowRow = h('div', { class: 'row-inline', hidden: !flexible.checked }, h('span', {}, t('prof.between')), winStart, h('span', {}, t('prof.and')), winEnd);
  flexible.addEventListener('change', () => {
    if (flexible.checked) {
      act.window_start = timeToHours(winStart.value) ?? act.start_hour;
      act.window_end = timeToHours(winEnd.value) ?? Math.min(act.start_hour + act.duration_h, 24);
    } else {
      act.window_start = null;
      act.window_end = null;
    }
    windowRow.hidden = !flexible.checked;
    saveHousehold();
  });
  const mask = h('input', { type: 'checkbox', checked: act.mask });
  mask.addEventListener('change', () => { act.mask = mask.checked; saveHousehold(); });
  return h(
    'article',
    { class: 'edit-card' },
    h('h4', {}, act.name),
    h('p', { class: 'muted small' }, t('prof.who', { names: listNames(memberNames(act.member_ids)) })),
    h('div', { class: 'row2' },
      field(t('prof.start'), timeInput(act.start_hour, (v) => { act.start_hour = Math.min(v, 23.99); saveHousehold(); })),
      field(t('prof.duration'), numberInput(act.duration_h, (v) => { act.duration_h = v; saveHousehold(); }, { min: 0.25, max: 24, step: 0.25 })),
    ),
    h('label', { class: 'check' }, flexible, h('span', {}, t('prof.flexible'))),
    windowRow,
    h('label', { class: 'check' }, mask, h('span', {}, t('prof.mask'))),
  );
}

function tripCard(trip) {
  const modes = trip.options.map((o) => [o.mode, t(`mode.${o.mode}`)]);
  return h(
    'article',
    { class: 'edit-card' },
    h('h4', {}, trip.name),
    h('p', { class: 'muted small' }, t('prof.who', { names: listNames(memberNames(trip.member_ids)) })),
    field(t('prof.mode'), select(modes, trip.mode, (v) => { trip.mode = v; saveHousehold(); })),
    h('div', { class: 'row2' },
      field(t('prof.depart'), timeInput(trip.depart_hour, (v) => { trip.depart_hour = Math.min(v, 23.99); saveHousehold(); })),
      field(t('prof.flex'), numberInput(trip.depart_flex_h, (v) => { trip.depart_flex_h = Math.min(Math.max(v, 0), 6); saveHousehold(); }, { min: 0, max: 6, step: 0.5 })),
    ),
  );
}

function roomCard(room) {
  return h(
    'article',
    { class: 'edit-card' },
    h('h4', {}, room.name),
    h('p', { class: 'muted small' }, t('prof.volume', { v: fmtNum(room.volume_m3) })),
    field(t('prof.windows'), select([['leaky', t('win.leaky')], ['sealed', t('win.sealed')]], room.windows, (v) => { room.windows = v; saveHousehold(); })),
    field(t('prof.cadr'), numberInput(room.purifier_cadr_m3_per_h, (v) => { room.purifier_cadr_m3_per_h = Math.max(v, 0); saveHousehold(); }, { min: 0, max: 2000, step: 10 })),
  );
}

function group(title, cards, id) {
  return h('section', { class: 'edit-group', 'aria-labelledby': id }, h('h3', { id }, title), h('div', { class: 'edit-grid' }, cards));
}

function renderProfile() {
  const hh = state.household;
  const form = $('#profile');
  if (!hh) {
    form.hidden = true;
    return;
  }
  form.hidden = false;
  const body = clear($('#profile-body'));

  const locationInput = textInput(hh.location.label ?? '', (v) => { hh.location.label = v.slice(0, 120); saveHousehold(); }, { maxlength: 120 });
  const coords = h('p', { class: 'muted small', id: 'coords' }, t('prof.coords', { lat: fmtDec(hh.location.lat, 2), lon: fmtDec(hh.location.lon, 2) }));
  const locateNote = h('p', { class: 'alert', role: 'alert', hidden: true });
  const locate = h('button', {
    type: 'button',
    class: 'btn ghost',
    onclick: () => {
      if (!navigator.geolocation) {
        showError(locateNote, t('prof.locate_denied'));
        return;
      }
      hideError(locateNote);
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          hh.location.lat = Math.round(pos.coords.latitude * 100) / 100;
          hh.location.lon = Math.round(pos.coords.longitude * 100) / 100;
          saveHousehold();
          coords.textContent = t('prof.coords', { lat: fmtDec(hh.location.lat, 2), lon: fmtDec(hh.location.lon, 2) });
        },
        () => showError(locateNote, t('prof.locate_denied')),
        { maximumAge: 600000, timeout: 8000 },
      );
    },
  }, icon('locate'), h('span', {}, t('prof.locate')));

  body.append(
    h('section', { class: 'edit-group', 'aria-labelledby': 'loc-h' },
      h('h3', { id: 'loc-h' }, t('prof.location')),
      h('div', { class: 'edit-card wide' },
        h('div', { class: 'row2' },
          field(t('prof.location_label'), locationInput),
          field(t('prof.budget'), select([['low', t('budget.low')], ['medium', t('budget.medium')], ['high', t('budget.high')]], hh.budget, (v) => { hh.budget = v; saveHousehold(); })),
        ),
        coords, locate, locateNote,
      ),
    ),
    group(t('prof.members'), hh.members.map(memberCard), 'mem-h'),
  );
  if (hh.activities.length) body.append(group(t('prof.activities'), hh.activities.map(activityCard), 'act-h'));
  if (hh.trips.length) body.append(group(t('prof.trips'), hh.trips.map(tripCard), 'trip-h'));
  body.append(group(t('prof.rooms'), hh.home.rooms.map(roomCard), 'room-h'));
}

// --------------------------------------------------------------------------- results

const memberById = () => new Map(state.household.members.map((m) => [m.id, m]));

/** A section heading with its story-step eyebrow, so the page reads as one story. */
function sectionHead(id, titleKey, ledeKey, storyKey, step) {
  return h('div', { class: 'head' },
    storyKey
      ? h('p', { class: 'eyebrow' }, h('span', { class: 'step-n', 'aria-hidden': 'true' }, String(step).padStart(2, '0')), t(storyKey))
      : null,
    h('h2', { id, class: 'section-title' }, t(titleKey)),
    ledeKey ? h('p', { class: 'section-lede' }, t(ledeKey)) : null);
}

const dayMean = (hours) => hours.reduce((sum, x) => sum + x.pm25, 0) / hours.length;

/** The big live reading in the hero card: the example until a plan loads, then today's average. */
function paintOrb() {
  const card = $('.hero-card');
  const live = state.plan ? dayMean(state.plan.plan.hours) : 240;
  const category = categoryOf(live);
  card.dataset.cat = category;
  const num = $('#orb-num');
  if (state.plan) setCount(num, Math.round(live));
  else {
    num.dataset.count = '240';
    num.textContent = fmtNum(240);
  }
  $('#orb-label').textContent = state.plan
    ? t('hero.orb_live', { place: state.plan.location || '—' })
    : t('hero.orb_example');
  clear($('#orb-band')).append(categoryChip(category));
  heroField?.setPm(live);
}

function renderProblem() {
  const r = state.plan;
  const { hours } = r.plan;
  const avg = dayMean(hours);
  const category = categoryOf(avg);
  const peak = hours.reduce((a, b) => (b.pm25 > a.pm25 ? b : a));
  const best = hours.filter((x) => x.hour >= 6 && x.hour <= 21).reduce((a, b) => (b.pm25 < a.pm25 ? b : a));
  clear($('#res-badges')).append(
    h('span', { class: 'badge' }, icon('pin'), t('res.forecast_for', { place: r.location || '—' })),
    h('span', { class: 'badge' }, icon('info'), t(r.demo ? 'res.demo_badge' : 'res.live_badge')),
    h('span', { class: 'badge' }, icon('sparkle'), t(r.narrated_by_model ? 'res.model_badge' : 'res.template_badge')),
  );
  $('#res-summary').textContent = r.summary;
  const number = clear($('#res-number'));
  number.dataset.cat = category;
  number.setAttribute('data-reveal', '');
  number.append(
    h('p', { class: 'bn-label' }, t('res.avg')),
    h('p', { class: 'bn-value' }, counter(Math.round(avg), fmtNum), h('small', {}, t('air.unit'))),
    h('div', { class: 'bn-band' }, categoryChip(category)),
    h('ul', { class: 'bn-facts' },
      h('li', { class: 'fact-peak' }, icon('alert'), `${t('air.peak', { time: fmtHour(peak.hour) })} · ${fmtNum(peak.pm25)}`),
      h('li', { class: 'fact-best' }, icon('check'), `${t('air.best', { time: fmtHour(best.hour) })} · ${fmtNum(best.pm25)}`)),
  );
  const scale = clear($('#res-scale'));
  scale.setAttribute('data-reveal', '');
  scale.append(scaleBar(avg));
  resField ??= smogField($('#res-canvas'), { pm: avg, anchor: [0.82, 0.42] });
  resField.setPm(avg);
  paintOrb();
}

function renderAir() {
  const { plan, recommendations } = state.plan;
  const body = clear($('#air-body'));
  const advice = Object.entries(recommendations ?? {});
  body.append(
    sectionHead('air-title', 'air.title', 'air.lede', 'story.problem', 1),
    legend(),
    h('div', { class: 'chart-card' },
      h('p', { class: 'chart-unit', 'aria-hidden': 'true' }, t('air.unit')),
      chartHost(forecastChart({ hours: plan.hours, mode: 'air', fmtHour, fmtShort, fmtNum }))),
    h('p', { class: 'muted small stag-note' }, t('air.stag_legend')),
    advice.length
      ? h('details', { class: 'advice' },
          h('summary', {}, icon('info'), t('air.advice'), icon('chevron-down', 'chev')),
          h('dl', {}, advice.map(([k, v]) => [h('dt', {}, t(`adv.${k}`)), h('dd', {}, v)])))
      : null,
  );
}

function renderFamily() {
  const hh = state.household;
  const { plan } = state.plan;
  const summaries = new Map(plan.members.map((m) => [m.member_id, m]));
  const body = clear($('#family-body'));
  const cards = hh.members.map((m, i) => {
    const summary = summaries.get(m.id);
    const routine = [
      ...hh.activities.filter((a) => a.member_ids.includes(m.id)).map((a) => ({ name: a.name, glyph: 'clock', hour: a.start_hour })),
      ...hh.trips.filter((tr) => tr.member_ids.includes(m.id)).map((tr) => ({ name: tr.name, glyph: tr.mode, hour: tr.depart_hour })),
    ].sort((a, b) => a.hour - b.hour);
    return h('article', { class: `person${summary && summary.weight > 1 ? ' care' : ''}`, vars: { '--i': i } },
      h('header', {},
        h('span', { class: 'avatar xl', 'aria-hidden': 'true' }, m.name.slice(0, 1).toUpperCase()),
        h('div', {}, h('h3', {}, m.name), h('p', { class: 'muted small' }, t(`age.${m.age_band}`)))),
      h('div', { class: 'conds' },
        summary && summary.weight > 1 ? h('span', { class: 'chip care' }, icon('shield'), t('led.care')) : null,
        m.conditions.map((c) => h('span', { class: 'chip' }, t(`cond.${c}`)))),
      h('p', { class: 'day-title' }, t('fam.day')),
      routine.length
        ? h('ul', { class: 'day' }, routine.map((x) => h('li', {}, icon(x.glyph), h('span', {}, x.name), h('time', {}, fmtHour(x.hour)))))
        : h('p', { class: 'muted small' }, t('fam.day_none')));
  });
  body.append(sectionHead('fam-title', 'fam.title', 'fam.lede', 'story.family', 2), h('div', { class: 'people', 'data-reveal': '' }, cards));
}

function renderTimeline() {
  const { plan } = state.plan;
  const byId = memberById();
  const body = clear($('#timeline-body'));
  body.append(
    sectionHead('tl-title', 'tl.title', 'tl.lede', 'story.change', 3),
    h('div', { class: 'chart-card moves' },
      h('p', { class: 'chart-unit', 'aria-hidden': 'true' }, t('air.unit')),
      chartHost(forecastChart({ hours: plan.hours, timeline: plan.timeline, mode: 'moves', fmtHour, fmtShort, fmtNum })),
      h('ul', { class: 'move-key' }, plan.timeline.filter((x) => x.shifted).map((x) =>
        h('li', {}, icon('shuffle'), h('strong', {}, x.name), h('span', {}, t('tl.moved', { from: fmtHour(x.original_start), to: fmtHour(x.planned_start) })))))),
  );
  const items = plan.timeline.map((it) => {
    const names = listNames(it.member_ids.map((id) => byId.get(id)?.name ?? id));
    const cut = Math.round(it.dose_cut_pct);
    return h('li', { class: `tl-item${it.shifted ? ' shifted' : ''}`, 'data-reveal': '' },
      h('div', { class: 'when' },
        h('span', { class: 'big' }, icon('clock'), fmtHour(it.planned_start)),
        h('span', { class: 'was' }, it.shifted ? t('tl.was', { time: fmtHour(it.original_start) }) : t('tl.kept', { time: fmtHour(it.original_start) }))),
      h('div', { class: 'what' },
        h('h3', {}, it.name),
        h('p', { class: 'muted small' }, t('prof.who', { names })),
        h('p', { class: 'reason' }, icon(it.shifted ? 'check' : 'info'), t(`tl.reason.${it.reason}`)),
        beforeAfter(it, fmtHour, fmtNum),
        cut > 0
          ? h('p', { class: 'cut-chip' }, h('span', { class: 'sr-only' }, t('tl.dose', { pct: fmtNum(cut) })), h('span', { 'aria-hidden': 'true' }, counter(cut, fmtNum), '% ', t('led.cut')))
          : h('p', { class: 'cut-chip none' }, t('tl.dose_same'))));
  });
  if (items.length) body.append(h('ol', { class: 'timeline' }, items));
}

function renderCommute() {
  const { plan } = state.plan;
  $('#commute').hidden = plan.commute.length === 0;
  const body = clear($('#commute-body'));
  if (!plan.commute.length) return;
  body.append(
    sectionHead('commute-title', 'commute.title', 'commute.lede', 'story.commute', 3),
    h('div', { class: 'commutes' }, plan.commute.map((comp) => commuteBars(comp, fmtNum, fmtDec))));
}

function renderLedger() {
  const { plan } = state.plan;
  const body = clear($('#ledger-body'));
  const maxDose = Math.max(...plan.members.map((m) => m.dose_baseline_ug), 1);
  body.append(sectionHead('led-title', 'led.title', 'led.lede', 'story.less', 4));
  const cards = plan.members.map((m, i) =>
    h('article', { class: 'led-member', 'data-reveal': '', vars: { '--i': i } },
      h('header', {},
        h('span', { class: 'avatar', 'aria-hidden': 'true' }, m.name.slice(0, 1).toUpperCase()),
        h('h3', {}, m.name),
        m.weight > 1 ? h('span', { class: 'chip care' }, icon('shield'), t('led.care')) : null),
      doseGauge(m, maxDose, fmtNum),
      h('p', { class: 'sr-only' }, t('led.dose', { a: fmtNum(m.dose_baseline_ug), b: fmtNum(m.dose_plan_ug), pct: fmtNum(m.pct_change) })),
      h('dl', { class: 'dose-legend', 'aria-hidden': 'true' },
        h('div', { class: 'now' }, h('dt', {}, h('i', {}), t('led.now')), h('dd', {}, counter(Math.round(m.dose_baseline_ug), fmtNum), ' µg')),
        h('div', { class: 'plan' }, h('dt', {}, h('i', {}), t('led.plan')), h('dd', {}, counter(Math.round(m.dose_plan_ug), fmtNum), ' µg'))),
      m.cigarettes_avoided >= 0.05
        ? h('div', { class: 'cig-row' }, cigarettes(m.cigarettes_avoided), h('p', { class: 'muted' }, t('led.cig', { n: fmtDec(m.cigarettes_avoided, 1) })))
        : null,
      h('p', { class: 'avoid' }, icon('alert'), m.avoid_exertion_hours.length ? t('led.avoid', { hours: hourRanges(m.avoid_exertion_hours) }) : t('led.avoid_none'))));
  body.append(h('div', { class: 'led-grid' }, cards), h('p', { class: 'muted small' }, t('led.cig_note')));
}

function actionMetrics(entry, names) {
  const items = [];
  if (names.length) items.push(h('li', {}, icon('users'), t('m.for', { names: listNames(names) })));
  if (entry.avoided_ug > 0.5) items.push(h('li', {}, icon('lungs'), t('m.avoided', { n: fmtNum(entry.avoided_ug) })));
  if (entry.pct_change > 0.5) items.push(h('li', {}, icon('check'), t('m.pct', { pct: fmtNum(entry.pct_change) })));
  if (entry.cigarettes_avoided >= 0.05) items.push(h('li', {}, icon('smoke'), t('m.cig', { n: fmtDec(entry.cigarettes_avoided, 1) })));
  if (entry.co2_avoided_kg > 0.05) items.push(h('li', {}, icon('leaf'), t('m.co2', { n: fmtDec(entry.co2_avoided_kg, 1) })));
  if (entry.pm25_avoided_g > 0.5) items.push(h('li', {}, icon('wind'), t('m.pm', { n: fmtNum(entry.pm25_avoided_g) })));
  return h('ul', { class: 'metrics' }, items);
}

function tierBadge(tier) {
  return h('span', { class: `tier t${tier}`, title: t('tier.label', { tier: t(`tier.${tier}`) }) },
    h('span', { class: 'pips', 'aria-hidden': 'true' }, [1, 2, 3, 4].map((i) => h('i', { class: i <= tier ? 'on' : '' }))),
    t('tier.label', { tier: t(`tier.${tier}`) }));
}

function renderLadder(refocus = null) {
  const { plan, action_text: texts } = state.plan;
  const byId = memberById();
  const body = clear($('#ladder-body'));
  body.append(sectionHead('ladder-title', 'ladder.title', 'ladder.lede', 'story.ladder', 4));

  const filters = [['all', 'ladder.f_all'], ['free', 'ladder.f_free'], ['diy', 'ladder.f_diy']];
  body.append(
    h('div', { class: 'filters', role: 'group', 'aria-label': t('ladder.filter') },
      filters.map(([key, label]) =>
        h('button', {
          type: 'button',
          class: 'pill',
          'data-filter': key,
          'aria-pressed': String(state.filter === key),
          onclick: () => { state.filter = key; state.expanded = false; renderLadder(key); },
        }, t(label)))),
  );

  const matches = (a) => state.filter === 'all' || (state.filter === 'free' ? a.effort_tier === 1 : a.effort_tier <= 3);
  const list = plan.actions.filter(matches);
  const shown = state.expanded ? list : list.slice(0, LADDER_PREVIEW);
  const rankOf = new Map(plan.actions.map((a, i) => [a.id, i + 1]));
  const top = Math.max(...plan.actions.map((a) => a.score), 1e-9);

  body.append(
    h('ol', { class: 'ladder' },
      shown.map((a, i) => {
        const names = a.members.map((m) => byId.get(m.member_id)?.name ?? m.member_id);
        const glyph = a.kind === 'mode_switch' && a.details.mode_new ? String(a.details.mode_new) : KIND_ICON[a.kind];
        return h('li', { class: `ladder-item tier-${a.effort_tier}${a.tradeoff ? ' tradeoff' : ''}`, 'data-reveal': '', vars: { '--i': i } },
          h('div', { class: 'rank' }, h('span', { class: 'n' }, String(rankOf.get(a.id))), h('span', { class: 'sr-only' }, t('ladder.rank', { n: rankOf.get(a.id) }))),
          h('div', { class: 'body' },
            h('header', {}, h('span', { class: 'kind' }, icon(glyph), t(`kind.${a.kind}`)), tierBadge(a.effort_tier)),
            h('p', { class: 'text' }, texts[a.id] ?? ''),
            h('div', { class: 'impact', 'aria-hidden': 'true' },
              h('span', { class: 'imp-lab' }, t('ladder.impact')),
              h('span', { class: 'track' }, h('span', { class: 'fill', vars: { '--w': Math.max(a.score / top, 0.03) } })),
              h('span', { class: 'amt' }, counter(Math.round(a.score), fmtNum))),
            actionMetrics(a, names),
            a.tradeoff ? h('p', { class: 'trade' }, icon('info'), t('m.tradeoff')) : null));
      })),
  );
  if (list.length > LADDER_PREVIEW) {
    body.append(
      h('button', { type: 'button', class: 'btn ghost more', onclick: () => { state.expanded = !state.expanded; renderLadder('more'); } },
        t(state.expanded ? 'ladder.less' : 'ladder.more', { n: fmtNum(list.length) })));
  }
  if (refocus) {
    watch(body);
    (refocus === 'more' ? $('.more', body) : $(`[data-filter="${refocus}"]`, body))?.focus({ preventScroll: true });
  }
}

function renderHome() {
  const { plan } = state.plan;
  const body = clear($('#home-body'));
  const max = Math.max(...plan.rooms.flatMap((r) => [r.outdoor_pm25, r.indoor_now, r.indoor_no_purifier, r.indoor_with_purifier]), 60) * 1.08;
  body.append(sectionHead('home-title', 'home.title', 'home.lede', 'story.home', 5));

  body.append(
    h('div', { class: 'rooms' },
      plan.rooms.map((r, i) =>
        h('article', { class: 'room-card', 'data-reveal': '', vars: { '--i': i } },
          h('header', {}, h('h3', {}, icon('home'), r.room), categoryChip(r.category_now)),
          roomChart(r, max, fmtNum),
          h('p', { class: 'need' }, icon('purifier'), r.purifier_cadr > 0 ? t('home.has', { cadr: fmtNum(r.purifier_cadr) }) : t('home.need', { cadr: fmtNum(Math.ceil(r.cadr_needed / 50) * 50) }))))),
  );

  const v = plan.ventilation;
  body.append(
    h('div', { class: 'home-lower' },
      h('article', { class: 'vent', 'data-reveal': '' },
        h('h3', {}, icon('window'), t('home.vent_title')),
        h('p', { class: 'vent-text' }, t('home.vent', { min: fmtNum(v.minutes), time: fmtHour(v.best_hour), best: fmtNum(v.pm25_best), mean: fmtNum(v.pm25_waking_mean) })),
        ventStrip(plan.hours, v.best_hour, fmtShort)),
      h('article', { class: 'sources' },
        h('h3', {}, icon('flame'), t('home.sources')),
        plan.sources.length
          ? h('ul', {}, plan.sources.map((s) =>
              h('li', {},
                h('strong', {}, t(`src.${s.kind}`)),
                h('span', {}, s.neighbourhood
                  ? t('src.out', { pm: fmtNum(s.pm25_g_per_day), co2: fmtDec(s.co2_kg_per_day, 1) })
                  : t('src.indoor', { n: fmtNum(s.indoor_increase), room: s.room ?? '' })))))
          : h('p', { class: 'muted' }, t('home.sources_none')))),
  );
}

// --------------------------------------------------------------------------- ask

function messageNode(msg) {
  return h('div', { class: `msg ${msg.role}` },
    h('span', { class: 'who' }, t(msg.role === 'user' ? 'ask.you' : 'ask.saans')),
    h('p', {}, msg.text),
    msg.badge ? h('span', { class: `chip ${msg.badge === 'verified' ? 'solid' : ''}` }, icon(msg.badge === 'verified' ? 'check' : 'info'), t(msg.badge === 'verified' ? 'ask.verified' : 'ask.template')) : null);
}

function renderAsk() {
  const body = clear($('#ask-body'));
  const input = h('input', { type: 'text', id: 'ask-input', maxlength: 2000, autocomplete: 'off', placeholder: t('ask.ph') });
  const log = h('div', { class: 'log', role: 'log', 'aria-live': 'polite' }, askLog.map(messageNode));
  const send = h('button', { type: 'submit', class: 'btn primary' }, icon('send'), h('span', {}, t('ask.send')));
  const error = h('p', { class: 'alert', role: 'alert', hidden: true });

  async function submit(question) {
    const q = question.trim();
    if (!q || send.disabled) return;
    hideError(error);
    askLog.push({ role: 'user', text: q });
    log.append(messageNode(askLog.at(-1)));
    input.value = '';
    send.disabled = true;
    const pending = h('div', { class: 'msg bot pending' }, h('p', {}, t('ask.thinking'), h('span', { class: 'dots', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'))));
    log.append(pending);
    try {
      const data = await api('/api/ask', { body: { household: state.household, question: q } });
      pending.remove();
      askLog.push({ role: 'bot', text: data.answer, badge: data.grounded ? 'verified' : 'template' });
      log.append(messageNode(askLog.at(-1)));
    } catch (err) {
      pending.remove();
      showError(error, err instanceof ApiError && err.code === 'rate_limited' ? t('ask.limited') : errorText(err));
    } finally {
      send.disabled = false;
      log.scrollTop = log.scrollHeight;
    }
  }

  const form = h('form', { class: 'ask-form', novalidate: true, onsubmit: (e) => { e.preventDefault(); submit(input.value); } },
    h('label', { for: 'ask-input', class: 'sr-only' }, t('ask.label')), input, send);
  const chips = h('div', { class: 'chips' }, ['ask.s1', 'ask.s2', 'ask.s3', 'ask.s4'].map((k) =>
    h('button', { type: 'button', class: 'pill', onclick: () => submit(t(k)) }, icon('sparkle'), t(k))));

  body.append(sectionHead('ask-title', 'ask.title', 'ask.lede', 'story.ask', 6), h('div', { class: 'ask' }, form, chips, error, log));
}

function renderResults() {
  if (!state.plan) return;
  const results = $('#results');
  results.hidden = false;
  results.setAttribute('aria-busy', 'false');
  $('#nav-plan').hidden = false;
  renderProblem();
  renderAir();
  renderFamily();
  renderTimeline();
  renderCommute();
  renderLedger();
  renderLadder();
  renderHome();
  renderAsk();
  watch(results);
}

// --------------------------------------------------------------------------- loading skeletons

const bone = (cls) => h('span', { class: `bone ${cls}` });

/** Placeholder blocks sized like the real sections, so nothing jumps when the plan arrives. */
function renderSkeleton() {
  const results = $('#results');
  results.hidden = false;
  results.setAttribute('aria-busy', 'true');
  $('#nav-plan').hidden = false;
  const head = () => h('div', { class: 'skel-head' }, bone('w30'), bone('w60 tall'), bone('w45'));
  const grid = (n, cls) => h('div', { class: `skel-grid ${cls}` }, Array.from({ length: n }, () => bone('card')));
  const fill = (id, ...kids) => clear($(id)).append(h('div', { class: 'skeleton', 'aria-hidden': 'true' }, ...kids));
  $('#res-summary').textContent = '';
  clear($('#res-badges'));
  clear($('#res-scale'));
  clear($('#res-number')).append(h('div', { class: 'skeleton', 'aria-hidden': 'true' }, bone('w45'), bone('number'), bone('w60')));
  $('#res-summary').append(h('span', { class: 'skeleton', 'aria-hidden': 'true' }, bone('w100'), bone('w90'), bone('w60')));
  fill('#air-body', head(), bone('chart'));
  fill('#family-body', head(), grid(4, 'g4'));
  fill('#timeline-body', head(), bone('chart'));
  clear($('#commute-body'));
  $('#commute').hidden = false;
  fill('#commute-body', head(), grid(2, 'g2'));
  fill('#ledger-body', head(), grid(4, 'g4 tall'));
  fill('#ladder-body', head(), bone('row'), bone('row'), bone('row'));
  fill('#home-body', head(), grid(4, 'g4 tall'));
  clear($('#ask-body'));
  announce(t('res.loading'));
}

// --------------------------------------------------------------------------- guided tour

const TOUR_STEPS = [
  { id: 'top', key: 'tour.s1', ms: 6500 },
  { id: 'problem', key: 'tour.s2', ms: 7000 },
  { id: 'air', key: 'tour.s3', ms: 7500 },
  { id: 'family', key: 'tour.s4', ms: 7500 },
  { id: 'timeline', key: 'tour.s5', ms: 8000 },
  { id: 'commute', key: 'tour.s6', ms: 7000 },
  { id: 'ledger', key: 'tour.s7', ms: 8000 },
  { id: 'ladder', key: 'tour.s8', ms: 8500 },
  { id: 'home', key: 'tour.s9', ms: 8500 },
  { id: 'ask', key: 'tour.s10', ms: 6500 },
];

const tour = createTour({
  steps: TOUR_STEPS.map((step) => ({
    ...step,
    el: () => {
      const el = document.getElementById(step.id);
      if (!el || el.hidden) return null;
      return step.id === 'top' || !$('#results').hidden ? el : null;
    },
  })),
});

// --------------------------------------------------------------------------- actions

const MIN_SKELETON_MS = 700;
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function requestPlan({ quiet = false, tour: tourAfter = false } = {}) {
  if (!state.household || state.busy) return;
  const btn = $('#plan-btn');
  const errorEl = $('#plan-error');
  hideError(errorEl);
  state.busy = true;
  if (!quiet) {
    setBusy(btn, true, 'prof.planning');
    renderSkeleton();
    if (!tourAfter) scrollToEl($('#results'));
  }
  try {
    state.household.language = getLanguage();
    const wait = quiet ? Promise.resolve() : pause(MIN_SKELETON_MS);
    const [plan] = await Promise.all([api('/api/plan', { body: { household: state.household } }), wait]);
    state.plan = plan;
    renderResults();
    announce(t('res.updated', { n: state.plan.plan.actions.length }));
    if (tourAfter) tour.start();
    else if (!quiet) $('#results').focus({ preventScroll: true });
  } catch (err) {
    if (!state.plan) $('#results').hidden = true;
    else $('#results').setAttribute('aria-busy', 'false');
    showError(errorEl, errorText(err));
    if (!quiet) scrollToEl($('#profile'));
  } finally {
    state.busy = false;
    if (!quiet) setBusy(btn, false);
  }
}

async function loadDemo(button, { tour: withTour = false } = {}) {
  if (tour.active) tour.stop();
  if (button) setBusy(button, true, 'demo.loading');
  try {
    state.household = await api(`/api/demo?language=${getLanguage()}`, { method: 'GET' });
    state.plan = null;
    askLog.length = 0;
    saveHousehold();
    renderProfile();
    await requestPlan({ tour: withTour });
  } catch (err) {
    showError($('#parse-error'), errorText(err));
    scrollToEl($('#start'));
  } finally {
    if (button) setBusy(button, false);
  }
}

async function parseFamily(event) {
  event.preventDefault();
  const text = $('#parse-text').value.trim();
  const errorEl = $('#parse-error');
  hideError(errorEl);
  if (!text) {
    $('#parse-text').focus();
    return;
  }
  const btn = $('#parse-btn');
  setBusy(btn, true, 'building');
  try {
    const address = $('#parse-address').value.trim();
    const data = await api('/api/profile/parse', {
      body: { text, address: address || null, language: getLanguage() },
    });
    state.household = data.household;
    state.household.budget = $('#parse-budget').value;
    state.plan = null;
    askLog.length = 0;
    saveHousehold();
    renderProfile();
    scrollToEl($('#profile'));
    $('#prof-title').focus({ preventScroll: true });
  } catch (err) {
    showError(errorEl, errorText(err));
  } finally {
    setBusy(btn, false);
  }
}

// --------------------------------------------------------------------------- start

function init() {
  const saved = recall(KEYS.lang);
  setLanguage(saved ?? (navigator.language?.toLowerCase().startsWith('hi') ? 'hi' : 'en'));
  if (recall(KEYS.large) === 'on') document.documentElement.dataset.large = 'on';
  initFx();
  heroField = smogField($('#hero-canvas'), { pm: 240 });
  applyI18n();

  $('#lang-btn').addEventListener('click', changeLanguage);
  $('#large-btn').addEventListener('click', () => {
    const on = document.documentElement.dataset.large !== 'on';
    document.documentElement.dataset.large = on ? 'on' : 'off';
    store(KEYS.large, on ? 'on' : 'off');
    $('#large-btn').setAttribute('aria-pressed', String(on));
  });
  $('#hero-tour').addEventListener('click', () => loadDemo($('#hero-tour'), { tour: true }));
  $('#hero-demo').addEventListener('click', () => loadDemo($('#hero-demo')));
  $('#start-demo').addEventListener('click', () => loadDemo($('#start-demo')));
  $('#parse-form').addEventListener('submit', parseFamily);
  $('#profile').addEventListener('submit', (e) => {
    e.preventDefault();
    requestPlan();
  });

  const params = new URLSearchParams(location.search);
  if (params.get('demo') === '1' || params.get('tour') === '1') {
    loadDemo(null, { tour: params.get('tour') === '1' });
    return;
  }
  const raw = recall(KEYS.household);
  if (raw) {
    try {
      state.household = JSON.parse(raw);
      state.household.language = getLanguage();
      renderProfile();
    } catch {
      store(KEYS.household, null);
    }
  }
}

init();
