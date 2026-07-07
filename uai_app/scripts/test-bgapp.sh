#!/bin/bash
# Launch UAI app via bgapp.py for background E2E testing.
#
# Usage:
#   ./test-bgapp.sh launch [--port PORT]   # Start UAI in background
#   ./test-bgapp.sh screenshot [--output PATH]
#   ./test-bgapp.sh dom-query <selector>
#   ./test-bgapp.sh dom-click <selector>
#   ./test-bgapp.sh close
#   ./test-bgapp.sh list
#
# Requires: bgapp.py, Hammerspoon with hs.ipc, Accessibility permissions
#
# Note: Use the devTree bgapp.py which is parameterized for app name.
# The main ai_root copy still hardcodes "UnifiedCLI".

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# Use devTree copy (parameterized) over main ai_root copy (hardcoded UnifiedCLI)
BGAPP="$PROJECT_DIR/../../scripts/ui/bgapp.py"
if [ ! -f "$BGAPP" ]; then
  BGAPP="${AI_ROOT:-$HOME/Documents/AI/ai_root}/ai_general/scripts/ui/bgapp.py"
fi

# UAI instance name for bgapp registry
UAI_INSTANCE="uai-test"

case "${1:-}" in
  launch)
    shift
    # Build the app first if needed
    if [ ! -d "$PROJECT_DIR/app/out" ]; then
      echo "Building UAI app..."
      (cd "$PROJECT_DIR/app" && npm run package 2>&1) || {
        echo "ERROR: Build failed"
        exit 1
      }
    fi
    # Find the built .app
    APP_PATH=$(find "$PROJECT_DIR/app/out" -name "*.app" -maxdepth 3 -not -name "Helper*" | head -1)
    if [ -z "$APP_PATH" ]; then
      echo "ERROR: No .app found in app/out/"
      exit 1
    fi
    python3 "$BGAPP" launch "$APP_PATH" --name "$UAI_INSTANCE" "$@"
    ;;
  screenshot)
    shift
    python3 "$BGAPP" screenshot "$UAI_INSTANCE" "$@"
    ;;
  dom-query)
    shift
    python3 "$BGAPP" dom-query "$UAI_INSTANCE" "$@"
    ;;
  dom-click)
    shift
    python3 "$BGAPP" dom-click "$UAI_INSTANCE" "$@"
    ;;
  dom-type)
    shift
    python3 "$BGAPP" dom-type "$UAI_INSTANCE" "$@"
    ;;
  axtree)
    shift
    python3 "$BGAPP" axtree "$UAI_INSTANCE" "$@"
    ;;
  close)
    python3 "$BGAPP" close "$UAI_INSTANCE"
    ;;
  list)
    python3 "$BGAPP" list
    ;;
  *)
    echo "Usage: $0 {launch|screenshot|dom-query|dom-click|dom-type|axtree|close|list}"
    exit 1
    ;;
esac
