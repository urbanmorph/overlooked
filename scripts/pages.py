"""Fill the shared parts of every page from site-parts/ (head links, header with the nav, footer, noscript).

A page marks each part as <!-- part:NAME --> ... <!-- /part:NAME -->; the text between the marks is replaced
with site-parts/NAME.html. The pages stay plain HTML (no build step on Cloudflare Pages, readable without
JavaScript). Safe to run again: a page in sync does not change. tests/test_pages.py checks that every page is.

Usage: .venv/bin/python scripts/pages.py
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PARTS = ROOT / "site-parts"
PAGES = sorted(p for p in SITE.glob("*.html") if not p.name.startswith("google"))  # not the search-console token
NAV = [("/", "Explore", "index"), ("/changes", "Changes", "changes"), ("/method", "Sources and method", "method")]
MARK = re.compile(r"(<!-- part:(\w+) -->\n).*?(<!-- /part:\2 -->)", re.S)


def part(name):
    return (PARTS / f"{name}.html").read_text()


def nav(page):
    current = ' aria-current="page"'
    return "\n".join(f'      <a href="{href}"{current if p == page else ""}>{text}</a>' for href, text, p in NAV)


def render(text, page):
    """The page text with every marked part filled; `page` is the file stem (index, species, ...)."""
    def fill(m):
        return m.group(1) + part(m.group(2)).replace("{{nav}}", nav(page)) + m.group(3)
    return MARK.sub(fill, text).replace("{{nav}}", nav(page))


def main():
    for path in PAGES:
        text = path.read_text()
        new = render(text, path.stem)
        if new != text:
            path.write_text(new)
            print(f"updated {path.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
