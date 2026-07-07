#!/bin/bash
# UAI Packaged Build Smoke Test — Quality Gate 1D.3
#
# Verifies the Electron app packages and launches successfully.
# Run from the project root: bash scripts/smoke-test.sh
#
# Gates tested:
#   S1: Package builds (electron-forge package exits 0)
#   S2: App binary exists
#   S3: App launches and stays running for 5 seconds
#   S4: No crash in first 5 seconds

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$PROJECT_DIR/src"
PASS=0
FAIL=0

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }

echo "═══════════════════════════════════════════════════"
echo "  UAI Smoke Test — Packaged Build Verification"
echo "═══════════════════════════════════════════════════"
echo ""

# ── S1: Package builds ────────────────────────────────────────────────
echo "Gate S1: Building packaged app..."
cd "$SRC_DIR"
if npm run package 2>&1 | tail -5; then
  pass "S1: Package built successfully"
else
  fail "S1: Package build failed"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

# ── S2: App binary exists ─────────────────────────────────────────────
echo ""
echo "Gate S2: Checking for app binary..."
APP_PATH=$(find "$SRC_DIR/out" -name "*.app" -type d 2>/dev/null | head -1)
if [ -n "$APP_PATH" ] && [ -d "$APP_PATH" ]; then
  pass "S2: App binary found at $APP_PATH"
else
  fail "S2: No .app bundle found in out/"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

# ── S3 + S4: App launches and stays running ───────────────────────────
echo ""
echo "Gate S3/S4: Launching app for 5 seconds..."
EXEC_PATH="$APP_PATH/Contents/MacOS/$(ls "$APP_PATH/Contents/MacOS/" | head -1)"

if [ ! -x "$EXEC_PATH" ]; then
  fail "S3: Executable not found or not executable"
  echo ""
  echo "Results: $PASS passed, $FAIL failed"
  exit 1
fi

# Launch in background, wait 5 seconds, check if still running
"$EXEC_PATH" &>/dev/null &
APP_PID=$!
sleep 5

if kill -0 "$APP_PID" 2>/dev/null; then
  pass "S3: App launched and stayed running for 5 seconds"
  pass "S4: No crash detected (PID $APP_PID still alive)"
  # Clean up — send SIGTERM
  kill "$APP_PID" 2>/dev/null || true
  wait "$APP_PID" 2>/dev/null || true
else
  # Process died — check exit code
  wait "$APP_PID" 2>/dev/null
  EXIT_CODE=$?
  fail "S3: App exited within 5 seconds (exit code: $EXIT_CODE)"
  fail "S4: Crash detected"
fi

# ── Summary ───────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
