"""Checks before a snapshot is published. Any failure stops the run; nothing is uploaded."""

# A change from the last run larger than this stops the run for a look.
MAX_CHANGE = 0.20
# Outputs a snapshot may lack (built from downloads made before they were added). When present they
# must not be empty, and they are compared with the last run only if the last run has them too.
OPTIONAL = ("unlocated_records",)


def run(summary, manifest, previous_summary=None):
    problems = []
    if summary["ledger_rows"] <= 0:
        problems.append("ledger is empty")
    if summary["districts"] < 1:
        problems.append("no districts in the ledger")
    for k in OPTIONAL:
        if summary.get(k) is not None and summary[k] <= 0:
            problems.append(f"{k} is empty")
    for d in manifest["downloads"]:
        if not d.get("doi"):
            problems.append(f"download {d['key']} has no DOI")
    if previous_summary:
        for k in ("species", "ledger_rows", *OPTIONAL):
            before, now = previous_summary.get(k), summary.get(k)
            if before and now is not None and abs(now - before) / before > MAX_CHANGE:
                problems.append(f"{k} changed from {before:,} to {now:,} (more than {MAX_CHANGE:.0%})")
    return problems
