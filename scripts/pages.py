"""Fill the shared parts of every page from site-parts/ (head links, header with the nav, footer, noscript), and
version every script and stylesheet: each reference in a page and each import between scripts carries ?v=<version>,
a hash of the file's contents and of the versions of the modules it imports. A browser can then never mix an old
cached module with a new page (Safari keeps modules in memory across reloads), and assets can be cached for a year.

A page marks each part as <!-- part:NAME --> ... <!-- /part:NAME -->; the text between the marks is replaced
with site-parts/NAME.html. The pages stay plain HTML (no build step on Cloudflare Pages, readable without
JavaScript). Safe to run again: a page in sync does not change. tests/test_pages.py checks that every page is.

Usage: .venv/bin/python scripts/pages.py
"""

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PARTS = ROOT / "site-parts"
ASSETS = SITE / "assets"
PAGES = sorted(p for p in SITE.glob("*.html") if not p.name.startswith("google"))  # not the search-console token
NAV = [("/", "Explore", "index"), ("/changes", "Changes", "changes"), ("/shortlist", "Shortlists", "shortlist"),
       ("/fix", "Records to fix", "fix"), ("/method", "Sources and method", "method")]
MARK = re.compile(r"(<!-- part:(\w+) -->\n).*?(<!-- /part:\2 -->)", re.S)
IMPORT = re.compile(r"""(\b(?:from|import)\s+)(['"])\./([\w-]+\.js)(?:\?v=\w+)?\2""")   # an import between scripts
REF = re.compile(r"""(["'])/assets/([\w-]+\.(?:js|css))(?:\?v=\w+)?\1""")              # a reference in a page


def part(name):
    return (PARTS / f"{name}.html").read_text()


def nav(page):
    current = ' aria-current="page"'
    return "\n".join(f'      <a href="{href}"{current if p == page else ""}>{text}</a>' for href, text, p in NAV)


def versions(folder=ASSETS):
    """{file name: version} for the scripts and stylesheets of a folder. The version hashes the file without its
    import versions, then the versions of the modules it imports, so a changed module changes every module above it."""
    files = {p.name: p.read_text() for p in folder.iterdir() if p.suffix in (".js", ".css")}
    done = {}

    def version(name, path=()):
        if name not in done:
            text = files[name]
            h = hashlib.sha256(IMPORT.sub(lambda m: f"{m[1]}{m[2]}./{m[3]}{m[2]}", text).encode())
            for dep in sorted({m[3] for m in IMPORT.finditer(text)}):
                if dep in files and dep not in path:
                    h.update(version(dep, (*path, name)).encode())
            done[name] = h.hexdigest()[:10]
        return done[name]

    return {name: version(name) for name in files}


def stamp_js(text, ver):
    """A script's imports of other scripts with their versions."""
    return IMPORT.sub(lambda m: f"{m[1]}{m[2]}./{m[3]}?v={ver[m[3]]}{m[2]}" if m[3] in ver else m[0], text)


def stamp_html(text, ver):
    """A page's references to scripts and stylesheets with their versions."""
    return REF.sub(lambda m: f"{m[1]}/assets/{m[2]}?v={ver[m[2]]}{m[1]}" if m[2] in ver else m[0], text)


def render(text, page, ver=None):
    """The page text with every marked part filled; `page` is the file stem (index, species, ...)."""
    def fill(m):
        return m.group(1) + part(m.group(2)).replace("{{nav}}", nav(page)) + m.group(3)
    return stamp_html(MARK.sub(fill, text).replace("{{nav}}", nav(page)), ver or versions())


def main():
    ver = versions()
    for path in sorted(ASSETS.glob("*.js")):
        text = path.read_text()
        new = stamp_js(text, ver)
        if new != text:
            path.write_text(new)
            print(f"updated {path.relative_to(ROOT)}", flush=True)
    for path in PAGES:
        text = path.read_text()
        new = render(text, path.stem, ver)
        if new != text:
            path.write_text(new)
            print(f"updated {path.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
