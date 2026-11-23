"""robots.txt: open to people's search and to agents answering questions, the open data under /data/ (named in
llms.txt) included; closed to AI training and to SEO backlink crawlers, which give nothing back (23 Nov 2026). The
Cloudflare zone blocks the same crawlers for those that ignore robots.txt."""

from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
TRAINING = ["GPTBot", "ClaudeBot", "CCBot", "Google-Extended", "Applebot-Extended", "meta-externalagent", "Amazonbot", "Bytespider"]
BACKLINKS = ["AhrefsBot", "SemrushBot", "MJ12bot", "DataForSeoBot"]
ANSWERS = ["Googlebot", "Bingbot", "Applebot", "OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User",
           "PerplexityBot", "Perplexity-User", "ExaSearchBot"]


def groups():
    """{user agent (lower case): [(field, value)]}, a group per run of User-agent lines and the rules after them."""
    out, agents, rules = {}, [], None
    for line in (SITE / "robots.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (s.strip() for s in line.split(":", 1))
        if field.lower() == "user-agent":
            if rules is not None:
                agents, rules = [], None
            agents.append(value.lower())
        elif field.lower() in ("allow", "disallow", "content-signal"):
            if rules is None:
                rules = []
                for a in agents:
                    out[a] = rules
            rules.append((field.lower(), value))
    return out


def closed(rules, path):
    return any(f == "disallow" and v and path.startswith(v) for f, v in rules)


def test_everyone_else_may_read_the_site_and_the_data():
    g = groups()
    assert not closed(g["*"], "/") and not closed(g["*"], "/data/")
    assert "/data/" in (SITE / "llms.txt").read_text()


def test_training_and_backlink_crawlers_are_closed_out():
    g = groups()
    for a in TRAINING + BACKLINKS:
        assert closed(g[a.lower()], "/species/x"), a


def test_search_and_answer_crawlers_are_never_named():
    g = groups()
    for a in ANSWERS:
        assert a.lower() not in g, a


def test_the_content_signal_says_search_and_answers_yes_training_no():
    assert ("content-signal", "search=yes, ai-input=yes, ai-train=no") in groups()["*"]
    assert "Sitemap: https://yellide.com/sitemap.xml" in (SITE / "robots.txt").read_text()
