"""What only a real browser can answer about the published site.

Everything asserted here is a property Python cannot reach: a font that
actually painted, a request that actually left, a focus ring that
actually drew, a computed style under an emulated user preference, an
HTTP status, a layout that actually overflowed. Anything checkable by
reading the HTML belongs in one of the other test modules, not here.

The site under test is the one ``tests/site_fixture.py`` builds by
running the real generator with only the network stubbed, served over
HTTP from a throwaway directory. HTTP and not ``file://``: relative
paths, the 404 status and webfont loading all behave differently on the
two, and it is the HTTP behaviour that ships.

The whole module skips when Playwright is not installed, and each test
skips when Playwright is installed but its browser is not, so
``uv run pytest`` on a fresh clone reports the rest of the suite green
plus these skips rather than an error. CI installs the browser in a
second job (see .github/workflows/quality.yml) so a browser problem can
never block the ordinary test signal.

Nothing here sleeps. Every wait is a wait on a condition: navigation
settled, ``document.fonts`` finished, an element focused.
"""

from __future__ import annotations

import base64
import re
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests import site_fixture

sync_api = pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed; browser suite skipped",
)

pytestmark = pytest.mark.browser

# ---------------------------------------------------------------------------
# The site, and the server that answers for it.
# ---------------------------------------------------------------------------

# Two days is the smallest history that produces every page class at
# once: a home page with a hero and a populated grid, an archive front
# with a month index, a month bucket, and two species pages. Both birds
# have a photograph, so the hot-linked Macaulay CDN is exercised too,
# and the second day's bird carries a GBIF distribution map (see
# site_fixture.MAPPED_SPECIES) so that both plate layouts, with atlas
# and without, are measured here.
SITE_DAYS = ["2026-01-01", "2026-01-02"]

# Every page class the generator writes, as a browser reaches it. Both
# species pages are listed, not one: fakwrn1's plate carries the atlas
# and fakhaw1's does not, and the layouts fail differently. The 404 is
# requested by a path that does not exist, which is the only way to get
# the status: asking for /404.html by name is an ordinary hit.
PAGE_PATHS = {
    "index": "/index.html",
    "archive-front": "/archive.html",
    "month-bucket": "/archive-2026-01.html",
    "species-with-atlas": f"/birds/{site_fixture.MAPPED_SPECIES}.html",
    "species-without-atlas": "/birds/fakhaw1.html",
    "not-found": "/no-such-page",
}

# Where the atlas frame, the widest thing the site draws, must appear:
# the three page classes that render a plate. The archive front is not
# among them, because it renders cards and a month index rather than
# plates, so no atlas reaches it however recent the mapped species is.
PAGES_WITH_ATLAS = [
    PAGE_PATHS["index"],
    PAGE_PATHS["month-bucket"],
    PAGE_PATHS["species-with-atlas"],
]
ALL_PAGES = list(PAGE_PATHS.values())
CONTENT_PAGES = [p for name, p in PAGE_PATHS.items() if name != "not-found"]

# Hot-linked by design, and the only two origins allowed to appear: the
# Macaulay Library photo CDN and, for species with a GBIF match, the
# occurrence density tile. Everything else the site needs (stylesheet,
# webfonts, basemap, favicon) is published alongside the pages.
ALLOWED_FOREIGN_ORIGINS = frozenset(
    {
        "https://cdn.download.ams.birds.cornell.edu",
        "https://api.gbif.org",
    }
)

# A 1x1 transparent PNG. Stands in for anything the page fetches from a
# foreign origin, so the suite records the request without making it and
# stays offline, fast and immune to a CDN having a bad afternoon.
_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8A"
    "AAAASUVORK5CYII="
)


def _page_id(path: str) -> str:
    """A readable parametrize id: the path without its leading slash."""
    return path.strip("/") or "root"


