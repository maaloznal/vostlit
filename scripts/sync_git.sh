#!/usr/bin/env bash
# Sync the local vostlit-research repo with GitHub.
#
# Usage:
#   GIT_TOKEN=ghp_xxx ./scripts/sync_git.sh "commit message"
#
# Security:
#   - The token is read from the GIT_TOKEN env var ONLY.
#   - It is never written to any file, never stored in .git/config, never
#     logged. The remote 'origin' is kept as the clean HTTPS URL.
#   - The .gitignore defensively excludes any file matching *token*/*secret*.
#
# If GIT_TOKEN is not set, the script falls back to whatever credential
# helper your git is configured with (so it also works on a developer
# machine with a credential store).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REMOTE_URL="https://github.com/maaloznal/vostlit.git"
REMOTE_NAME="origin"

# ensure remote exists with the CLEAN url (no token)
if ! git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
  git remote add "$REMOTE_NAME" "$REMOTE_URL"
else
  git remote set-url "$REMOTE_NAME" "$REMOTE_URL"
fi

MSG="${1:-sync: update vostlit-research}"

# stage everything (respecting .gitignore)
git add -A

# only commit if there is something to commit
if git diff --cached --quiet; then
  echo "nothing to commit; working tree clean."
else
  git commit -m "$MSG"
fi

# push using the token from env (via an inline credential helper that does
# NOT persist). If GIT_TOKEN is unset, fall back to normal auth.
if [ -n "${GIT_TOKEN:-}" ]; then
  git -c credential.helper='!f() { echo "username=x-access-token"; echo "password=$GIT_TOKEN"; }; f' push "$REMOTE_NAME" main
else
  git push "$REMOTE_NAME" main
fi

echo "synced with $REMOTE_URL"
