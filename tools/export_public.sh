#!/usr/bin/env bash
# Copy the tracked files that are meant to be public into a separate working copy
# with its own history. docs/specs (private design notes) never leaves this repo.
# Usage: tools/export_public.sh <public-working-copy-dir>
set -euo pipefail
src="$(cd "$(dirname "$0")/.." && pwd)"
dst="${1:?public working copy dir}"
mkdir -p "$dst"
cd "$src"
git ls-files | grep -v '^docs/specs/' | while IFS= read -r f; do
  mkdir -p "$dst/$(dirname "$f")"
  cp -p "$f" "$dst/$f"
done
# remove files that were deleted here
cd "$dst"
if [ -d .git ]; then
  git ls-files | while IFS= read -r f; do
    (cd "$src" && git ls-files --error-unmatch "$f" >/dev/null 2>&1) || git rm -q "$f"
  done
fi
echo "exported to $dst"
