"""scripts/report_failure.sh: one open issue per failing workflow (a fake gh on PATH records its calls)."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "report_failure.sh"


def run(tmp_path, open_issue):
    log = tmp_path / "calls"
    gh = tmp_path / "gh"
    gh.write_text(f'#!/usr/bin/env bash\necho "$@" >> {log}\n'
                  f'[ "$1 $2" = "issue list" ] && echo "{open_issue}"\nexit 0\n')
    gh.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    subprocess.run(["bash", str(SCRIPT), "Weekly build", "https://x/runs/1"], env=env, check=True)
    return log.read_text().splitlines()


def test_opens_an_issue_when_none_is_open(tmp_path):
    calls = run(tmp_path, "")
    assert calls[-1].startswith("issue create --title Weekly build failed (")


def test_comments_on_the_open_issue(tmp_path):
    calls = run(tmp_path, "7")
    assert calls[-1] == "issue comment 7 --body Failed again on " + calls[-1].split("on ", 1)[1]
    assert not any(c.startswith("issue create") for c in calls)