class _SiteHandler(SimpleHTTPRequestHandler):
    """A static file server that answers a missing path the way nginx does.

    The deployed site maps every unknown URL onto 404.html's body with a
    real 404 status (``error_page 404 /404.html``, and GitHub Pages does
    the same). Serving the directory plainly would answer 404 with the
    stock one-line error document instead, and the status test would be
    asserting about a page the reader never sees.
    """

    # woff2 predates several of the mimetypes databases this can run
    # against; without this the fonts arrive as application/octet-stream.
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".woff2": "font/woff2"}

    def send_error(self, code, message=None, explain=None):
        if code != 404:
            super().send_error(code, message, explain)
            return
        body = (Path(self.directory) / "404.html").read_bytes()
        self.send_response(404, message)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        """Silence the per-request log; pytest's output is the signal here."""


@pytest.fixture(scope="session")
def base_url(tmp_path_factory) -> str:
    """Build the site once, serve it, and yield the origin it answers on.

    The server is bound before the site is built so that its port is
    known in time to be configured as the site's ``feed_link``. That
    matters for exactly one page: 404.html is rendered with absolute
    URLs (it is served for a URL of any depth, so it cannot use
    depth-relative ones), and with the default ``feed_link`` its own
    stylesheet would point off-site.
    """
    tmp_path = tmp_path_factory.mktemp("browser-site")
    root = tmp_path / "state"

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(_SiteHandler, directory=str(root)),
        bind_and_activate=False,
    )
    server.allow_reuse_address = True
    server.server_bind()
    server.server_activate()
    origin = f"http://127.0.0.1:{server.server_address[1]}"

    with pytest.MonkeyPatch.context() as monkeypatch:
        site_fixture.build_site(monkeypatch, tmp_path, SITE_DAYS, feed_link=origin)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield origin
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    """A headless Chromium, or a skip if Playwright has no browser installed.

    Deliberately independent of ``base_url``, and named first in every
    test signature, so that a machine with no browser skips before it
    builds and serves a site nothing will ever load.
    """
    with sync_api.sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch()
        except sync_api.Error as exc:  # no browser binary on this machine
            pytest.skip(f"playwright has no chromium installed: {exc}")
        try:
            yield instance
        finally:
            instance.close()


class _Visit:
    """One loaded page, plus every request it made while loading."""

    def __init__(self, page, response, requests: list[str]) -> None:
        self.page = page
        self.response = response
        self.requests = requests

    def origins(self) -> set[str]:
        return {f"{u.scheme}://{u.netloc}" for u in map(urlsplit, self.requests)}


@contextmanager
def visit(browser, base_url: str, path: str, **context_kwargs):
    """Open ``path``, recording (and stubbing out) every foreign request.

    A request to any origin other than the test server is answered from
    memory with a 1x1 PNG rather than being let out, so the suite never
    touches the internet, and is recorded either way: what is asserted
    is the set of origins the page *asked* for, which is the thing that
    would leak in production.
    """
    context = browser.new_context(**context_kwargs)
    requests: list[str] = []

    def handle(route, request):
        requests.append(request.url)
        if request.url.startswith(base_url):
            route.continue_()
        else:
            route.fulfill(status=200, content_type="image/png", body=_PNG_1X1)

    context.route("**/*", handle)
    page = context.new_page()
    try:
        response = page.goto(base_url + path, wait_until="load")
        # Not a sleep: resolves as soon as every face the page actually
        # needs has finished loading (or failed to).
        page.wait_for_function("document.fonts.status === 'loaded'")
        yield _Visit(page, response, requests)
    finally:
        context.close()


# ---------------------------------------------------------------------------
# The webfonts actually paint.
# ---------------------------------------------------------------------------


