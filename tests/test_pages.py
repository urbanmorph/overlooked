"""The pages share their head, header and footer from site parts (scripts/pages.py). Run that script after
changing a part; this test fails when a page is not in sync."""

import importlib.util
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("pages", Path(__file__).resolve().parent.parent / "scripts" / "pages.py")
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)


def test_every_page_is_in_sync_with_the_parts():
    for path in pages.PAGES:
        text = path.read_text()
        assert pages.render(text, path.stem) == text, f"{path.name}: run .venv/bin/python scripts/pages.py"


def test_every_page_has_the_header_and_the_footer_with_the_credits():
    for path in pages.PAGES:
        text = path.read_text()
        footer = re.search(r"<footer>.*?</footer>", text, re.S).group(0)
        assert "Botanical Survey of India" in footer and "Zoological Survey of India" in footer, path.name
        assert "CC BY 4.0, Sathya Sankaran" in footer, path.name
        assert text.count('class="top"') == 1, path.name


def test_the_nav_marks_the_current_page():
    assert 'href="/" aria-current="page"' in pages.render(pages.part("header"), "index")
    assert 'href="/changes" aria-current="page"' in pages.render(pages.part("header"), "changes")
    assert 'href="/shortlist" aria-current="page"' in pages.render(pages.part("header"), "shortlist")
    assert "aria-current" not in pages.render(pages.part("header"), "404")


def test_render_is_idempotent():
    text = (pages.SITE / "species.html").read_text()
    once = pages.render(text, "species")
    assert pages.render(once, "species") == once


# ---------------------------------------------------------------- versioned assets

def test_every_reference_to_an_asset_carries_the_version_of_its_contents():
    """A browser that keeps an old copy of one module must not mix it with a new page: every page and every import
    names each asset with ?v=<version>, so a new deploy changes the address."""
    ver = pages.versions()
    for path in pages.PAGES:
        refs = re.findall(r"/assets/([\w-]+\.(?:js|css))(\?v=\w+)?", path.read_text())
        assert refs, path.name
        for name, v in refs:
            assert v == f"?v={ver[name]}", f"{path.name}: {name}{v} (run scripts/pages.py)"
    for js in pages.ASSETS.glob("*.js"):
        for name, v in re.findall(r"""(?:from|import)\s+['"]\./([\w-]+\.js)(\?v=\w+)?['"]""", js.read_text()):
            assert v == f"?v={ver[name]}", f"{js.name} imports {name}{v} (run scripts/pages.py)"


def test_a_changed_module_changes_the_version_of_every_module_above_it(tmp_path):
    (tmp_path / "c.js").write_text("export const c = 1;\n")
    (tmp_path / "b.js").write_text("import { c } from './c.js';\nexport const b = c;\n")
    (tmp_path / "a.js").write_text("import { b } from './b.js';\nexport const a = b;\n")
    (tmp_path / "s.css").write_text("body { margin: 0 }\n")
    before = pages.versions(tmp_path)
    (tmp_path / "c.js").write_text("export const c = 2;\n")
    after = pages.versions(tmp_path)
    assert all(before[n] != after[n] for n in ("a.js", "b.js", "c.js")) and before["s.css"] == after["s.css"]
    # Stamping the imports changes no version: a second run of the script changes nothing.
    stamped = pages.stamp_js((tmp_path / "a.js").read_text(), after)
    assert f"'./b.js?v={after['b.js']}'" in stamped
    (tmp_path / "a.js").write_text(stamped)
    assert pages.versions(tmp_path) == after
    assert pages.stamp_js(stamped, after) == stamped


def test_assets_are_cached_for_a_year_as_their_addresses_change_with_their_contents():
    headers = (pages.SITE / "_headers").read_text()
    assert "/assets/*\n  Cache-Control: public, max-age=31536000, immutable" in headers


def test_the_nav_has_the_mcp_page_and_a_menu_button_for_small_screens():
    """The MCP page is in the nav. Under 900 px a Menu button opens the nav (an inline script in the header part: it
    works on every page, 404 too); with no JavaScript the button stays hidden and the nav is the row it was."""
    header = pages.render(pages.part("header"), "mcp")
    assert 'href="/mcp" aria-current="page"' in header
    assert re.search(r'<button[^>]+class="menu"[^>]+aria-controls="nav"[^>]+aria-expanded="false"[^>]+hidden', header)
    assert '<nav class="main" id="nav"' in header
    assert "<script>" in header and "aria-expanded" in header


def test_the_mcp_page():
    text = (pages.SITE / "mcp.html").read_text().replace("&amp;", "&")
    for s in ("https://yellide.com/mcp", "claude mcp add --transport http --scope user", '"mcpServers"', "Add custom connector",
              "cursor://anysphere.cursor-deeplink/mcp/install?name=yellide&config=", "https://vscode.dev/redirect/mcp/install?name=yellide",
              "codex mcp add yellide --url", "[mcp_servers.yellide]", "serverUrl",
              "find_species", "get_species", "count_species", "list_species", "new_species", "yellide://regions", "curl"):
        assert s in text, s
    assert not re.search(r"missing|lost|extinct|quiet|—", re.sub(r"<[^>]+>", " ", text), re.IGNORECASE)
    assert "/mcp</loc>" in (pages.SITE / "sitemap-pages.xml").read_text()


def test_the_one_click_install_links_carry_the_server_address():
    import base64
    import json
    from urllib.parse import parse_qs, unquote, urlparse
    text = (pages.SITE / "mcp.html").read_text().replace("&amp;", "&")
    cursor = re.search(r'href="(cursor://[^"]+)"', text).group(1)
    vscode = re.search(r'href="(https://vscode\.dev/redirect/mcp/install[^"]+)"', text).group(1)
    url = "https://yellide.com/mcp"
    assert json.loads(base64.b64decode(unquote(parse_qs(urlparse(cursor).query)["config"][0]))) == {"url": url}
    assert json.loads(parse_qs(urlparse(vscode).query)["config"][0]) == {"type": "http", "url": url}


