"""DuckDB 2 rejects the arrow lambda (x -> ...) in list functions; the pipeline uses lambda x: ... (works on 1.5.6+)."""

import re
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent / "pipeline"
ARROW = re.compile(r"list_\w+\([^()]*,\s*\w+\s*->")


def test_no_arrow_lambdas():
    found = [f"{p.name}: {m.group(0)}" for p in PIPELINE.glob("*.py") for m in ARROW.finditer(p.read_text())]
    assert found == []
