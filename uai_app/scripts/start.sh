#!/bin/bash
# Launch UAI app in dev mode (monorepo structure)
#
# electron-forge start has a process management bug that kills the Electron
# child process. This script does the manual equivalent: build main+preload,
# start Vite dev server, launch Electron directly.

APP_DIR="$(cd "$(dirname "$0")/../app" && pwd)"
cd "$APP_DIR" || exit 1

# Build main process and preload
echo "[UAI] Building main + preload..."
npx vite build --config vite.main.config.ts 2>/dev/null
npx vite build --config vite.preload.config.ts 2>/dev/null

# Start Vite renderer dev server
echo "[UAI] Starting Vite dev server..."
npx vite --config vite.renderer.config.ts --port 5173 &
VITE_PID=$!
sleep 2

# Launch Electron with the dev server URL
echo "[UAI] Launching Electron..."
MAIN_WINDOW_VITE_DEV_SERVER_URL="http://localhost:5173" \
MAIN_WINDOW_VITE_NAME="main_window" \
  npx electron .vite/build/index.js "$@"

# Cleanup Vite when Electron exits
kill $VITE_PID 2>/dev/null
