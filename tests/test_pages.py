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
    assert "aria-current" not in pages.render(pages.part("header"), "404")


def test_render_is_idempotent():
    text = (pages.SITE / "species.html").read_text()
    once = pages.render(text, "species")
    assert pages.render(once, "species") == once