def test_the_webfonts_load_and_the_masthead_is_set_in_fraunces(browser, base_url):
    """Both families load, and the masthead really resolves to Fraunces.

    The site rendered in a fallback serif for months because the old
    Google Fonts @import URL was malformed. Nothing in the HTML could
    have said so: the stylesheet was linked, the rule matched, the
    declared font-family named Fraunces. Only the browser knows whether
    a face was ever fetched and used.
    """
    with visit(browser, base_url, PAGE_PATHS["index"]) as v:
        state = v.page.evaluate(
            """() => {
                const h = document.querySelector('header.site h1');
                const cs = getComputedStyle(h);
                return {
                  declared: cs.fontFamily,
                  weight: cs.fontWeight,
                  size: cs.fontSize,
                  text: h.textContent.trim(),
                  loaded: Array.from(document.fonts)
                    .filter(f => f.status === 'loaded')
                    .map(f => f.family),
                };
            }"""
        )
        painted = v.page.evaluate(
            "([w, s, t]) => document.fonts.check(`${w} ${s} Fraunces`, t)",
            [state["weight"], state["size"], state["text"]],
        )

    assert state["declared"].startswith("Fraunces"), (
        "the masthead does not even ask for Fraunces: "
        f"computed font-family is {state['declared']!r}"
    )
    assert "Fraunces" in state["loaded"], (
        "no Fraunces face finished loading; the masthead is painting in a "
        f"fallback. Loaded families: {sorted(set(state['loaded']))}"
    )
    assert "Source Serif 4" in state["loaded"], (
        "no Source Serif 4 face finished loading; the body text is painting "
        f"in a fallback. Loaded families: {sorted(set(state['loaded']))}"
    )
    assert painted, (
        "document.fonts.check says the masthead's own text cannot be drawn "
        "in Fraunces at its computed weight and size"
    )


# ---------------------------------------------------------------------------
# Nothing leaves the site.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ALL_PAGES, ids=_page_id)
def test_no_page_requests_an_origin_it_has_no_business_requesting(
    browser, base_url, path
):
    """Every request goes to the site itself, or to one of two hot links.

    The photo CDN and the GBIF density tile are hot-linked deliberately
    and are the whole of the allowance. A stylesheet, a webfont, an
    icon or an analytics beacon appearing on any other origin is a
    regression, and one that reading the HTML would miss the moment it
    arrived through an ``@import`` or a redirect.

    404.html is in the list on purpose: it is the one page rendered with
    absolute URLs rather than depth-relative ones, so it is the one page
    that could quietly start fetching its own stylesheet from elsewhere.
    """
    with visit(browser, base_url, path) as v:
        origins = v.origins()

    assert base_url in origins, "the page did not even fetch itself"
    foreign = origins - {base_url}
    assert foreign <= ALLOWED_FOREIGN_ORIGINS, (
        f"{path} reaches origins it is not allowed to: "
        f"{sorted(foreign - ALLOWED_FOREIGN_ORIGINS)}"
    )


def test_the_stylesheet_and_a_webfont_are_served_by_the_site_itself(
    browser, base_url
):
    """The allowance above is not vacuous: the real assets are local.

    A page that fetched nothing at all would satisfy the test above.
    This one names the two assets whose absence would be the actual
    disaster and insists they came from the site's own origin.
    """
    with visit(browser, base_url, PAGE_PATHS["index"]) as v:
        requests = list(v.requests)

    assert f"{base_url}/assets/site.css" in requests, (
        f"the stylesheet was not fetched from the site: {requests}"
    )
    fonts = [u for u in requests if u.endswith(".woff2")]
    assert fonts, f"no webfont was fetched at all: {requests}"
    assert all(u.startswith(base_url) for u in fonts), (
        f"a webfont was fetched from somewhere else: {fonts}"
    )


# ---------------------------------------------------------------------------
# The card link is reachable, ringed and named.
# ---------------------------------------------------------------------------


