#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$*"
}

ROOT="${EMOS_BACKUP_ROOT:-/share/emostore}"
REPO="${EMOS_BACKUP_REPO:-$ROOT/repo}"
HOST_MAP="${EMOS_BACKUP_HOST_MAP:-}"
PUSH="${EMOS_BACKUP_PUSH:-0}"
REMOTE="${EMOS_BACKUP_GIT_REMOTE:-origin}"
BRANCH="${EMOS_BACKUP_GIT_BRANCH:-main}"
DRY_RUN="${EMOS_BACKUP_DRY_RUN:-0}"

RUNTIME_DIR="$ROOT/runtime"
LOCK_DIR="$RUNTIME_DIR/scan.lock"
mkdir -p "$RUNTIME_DIR"

cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "another backup scan is running, skip"
  exit 0
fi

CMD=(node "$REPO_ROOT/tools/emos_backup_worker.mjs" --root "$ROOT" --repo "$REPO" --commit)

if [[ -n "$HOST_MAP" ]]; then
  CMD+=(--host-map "$HOST_MAP")
fi

if [[ "$DRY_RUN" == "1" ]]; then
  CMD+=(--dry-run)
fi

log "starting backup scan"
log "root=$ROOT repo=$REPO push=$PUSH dry_run=$DRY_RUN"

"${CMD[@]}"

if [[ "$DRY_RUN" == "1" ]]; then
  log "dry run complete, skip git push"
  exit 0
fi

if [[ "$PUSH" != "1" ]]; then
  log "backup scan complete, git push disabled"
  exit 0
fi

if [[ ! -d "$REPO/.git" ]]; then
  log "repo has no .git, skip push"
  exit 0
fi

if ! git -C "$REPO" remote get-url "$REMOTE" >/dev/null 2>&1; then
  log "git remote '$REMOTE' not found, skip push"
  exit 0
fi

if [[ -z "$(git -C "$REPO" status --short)" ]]; then
  log "no pending worktree changes after scan"
fi

log "pushing git history to $REMOTE/$BRANCH"
git -C "$REPO" push "$REMOTE" "$BRANCH"
log "backup scan complete"