def test_every_page_has_canonical_and_share_tags_from_its_own_title_and_description():
    """Search engines and link previews (LinkedIn, X, WhatsApp): a canonical URL, Open Graph and Twitter tags, filled
    from the page's own <title> and description. The species page has no canonical (its address carries ?key=); the
    404 page asks not to be indexed."""
    for path in pages.PAGES:
        text = path.read_text()
        title = re.search(r"<title>(.*?)</title>", text).group(1)
        desc = re.search(r'<meta name="description" content="([^"]*)"', text).group(1)
        assert f'<meta property="og:title" content="{title}">' in text, path.name
        assert f'<meta property="og:description" content="{desc}">' in text, path.name
        assert '<meta property="og:image" content="https://yellide.com/og.png">' in text, path.name
        assert '<meta name="twitter:card" content="summary_large_image">' in text, path.name
        url = pages.page_url(path.stem)
        if path.stem in ("species", "404"):
            assert 'rel="canonical"' not in text, path.name
        else:
            assert f'<link rel="canonical" href="{url}">' in text and f'<meta property="og:url" content="{url}">' in text, path.name
    assert '<meta name="robots" content="noindex">' in (pages.SITE / "404.html").read_text()
    assert pages.page_url("index") == "https://yellide.com/" and pages.page_url("mcp").endswith("/mcp")
    assert (pages.SITE / "og.png").exists()


def test_the_mcp_page_shows_places_through_bharatlas_with_its_limits():
    text = (pages.SITE / "mcp.html").read_text()
    assert 'id="places"' in text and "bharatlas" in text and "locate" in text
    for s in ("recorded in", "not a field guide", "Sensitive locations", "forest department"):
        assert s.lower() in text.lower(), s


def test_the_home_page_description_names_the_district():
    """The smallest area the site shows is a district: the description search engines and link previews show says so."""
    text = (pages.SITE / "index.html").read_text()
    desc = re.search(r'<meta name="description" content="([^"]*)"', text).group(1)
    assert "district" in desc


def test_the_species_page_holds_the_space_its_script_fills_so_nothing_jumps():
    # Field CLS was 0.67 on species pages (Nov 2026): the pyramid, photo and gap note arrived empty and pushed the
    # map and records down about 400 px once species.js filled them.
    site = Path(__file__).resolve().parent.parent / "site"
    html = (site / "species.html").read_text()
    pyr = re.search(r'<div class="pyr" id="pyr">(.*?)</div>\s*<div class="legend" id="pyrkey">', html, re.S)[1]
    assert [len(re.findall(r'class="blk sk"', lvl)) for lvl in re.findall(r'<div class="lvl l\d">(.*?)</div>', pyr)] == [4, 2, 1]
    assert re.search(r'<div class="legend" id="pyrkey">\s*<span class="lbl">', html)
    assert re.search(r'id="gapnote"[^>]*>[^<]+</div>', html)
    css = (site / "assets" / "style.css").read_text()
    assert ".sp-photo:empty { display: none }" not in css
    assert re.search(r"\.sp-photo:empty \{[^}]*aspect-ratio", css)


def test_the_species_page_shows_its_lower_part_only_once_drawn():
    # A reader who scrolls before the data comes (or a bot that jumps to the end) saw the partner and relative cards
    # fill in on screen and push the rest down: 0.5 layout shift in a throttled test (24 Nov 2026). The page now holds
    # everything under the map, and the footer, back until species.js has drawn it, so it appears and does not move.
    site = Path(__file__).resolve().parent.parent / "site"
    html = (site / "species.html").read_text()
    head = html.split("</head>", 1)[0]
    assert "classList.add('sp-loading')" in head
    css = (site / "assets" / "style.css").read_text()
    assert ".sp-loading #main > .sp-two ~ *, .sp-loading footer { display: none }" in css
    js = (site / "assets" / "species.js").read_text()
    assert re.search(r"\} finally \{\s*document\.documentElement\.classList\.remove\('sp-loading'\)", js)
    # the relatives and the shortlist note come before the lower part shows, not after
    assert re.search(r"await Promise\.all\(\[rel, short\]\)", js)


def test_the_species_page_holds_the_lines_its_script_adds_at_the_top():
    # The pills, the pyramid key's bar line, the gap note and the map's first line came after load and moved the page
    # (about 200 px on a phone, 24 Nov 2026).
    site = Path(__file__).resolve().parent.parent / "site"
    html = (site / "species.html").read_text()
    key = re.search(r'<div class="legend" id="pyrkey">(.*?)</div>', html, re.DOTALL)[1]
    assert key.count('class="lbl"') == 5 and "Bar:" in key
    css = (site / "assets" / "style.css").read_text()
    assert re.search(r"\.sp-pills:empty \{ min-height: 31px \}", css)
    assert re.search(r"#where:empty \{ min-height: 1lh \}", css)
    assert ".sp-map #legend:empty { min-height: 47px }" in css
    phone = re.search(r"@media \(max-width: 600px\) \{ /\* species page while loading \*/(.*?)\n\}", css, re.DOTALL)[1]
    for rule in (".sp-pills:empty { min-height: 70px }", ".sp-gapnote { min-height: calc(3lh + 24px) }",
                 ".blk.sk { min-height: 98px }", "#where:empty { min-height: 2lh }",
                 ".sp-map #legend:empty { min-height: 75px }"):
        assert rule in phone, rule
    js = (site / "assets" / "species.js").read_text()
    assert "`Bar: not measured for" in js   # a species with no shares keeps the line