def test_the_card_link_draws_a_focus_ring_and_has_an_accessible_name(
    browser, base_url
):
    """Tab to the grid card and check the ring the keyboard user sees.

    ``:focus-visible`` is why this cannot be a stylesheet assertion: the
    rule exists either way, and what matters is whether it matches after
    a real Tab. The accessible name is computed by the browser from the
    anchor's whole subtree, which is why it is checked here and not by
    reading the markup; requiring the bird's own name in it asserts more
    than "not empty", since a card announced as "link" and nothing else
    would satisfy the weaker version.
    """
    with visit(browser, base_url, PAGE_PATHS["index"]) as v:
        page = v.page
        assert page.locator("article.card").count() >= 1, (
            "the home page has no grid card to focus"
        )
        card_link = page.locator("article.card a").first
        resting = card_link.evaluate("el => getComputedStyle(el).outlineStyle")

        for _ in range(60):
            page.keyboard.press("Tab")
            if card_link.evaluate("el => el === document.activeElement"):
                break
        else:
            raise AssertionError(
                "60 presses of Tab never reached the first grid card's link"
            )

        ring = card_link.evaluate(
            """el => {
                const cs = getComputedStyle(el);
                return {
                  focusVisible: el.matches(':focus-visible'),
                  style: cs.outlineStyle,
                  width: parseFloat(cs.outlineWidth),
                  color: cs.outlineColor,
                };
            }"""
        )
        sync_api.expect(card_link).to_have_accessible_name(re.compile(r"\bFake Hawk\b"))

    assert ring["focusVisible"], (
        "the card link took keyboard focus but :focus-visible did not match, "
        "so no ring is drawn"
    )
    assert ring["style"] not in ("none", "hidden"), (
        f"focused card link has outline-style {ring['style']!r}"
    )
    assert ring["width"] > 0, f"focused card link has a {ring['width']}px outline"
    assert resting in ("none", "hidden") or ring["style"] != resting, (
        "the outline looks identical focused and unfocused, so nothing about "
        "the ring is actually a focus indicator"
    )


@pytest.mark.parametrize("path", ALL_PAGES, ids=_page_id)
def test_no_anchor_is_nested_inside_another_anchor(browser, base_url, path):
    """No page contains a link inside a link.

    The card is one big anchor wrapping a thumbnail, a name and a
    scientific name; adding a second link inside it (an IUCN badge that
    became a link, a republication chip that forgot it is only a chip)
    would be invalid HTML that the parser silently repairs by closing
    the outer anchor early, quietly amputating the card's own link.
    Checked in the DOM the browser actually built.
    """
    with visit(browser, base_url, path) as v:
        nested = v.page.evaluate(
            """() => Array.from(document.querySelectorAll('a a'))
                .map(el => el.outerHTML.slice(0, 120))"""
        )
    assert nested == [], f"{path} nests anchors: {nested}"


# ---------------------------------------------------------------------------
# Reduced motion is honoured.
# ---------------------------------------------------------------------------

# The elements whose transitions are the perceptible motion on the site:
# the hero photo's slow zoom, a card thumbnail's zoom, and the link
# underline colour that every page has.
_MOVING = [".plate-image img", "article.card a", "header.site nav a"]


def test_reduced_motion_neutralises_every_transition(browser, base_url):
    """With the preference set, the durations computed by the browser are zero.

    Read as computed style under an emulated preference, not from the
    stylesheet: the question is whether the media query matches and wins
    over the specific rules that set the durations, and only a browser
    resolving the cascade can answer that. The first half of the test is
    the control, and exists so that a stylesheet which stopped animating
    anything at all could not pass the second half by default.
    """
    script = (
        "sels => sels.map(s => getComputedStyle(document.querySelector(s))"
        ".transitionDuration)"
    )

    with visit(browser, base_url, PAGE_PATHS["index"]) as v:
        ordinary = v.page.evaluate(script, _MOVING)

    with visit(
        browser, base_url, PAGE_PATHS["index"], reduced_motion="reduce"
    ) as v:
        reduced = v.page.evaluate(script, _MOVING)

    def seconds(value: str) -> float:
        """Longest duration in a comma-separated transition-duration list."""
        return max(
            float(part[:-2]) / 1000 if part.endswith("ms") else float(part[:-1])
            for part in (p.strip() for p in value.split(","))
        )

    for selector, before in zip(_MOVING, ordinary):
        assert seconds(before) > 0.05, (
            f"{selector} does not transition even without the preference "
            f"({before}), so this test would prove nothing"
        )
    for selector, after in zip(_MOVING, reduced):
        assert seconds(after) <= 0.001, (
            f"{selector} still transitions over {after} under "
            "prefers-reduced-motion: reduce"
        )


# ---------------------------------------------------------------------------
# The 404 is a 404, and it is the only page that says noindex.
# ---------------------------------------------------------------------------


