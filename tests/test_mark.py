"""The site's mark: the seven gaps as the species pages draw them (web.js glyphSVG): four cells on top, two, then the
Linnean cell at the base; the top layer in the light green of "part known", the Prestonian cell in orange. The browser
tab (16 px) has three bars, one per layer, because seven cells are too small there."""

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCENT, PART, ORANGE = "#0B5D4B", "#9FC8BA", "#B4480E"


def fills(svg):
    return re.findall(r'<rect[^>]*fill="(#[0-9A-Fa-f]{6})"', svg)


def test_the_header_mark_is_the_seven_gap_glyph():
    svg = re.search(r'<a class="brand".*?(<svg.*?</svg>)', (ROOT / "site-parts" / "header.html").read_text(), re.S)[1]
    assert fills(svg) == [ORANGE, PART, PART, PART, ACCENT, ACCENT, ACCENT]
    for page in ["index.html", "species.html", "method.html"]:      # pages.py puts the header on every page
        assert svg in (ROOT / "site" / page).read_text(), page


def test_the_favicon_is_three_bars_with_the_top_layer_light_green_and_orange():
    assert fills((ROOT / "site" / "favicon.svg").read_text()) == [PART, ORANGE, ACCENT, ACCENT]


def test_the_home_screen_icon_is_180_pixels():
    png = (ROOT / "site" / "apple-touch-icon.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (180, 180)
    assert fills((ROOT / "site-parts" / "apple-touch-icon.svg").read_text())[0] == ACCENT    # its source
