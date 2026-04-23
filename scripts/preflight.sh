#!/usr/bin/env bash
#
# Release-readiness gauntlet. ~5-6 minutes.
#
# Runs everything the pre-push hook runs (import, wheel install smoke)
# plus the full pytest suite. Use before tagging a
# release:
#     ./scripts/preflight.sh && git push origin master
#     # if green: git tag vX.Y.Z && git push origin vX.Y.Z
#
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

cyan=$'\033[36m'; green=$'\033[32m'; red=$'\033[31m'; off=$'\033[0m'
say()  { printf "\n%s==>%s %s\n" "$cyan" "$off" "$1"; }
fail() { printf "%s✗%s %s\n" "$red" "$off" "$1" >&2; exit 1; }

# Delegate fast checks to the pre-push hook — single source of truth.
say "fast checks (via .githooks/pre-push)"
./.githooks/pre-push || fail "pre-push checks failed"

say "full pytest suite (~5 min)"
python -m pytest tests/ -q || fail "pytest failed"

printf "\n%s✓ preflight clean%s — safe to push and tag\n" "$green" "$off"
