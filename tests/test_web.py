"""Static checks on the front end: CSP-safe markup, textContent-only rendering, i18n parity."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import WEB_DIR, create_app

JS_FILES = ["app.js", "charts.js", "dom.js", "fx.js", "i18n.js", "tour.js", "viz.js"]


def read(name: str) -> str:
    return (WEB_DIR / name).read_text(encoding="utf-8")


def test_index_is_served_with_static_assets() -> None:
    settings = Settings(demo_mode=True, _env_file=None)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as client:
        index = client.get("/")
        assert index.status_code == 200 and "Saans" in index.text
        for path, kind in [
            ("/app.js", "javascript"),
            ("/styles.css", "css"),
            ("/icons.svg", "svg"),
        ]:
            res = client.get(path)
            assert res.status_code == 200 and kind in res.headers["content-type"], path


def test_markup_is_csp_safe() -> None:
    html = read("index.html")
    assert not re.search(r"\sstyle\s*=", html), "inline style attributes are blocked by the CSP"
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handlers are blocked by the CSP"
    scripts = re.findall(r"<script\b[^>]*>", html)
    assert scripts and all("src=" in s for s in scripts), "inline scripts are blocked by the CSP"
    # only Google Fonts is allowed as an external origin
    origins = set(re.findall(r"https?://([\w.-]+)", html))
    assert origins <= {"fonts.googleapis.com", "fonts.gstatic.com", "github.com", "www.w3.org"}, (
        origins
    )


def test_js_renders_text_with_textcontent_only() -> None:
    for name in JS_FILES:
        source = read(name)
        assert "innerHTML" not in source and "outerHTML" not in source, name
        assert "insertAdjacentHTML" not in source and "document.write" not in source, name
        assert "eval(" not in source and "new Function" not in source, name
        assert 'setAttribute("style"' not in source and "setAttribute('style'" not in source, name


def test_no_external_requests_from_js_or_css() -> None:
    for name in [*JS_FILES, "styles.css"]:
        urls = re.findall(r"https?://[\w./-]+", read(name))
        assert all("github.com" in u or "www.w3.org" in u for u in urls), (name, urls)


def _keys(block: str) -> set[str]:
    keys = set(re.findall(r"^\s+'?([\w.]+)'?:", block, flags=re.MULTILINE))
    return keys - {"en", "hi"}


def test_english_and_hindi_strings_have_the_same_keys() -> None:
    source = read("i18n.js")
    en, hi = source.split("\n  hi: {", 1)
    en_keys, hi_keys = _keys(en), _keys(hi.split("\n};", 1)[0])
    assert len(en_keys) > 200
    assert en_keys == hi_keys, sorted(en_keys ^ hi_keys)


def test_every_static_i18n_key_exists() -> None:
    html = read("index.html")
    source = read("i18n.js")
    used = set(re.findall(r'data-i18n="([\w.]+)"', html))
    for pair in re.findall(r'data-i18n-attr="([^"]+)"', html):
        used.update(p.split(":")[1] for p in pair.split(";"))
    defined = _keys(source.split("\n  hi: {", 1)[0])
    assert used <= defined, sorted(used - defined)


def test_icon_sprite_covers_every_icon_used() -> None:
    sprite = set(re.findall(r'<symbol id="([\w-]+)"', read("icons.svg")))
    used = set(re.findall(r"icons\.svg#([\w-]+)", read("index.html")))
    for name in JS_FILES:
        used |= set(re.findall(r"icon\('([\w-]+)'", read(name)))
    used |= {"shift_activity"} - {"shift_activity"}  # kind icons are listed below
    kind_icons = set(
        re.findall(
            r"^\s+\w+: '([\w-]+)',$",
            read("app.js")[: read("app.js").index("const SOURCE_ICON")],
            re.M,
        )
    )
    modes = {"walk", "cycle", "two_wheeler", "auto_rickshaw", "car", "bus", "metro"}
    missing = (used | kind_icons | modes) - sprite
    assert not missing, sorted(missing)


def test_web_dir_is_small() -> None:
    total = sum(f.stat().st_size for f in Path(WEB_DIR).rglob("*") if f.is_file())
    assert total < 400_000


def _defined(lang: str) -> set[str]:
    en, hi = read("i18n.js").split("\n  hi: {", 1)
    return _keys(en if lang == "en" else hi.split("\n};", 1)[0])


def test_every_literal_i18n_key_used_in_js_exists_in_both_languages() -> None:
    used: set[str] = set()
    for name in JS_FILES:
        if name == "i18n.js":
            continue
        used |= set(re.findall(r"\bt\('([\w.]+)'", read(name)))
        used |= set(
            re.findall(
                r"'((?:ladder|home|led|tl|commute|fam|air|res|story|hero|tour)\.[\w.]+)'",
                read(name),
            )
        )
    used = {k for k in used if not re.fullmatch(r"tour\.s\d+", k)}  # step prefixes: see below
    for lang in ("en", "hi"):
        assert used <= _defined(lang), (lang, sorted(used - _defined(lang)))


def test_tour_steps_have_captions_in_both_languages() -> None:
    keys = re.findall(r"key: '(tour\.s\d+)'", read("app.js"))
    assert len(keys) >= 8
    for lang in ("en", "hi"):
        defined = _defined(lang)
        for key in keys:
            assert f"{key}.t" in defined and f"{key}.d" in defined, (lang, key)
        for control in ("prev", "next", "pause", "play", "exit", "finish", "keys", "step", "label"):
            assert f"tour.{control}" in defined, (lang, control)


def test_tour_is_url_driven_keyboard_operable_and_stops_cleanly() -> None:
    app, tour = read("app.js"), read("tour.js")
    assert "params.get('tour')" in app
    for needle in (
        "'Escape'",
        "' '",
        "ArrowRight",
        "ArrowLeft",
        "removeEventListener",
        "aria-live",
    ):
        assert needle in tour, needle


def test_effects_rest_when_hidden_or_motion_is_reduced() -> None:
    fx = read("fx.js")
    assert (
        "prefers-reduced-motion" in fx and "visibilitychange" in fx and "IntersectionObserver" in fx
    )
    css = read("styles.css")
    assert "@media (prefers-reduced-motion: reduce)" in css
    # entrance states only apply when JS has switched effects on
    assert "html[data-fx='on']" in css


def test_severity_is_never_colour_alone_in_charts() -> None:
    charts, viz, css = read("charts.js"), read("viz.js"), read("styles.css")
    assert "zone-label" in charts and "STRIPED" in charts and "air.col_band" in charts
    assert "signal(" in viz and "repeating-linear-gradient" in css
