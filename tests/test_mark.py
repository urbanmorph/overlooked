"""The site's mark: the seven gaps as the species pages draw them (web.js glyphSVG): four cells on top, two, then the
Linnean cell at the base; the top layer in the light green of "part known", the Prestonian cell in orange. The browser
tab (16 px) has three bars, one per layer, because seven cells are too small there."""

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "site" / "assets" / "style.css").read_text()
# The gap shades are defined once, as tokens in style.css; the blocks, the glyph and the header mark use them.
ROOTVARS = dict(re.findall(r"--([\w-]+): ([^;]+);", re.search(r":root \{(.*?)\}", CSS, re.DOTALL)[1]))


def token(name):
    v = ROOTVARS[name].strip()
    return token(v[6:-1]) if v.startswith("var(--") else v


ACCENT, PART, ORANGE = token("gap-known"), token("gap-part"), token("gap-open")


def fills(svg):
    return re.findall(r'<rect[^>]*fill="(#[0-9A-Fa-f]{6})"', svg)


def test_the_gap_shades_are_tokens_used_everywhere():
    assert (ACCENT, PART, ORANGE) == ("#0B5D4B", "#9FC8BA", "#B4480E")
    assert CSS.count(PART) == 1                                       # no copy of a shade outside its token
    for js in (ROOT / "site" / "assets").glob("*.js"):
        assert "class=\"sw blk" not in js.read_text() or js.name == "web.js", js.name   # one key builder (web.js pyramidKey)


def test_the_header_mark_is_the_seven_gap_glyph():
    svg = re.search(r'<a class="brand".*?(<svg.*?</svg>)', (ROOT / "site-parts" / "header.html").read_text(), re.DOTALL)[1]
    assert re.findall(r'<rect[^>]*class="([\w-]+)"', svg) == ["m-open", "m-part", "m-part", "m-part", "m-known", "m-known", "m-known"]
    assert "fill=" not in svg
    for page in ["index.html", "species.html", "method.html"]:      # pages.py puts the header on every page
        assert svg in (ROOT / "site" / page).read_text(), page


def test_the_favicon_is_three_bars_with_the_top_layer_light_green_and_orange():
    assert fills((ROOT / "site" / "favicon.svg").read_text()) == [PART, ORANGE, ACCENT, ACCENT]


def test_the_home_screen_icon_is_180_pixels():
    png = (ROOT / "site" / "apple-touch-icon.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (180, 180)
    assert fills((ROOT / "site-parts" / "apple-touch-icon.svg").read_text())[0] == ACCENT    # its source
