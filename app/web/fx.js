// Visual effects, all hand-written and local: the drifting PM2.5 field, scroll-in reveals and
// count-up numbers. Every effect rests under prefers-reduced-motion and pauses off-screen.

const TAU = Math.PI * 2;
const BREATH_SECONDS = 10; // 4 s in, 6 s out, matched by the CSS orb
const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// --------------------------------------------------------------------------- state

let observer = null;
let motionOn = true;

/** Call once. Marks the document so CSS only hides things that JS will later reveal. */
export function initFx() {
  const query = window.matchMedia('(prefers-reduced-motion: reduce)');
  const apply = () => {
    motionOn = !query.matches;
    document.documentElement.dataset.fx = motionOn ? 'on' : 'off';
  };
  apply();
  query.addEventListener?.('change', apply);
  if ('IntersectionObserver' in window) {
    observer = new IntersectionObserver(onIntersect, { threshold: 0.18, rootMargin: '0px 0px -6% 0px' });
  }
}

// --------------------------------------------------------------------------- reveal and count-up

const numberFormat = (decimals) =>
  new Intl.NumberFormat(document.documentElement.lang === 'hi' ? 'hi-IN' : 'en-IN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });

function paintCount(el, value) {
  el.textContent = numberFormat(Number(el.dataset.dec ?? 0)).format(value);
}

function runCount(el) {
  const target = Number(el.dataset.count);
  if (!Number.isFinite(target)) return;
  if (!motionOn) {
    paintCount(el, target);
    return;
  }
  const start = performance.now();
  const duration = 1200;
  const step = (now) => {
    const k = clamp((now - start) / duration);
    paintCount(el, target * (1 - (1 - k) ** 3));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function reveal(el) {
  if (el.dataset.in !== undefined) return;
  el.dataset.in = '';
  for (const node of el.querySelectorAll('[data-count]')) runCount(node);
  if (el.matches('[data-count]')) runCount(el);
}

function onIntersect(entries) {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    observer.unobserve(entry.target);
    reveal(entry.target);
  }
}

/** Register every [data-reveal] element under root. Counts start from zero until revealed. */
export function watch(root) {
  const items = [...root.querySelectorAll('[data-reveal]')];
  if (root.matches?.('[data-reveal]')) items.push(root);
  for (const el of items) {
    if (!motionOn || !observer) {
      el.dataset.in = '';
      continue;
    }
    delete el.dataset.in;
    for (const node of el.querySelectorAll('[data-count]')) paintCount(node, 0);
    observer.observe(el);
  }
}

/** Animate one number now (used for the hero and problem figures). */
export function setCount(el, value, decimals = 0) {
  el.dataset.dec = String(decimals);
  const from = Number(el.dataset.count);
  el.dataset.count = String(value);
  if (!motionOn || !Number.isFinite(from)) {
    paintCount(el, value);
    return;
  }
  const start = performance.now();
  const step = (now) => {
    const k = clamp((now - start) / 900);
    paintCount(el, from + (value - from) * (1 - (1 - k) ** 3));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// --------------------------------------------------------------------------- the smog field

/**
 * A canvas of drifting particles. `setPm(µg/m³)` changes the density and the colour (clean teal
 * to hazy amber). The field inhales and exhales around `anchor`, a point given as fractions of
 * the canvas, in step with the CSS orb. Pauses when off-screen or when the tab is hidden, and
 * draws a single still frame under reduced motion.
 */
export function smogField(canvas, { pm = 240, anchor = [0.74, 0.48] } = {}) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return { setPm() {}, destroy() {} };

  let width = 0;
  let height = 0;
  let dpr = 1;
  let parts = [];
  let target = pm;
  let shown = pm;
  let frameId = 0;
  let onScreen = true;
  let last = 0;
  let clock = 0;
  const pointer = { x: -9999, y: -9999 };
  const rgb = { smog: [240, 168, 92], clean: [110, 224, 190] };

  const readColours = () => {
    const css = getComputedStyle(canvas);
    for (const [key, name] of [['smog', '--fx-rgb'], ['clean', '--fx-clean-rgb']]) {
      const parsed = css.getPropertyValue(name).trim().split(/\s+/).map(Number);
      if (parsed.length === 3 && parsed.every(Number.isFinite)) rgb[key] = parsed;
    }
  };

  const capacity = () => clamp(Math.round((width * height) / 3600), 80, 420);
  const severity = () => clamp((shown - 20) / 300);
  const activeCount = () => capacity() * (0.14 + 0.86 * severity());

  function seed() {
    const total = capacity();
    parts = Array.from({ length: total }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      r: 0.9 + Math.random() ** 2.2 * 4.6,
      depth: 0.35 + Math.random() * 0.65,
      phase: Math.random() * TAU,
      alpha: 0.3 + Math.random() * 0.6,
    }));
  }

  function resize() {
    const box = canvas.parentElement.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    width = Math.max(1, Math.round(box.width));
    height = Math.max(1, Math.round(box.height));
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    seed();
    draw();
  }

  function mixed(k) {
    return rgb.clean.map((c, i) => Math.round(c + (rgb.smog[i] - c) * k));
  }

  function draw() {
    ctx.clearRect(0, 0, width, height);
    const k = severity();
    const [r, g, b] = mixed(k);
    // soft haze blobs
    const blobs = 5;
    for (let i = 0; i < blobs; i += 1) {
      const bx = ((i + 0.5) / blobs) * width + Math.sin(clock * 0.07 + i * 2.1) * width * 0.08;
      const by = height * (0.3 + 0.4 * ((i * 0.37) % 1)) + Math.cos(clock * 0.05 + i) * height * 0.06;
      const rad = Math.max(width, height) * (0.28 + 0.05 * (i % 3));
      const grad = ctx.createRadialGradient(bx, by, 0, bx, by, rad);
      const a = 0.07 + 0.2 * k;
      grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${a})`);
      grad.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, width, height);
    }
    // particles
    const live = activeCount();
    for (let i = 0; i < parts.length; i += 1) {
      const p = parts[i];
      const presence = clamp(live - i);
      if (presence <= 0) continue;
      ctx.globalAlpha = p.alpha * presence * (0.55 + 0.45 * k);
      ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * (0.7 + 0.5 * k), 0, TAU);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function advance(dt) {
    clock += dt;
    shown += (target - shown) * Math.min(1, dt * 1.6);
    const breath = Math.sin((clock / BREATH_SECONDS) * TAU); // + inhale, - exhale
    const ax = anchor[0] * width;
    const ay = anchor[1] * height;
    const reach = Math.min(width, height) * 0.55;
    const wind = 10 + 22 * severity();
    for (const p of parts) {
      let vx = -wind * p.depth;
      let vy = Math.sin(p.x * 0.006 + clock * 0.4 + p.phase) * 9 * p.depth - 3;
      const dx = ax - p.x;
      const dy = ay - p.y;
      const dist = Math.hypot(dx, dy) || 1;
      if (dist < reach) {
        const pull = (1 - dist / reach) * breath * 34;
        vx += (dx / dist) * pull;
        vy += (dy / dist) * pull;
      }
      const px = p.x - pointer.x;
      const py = p.y - pointer.y;
      const pd = Math.hypot(px, py);
      if (pd < 110) {
        const push = (1 - pd / 110) * 90;
        vx += (px / (pd || 1)) * push;
        vy += (py / (pd || 1)) * push;
      }
      p.x += vx * dt;
      p.y += vy * dt;
      if (p.x < -10) p.x = width + 10;
      if (p.x > width + 10) p.x = -10;
      if (p.y < -10) p.y = height + 10;
      if (p.y > height + 10) p.y = -10;
    }
  }

  function loop(now) {
    frameId = 0;
    if (!canRun()) return;
    const dt = Math.min(0.05, (now - last) / 1000 || 0.016);
    last = now;
    advance(dt);
    draw();
    frameId = requestAnimationFrame(loop);
  }

  const canRun = () => onScreen && !document.hidden && !reduced();

  function sync() {
    if (canRun()) {
      if (!frameId) {
        last = performance.now();
        frameId = requestAnimationFrame(loop);
      }
    } else if (frameId) {
      cancelAnimationFrame(frameId);
      frameId = 0;
    }
  }

  const resizer = new ResizeObserver(() => resize());
  const sizeHost = canvas.parentElement;
  const visibility = new IntersectionObserver((entries) => {
    onScreen = entries.at(-1).isIntersecting;
    sync();
  });
  const onPointer = (e) => {
    const box = canvas.getBoundingClientRect();
    pointer.x = e.clientX - box.left;
    pointer.y = e.clientY - box.top;
  };
  const onLeave = () => {
    pointer.x = -9999;
    pointer.y = -9999;
  };
  const host = canvas.closest('section') ?? canvas.parentElement;

  readColours();
  resizer.observe(sizeHost);
  visibility.observe(canvas);
  document.addEventListener('visibilitychange', sync);
  host.addEventListener('pointermove', onPointer, { passive: true });
  host.addEventListener('pointerleave', onLeave);
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
    readColours();
    draw();
  });

  return {
    setPm(value) {
      target = value;
      if (reduced()) {
        shown = value;
        draw();
      } else sync();
    },
    destroy() {
      cancelAnimationFrame(frameId);
      resizer.disconnect();
      visibility.disconnect();
      document.removeEventListener('visibilitychange', sync);
      host.removeEventListener('pointermove', onPointer);
      host.removeEventListener('pointerleave', onLeave);
    },
  };
}
