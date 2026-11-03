#!/usr/bin/env bash
# One open issue per failing workflow: a failure adds a comment to the open "<what> failed" issue, else opens one.
# Usage: scripts/report_failure.sh "<what>" <run url>   (needs GH_TOKEN; called by the workflows on failure)
set -euo pipefail
what=$1 url=$2 day=$(date -u +%Y-%m-%d)
n=$(gh issue list --state open --search "\"$what failed\" in:title" --json number,title \
      --jq "[.[] | select(.title | startswith(\"$what failed\"))][0].number // empty")
if [ -n "$n" ]; then
  gh issue comment "$n" --body "Failed again on $day: $url"
else
  gh issue create --title "$what failed ($day)" --body "The workflow failed: $url"
fi
