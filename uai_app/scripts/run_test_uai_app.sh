#!/bin/bash
# run_test_uai_app.sh — launch an ISOLATED, OFFSCREEN UAI test instance.
#
# Why this exists: UAI is overwhelmingly a *reader* of the shared backend, so a
# second instance is safe to run alongside the user's live app EXCEPT for the two
# files UAI autonomously *writes*:
#     ai_general/data/app_state.json   (tabs, active tab, UI prefs)
#     ai_general/data/containers.json  (folder tree + its change-signal)
# Sharing those is what caused the 2026-06-20 "controlling one bleeds to the other"
# tab bleed-over. This script redirects BOTH to an isolated dir via the env-var
# overrides the app already supports, renders OFF-SCREEN so it never disturbs the
# user's display, and uses a SEPARATE CDP port so you can drive it independently.
#
# It does NOT isolate domain writes (comms.send, brief creation) — those only fire
# on explicit action, so DO NOT actively drive mini-chats / brief-create in a test.
# A passive render-verify never touches them.
#
# Reads (sessions, projects, todos, comms, transcripts) still come from the real
# AI_ROOT — that's intentional and safe; the app only reflects them.
#
# Usage:
#   ./run_test_uai_app.sh [--port N] [--dir PATH] [--reseed] [--fresh]
#     --port N     CDP/remote-debugging port for the test instance (default 9333;
#                  the user's live app uses 9226 — keep them different)
#     --dir PATH   isolated data dir (default ${TMPDIR:-/tmp}/uai_test)
#     --reseed     re-copy containers.json (folders) from the real AI_ROOT
#     --fresh      wipe the isolated dir first (start with empty UI state)
#     --mirror     ALSO seed the real app_state.json (your open tabs).
#                  WARNING: that opens your real session tabs, which ATTACH LIVE
#                  TMUX terminals — a form of interference + it hangs the offscreen
#                  renderer. Default is EMPTY app_state (no tabs, no attach). Only
#                  use --mirror knowingly, e.g. to eyeball your real workspace.
#
# After launch, inspect/drive via CDP at  http://localhost:<port>/json
# To render-verify a project view: launch (empty), then open a single PROJECT tab
# via CDP (project tabs have no terminal, so they're attach-free and safe).
set -euo pipefail

PORT=9333
TEST_DIR="${TMPDIR:-/tmp}/uai_test"
RESEED=0
FRESH=0
MIRROR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port)   PORT="$2"; shift 2 ;;
    --dir)    TEST_DIR="$2"; shift 2 ;;
    --reseed) RESEED=1; shift ;;
    --fresh)  FRESH=1; shift ;;
    --mirror) MIRROR=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "[test-uai] unknown arg: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AI_ROOT_REAL="${AI_ROOT_MAIN:-${AI_ROOT:-$HOME/AI/ai_root}}"
REAL_DATA="$AI_ROOT_REAL/ai_general/data"
REAL_APP_STATE="$REAL_DATA/app_state.json"
REAL_CONTAINERS="$REAL_DATA/containers.json"

TEST_APP_STATE="$TEST_DIR/app_state.json"
TEST_CONTAINERS="$TEST_DIR/containers.json"

# Guard: the user's live app uses 9226; never collide with it.
if [ "$PORT" = "9226" ]; then
  echo "[test-uai] refusing port 9226 — that's the live app's CDP port. Pick another." >&2
  exit 2
fi

if [ "$FRESH" = "1" ] && [ -d "$TEST_DIR" ]; then
  echo "[test-uai] --fresh: wiping $TEST_DIR"
  rm -rf "$TEST_DIR"
fi
mkdir "$TEST_DIR" 2>/dev/null || true

seed() { # $1 real  $2 test
  if [ ! -f "$2" ] || [ "$RESEED" = "1" ]; then
    if [ -f "$1" ]; then cp "$1" "$2" && echo "[test-uai] seeded $(basename "$2") from real"; \
    else echo "[test-uai] (no real $(basename "$1") to seed; starting empty)"; fi
  fi
}
seed "$REAL_CONTAINERS" "$TEST_CONTAINERS"   # folders — harmless, isolated copy
if [ "$MIRROR" = "1" ]; then
  echo "[test-uai] --mirror: seeding real app_state.json — WARNING: opens your real"
  echo "          tabs, incl. SESSION tabs that ATTACH LIVE TMUX. Knowingly only."
  seed "$REAL_APP_STATE" "$TEST_APP_STATE"
else
  # Empty app_state ⇒ no auto-opened tabs ⇒ no live-terminal attach. Open a
  # project tab via CDP after boot to render-verify (project tabs are attach-free).
  rm -f "$TEST_APP_STATE"
  echo "[test-uai] app_state: EMPTY (no auto tabs, no terminal attach). --mirror to override."
fi

cat <<EOF
[test-uai] ── isolated offscreen UAI test instance ──────────────────────
  CDP port        : $PORT            (live app stays on 9226)
  offscreen       : yes (UAI_TEST_OFFSCREEN=1 — renders at -4000,-4000)
  isolated dir    : $TEST_DIR
  app_state.json  : $TEST_APP_STATE   (writes isolated — no tab bleed-over)
  containers.json : $TEST_CONTAINERS  (folder writes isolated)
  reads from      : $AI_ROOT_REAL (real backend — reflect-only)
  inspect via     : http://localhost:$PORT/json
  NOTE: don't actively drive mini-chats/brief-create (those hit shared comms).
────────────────────────────────────────────────────────────────────────
EOF

export UAI_TEST_OFFSCREEN=1
export UAI_DEBUG_PORT="$PORT"
export UAI_APP_STATE_PATH="$TEST_APP_STATE"
export UAI_CONTAINERS_PATH="$TEST_CONTAINERS"
export UAI_ALLOW_MULTI=1   # harmless; current code has no single-instance lock anyway

exec "$SCRIPT_DIR/start.sh"