def test_a_url_that_does_not_exist_answers_404_and_says_noindex(browser, base_url):
    """The error page carries the status as well as the apology.

    A 404 body served with a 200 is indexed, linked and counted as a
    real page by everything that reads the status rather than the prose,
    which is every crawler and every uptime check.
    """
    with visit(browser, base_url, PAGE_PATHS["not-found"]) as v:
        status = v.response.status
        robots = v.page.evaluate(
            "() => Array.from(document.querySelectorAll('meta[name=robots]'))"
            ".map(m => m.content)"
        )
        heading = v.page.locator("h1").first.inner_text()

    assert status == 404, f"a URL that does not exist answered {status}"
    assert any("noindex" in c for c in robots), (
        f"the 404 page does not say noindex; its robots meta is {robots}"
    )
    assert heading.strip(), "the 404 page rendered without a heading"


@pytest.mark.parametrize("path", CONTENT_PAGES, ids=_page_id)
def test_no_page_with_content_says_noindex(browser, base_url, path):
    """``noindex`` belongs to 404.html alone and must not spread by copying."""
    with visit(browser, base_url, path) as v:
        robots = v.page.evaluate(
            "() => Array.from(document.querySelectorAll('meta[name=robots]'))"
            ".map(m => m.content)"
        )
    assert not any("noindex" in c for c in robots), (
        f"{path} tells crawlers to ignore it: robots meta is {robots}"
    )


# ---------------------------------------------------------------------------
# Nothing overflows horizontally on a phone.
# ---------------------------------------------------------------------------

# 390x844 is the iPhone 12/13/14 logical viewport, and the narrowest
# width worth supporting: below it the layout is nobody's actual phone.
PHONE = {"width": 390, "height": 844}


@pytest.mark.parametrize("path", ALL_PAGES, ids=_page_id)
def test_the_fixture_site_really_renders_an_atlas(browser, base_url, path):
    """The overflow check below must never quietly stop seeing the atlas.

    Its frame is the widest single element the site draws, and it is
    absent from a plate whose species GBIF does not know, so a fixture
    change that dropped the map would take the hardest case out of the
    measurement without any test going red. This one goes red instead.
    """
    with visit(browser, base_url, path) as v:
        frames = v.page.locator(".atlas-frame").count()
    if path in PAGES_WITH_ATLAS:
        assert frames == 1, f"{path} should render exactly one atlas, found {frames}"
    else:
        assert frames == 0, f"{path} renders an atlas it has no map for"


@pytest.mark.parametrize("path", ALL_PAGES, ids=_page_id)
def test_nothing_overflows_horizontally_on_a_phone(browser, base_url, path):
    """At 390 CSS pixels no page is wider than the viewport it is shown in.

    ``scrollWidth`` against ``clientWidth`` and not against
    ``innerWidth``: the second includes whatever space a vertical
    scrollbar occupies, which is not space the content may use. On
    failure the offending elements are named, because "something is too
    wide" is not a report anyone can act on. Elements parked off the
    left edge are not offenders: that is how ``.skip-link`` hides until
    focused, and a negative left does not make the document scroll.
    """
    with visit(browser, base_url, path, viewport=PHONE) as v:
        measured = v.page.evaluate(
            """() => {
                const doc = document.documentElement;
                const limit = doc.clientWidth;
                const guilty = [];
                for (const el of document.querySelectorAll('body *')) {
                  const r = el.getBoundingClientRect();
                  if (r.width === 0 && r.height === 0) continue;
                  if (r.right > limit + 0.5) {
                    guilty.push({
                      tag: el.tagName.toLowerCase(),
                      cls: el.className && el.className.toString(),
                      left: Math.round(r.left),
                      right: Math.round(r.right),
                    });
                  }
                }
                guilty.sort((a, b) => b.right - a.right);
                return {scrollWidth: doc.scrollWidth, clientWidth: limit, guilty};
            }"""
        )

    assert measured["scrollWidth"] <= measured["clientWidth"], (
        f"{path} scrolls sideways at {PHONE['width']}px: document is "
        f"{measured['scrollWidth']}px wide inside a "
        f"{measured['clientWidth']}px viewport. Widest offenders: "
        f"{measured['guilty'][:8]}"
    )
