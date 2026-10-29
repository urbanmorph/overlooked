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
