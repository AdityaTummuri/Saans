// Tiny DOM helpers. All text goes through textContent or text nodes, never HTML strings.

const SVG_NS = 'http://www.w3.org/2000/svg';
const SVG_TAGS = new Set([
  'svg', 'g', 'path', 'circle', 'rect', 'line', 'use', 'title', 'text', 'defs', 'pattern',
  'linearGradient', 'stop', 'clipPath', 'polygon', 'ellipse',
]);

/** Create an element. `vars` sets CSS custom properties (allowed under the page's CSP). */
export function h(tag, props = {}, ...kids) {
  const el = SVG_TAGS.has(tag)
    ? document.createElementNS(SVG_NS, tag)
    : document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'text') el.textContent = value;
    else if (key === 'vars') {
      for (const [name, v] of Object.entries(value)) el.style.setProperty(name, String(v));
    } else if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2), value);
    } else el.setAttribute(key, value === true ? '' : String(value));
  }
  append(el, kids);
  return el;
}

function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
}

/** An icon from the sprite. */
export function icon(name, cls = '') {
  const svg = h('svg', { class: `icon ${cls}`.trim(), 'aria-hidden': 'true', focusable: 'false' });
  svg.append(h('use', { href: `icons.svg#${name}` }));
  return svg;
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
