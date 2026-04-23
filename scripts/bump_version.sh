#!/usr/bin/env bash
# Bump pyproject.toml version in an isolated commit so auto-tag can fire.
#
# Why isolated: GITHUB_TOKEN cannot push refs (tags included) on commits that
# modify workflow files. If a version bump lands in the same commit as CI
# changes, the auto-tag job fails with a permission error and the release
# chain stalls. This script enforces the rule by refusing to run when
# workflow files are dirty or staged.
#
# Usage: scripts/bump_version.sh <new-version>
# Example: scripts/bump_version.sh 0.6.8

set -euo pipefail

new_version="${1:-}"
if [ -z "$new_version" ]; then
  echo "usage: $0 <new-version>" >&2
  exit 2
fi

cd "$(git rev-parse --show-toplevel)"

# Reject if workflow files are dirty — the whole point is an isolated bump.
dirty_workflows=$(git status --porcelain .github/workflows/ 2>/dev/null || true)
if [ -n "$dirty_workflows" ]; then
  echo "error: workflow files are modified. Commit or stash workflow changes first." >&2
  echo "$dirty_workflows" >&2
  exit 1
fi

# Reject if anything is already staged — keep the bump commit clean.
staged=$(git diff --cached --name-only)
if [ -n "$staged" ]; then
  echo "error: files already staged. Commit or reset them first." >&2
  echo "$staged" >&2
  exit 1
fi

current=$(grep -E '^version = "' pyproject.toml | head -1 | sed -E 's/version = "(.*)"/\1/')
if [ "$current" = "$new_version" ]; then
  echo "error: pyproject.toml is already at $new_version" >&2
  exit 1
fi

# In-place bump (portable between GNU and BSD sed).
python3 -c "
import pathlib, re
p = pathlib.Path('pyproject.toml')
text = p.read_text()
text = re.sub(r'^version = \".*\"', 'version = \"${new_version}\"', text, count=1, flags=re.M)
p.write_text(text)
"

git add pyproject.toml
git commit -m "Bump version to v${new_version}"

echo ""
echo "Bumped $current -> $new_version. Next:"
echo "  git push              # fires tests -> auto-tag -> publish chain"
