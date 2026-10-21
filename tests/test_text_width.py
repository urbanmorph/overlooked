"""Text spans its container: no width cap and no early line breaks on text (owner's rule, 21 October 2026).
Only the page frame (.wrap), controls and small chips may have a max-width."""

import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
MAY_CAP = {".wrap", ".tip", "label.f", "label.f select", ".search", ".tag"}


def css_rules():
    css = re.sub(r"/\*.*?\*/", "", (SITE / "assets" / "style.css").read_text(), flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def test_css_caps_the_width_of_no_text():
    capped = [sel.strip() for sel, body in css_rules() if re.search(r"(?<![-\w])max-width\s*:", body)]
    assert [s for s in capped if s not in MAY_CAP] == []


def test_css_does_not_break_lines_early():
    assert [sel.strip() for sel, body in css_rules() if re.search(r"text-wrap\s*:\s*(balance|pretty)", body)] == []


def test_pages_cap_no_text_inline():
    bad = []
    for page in sorted(SITE.glob("*.html")):
        for tag, style in re.findall(r"<(\w+)[^>]*\sstyle=\"([^\"]*)\"", page.read_text()):
            if "max-width" in style and tag not in {"select", "input"}:
                bad.append(f"{page.name}: <{tag} style=\"{style}\">")
    assert bad == []
