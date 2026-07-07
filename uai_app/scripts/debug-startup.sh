#!/bin/bash
# Debug UAI startup issues
# Run from project root: ./scripts/debug-startup.sh

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
APP="$PROJ/app"

echo "=== TypeScript check ==="
cd "$APP" && npx tsc --noEmit 2>&1 | tail -5

echo ""
echo "=== Vite build check (renderer) ==="
cd "$APP" && npx vite build --config vite.renderer.config.ts --outDir /tmp/uai-debug-build 2>&1 | tail -20

echo ""
echo "=== Vite build check (main) ==="
cd "$APP" && npx vite build --config vite.main.config.ts --outDir /tmp/uai-debug-main 2>&1 | tail -20

echo ""
echo "=== Check imports resolve ==="
cd "$APP" && node -e "
  const path = require('path');
  const alias = {
    '@uai/shared': path.resolve('$PROJ/packages/shared/src'),
    '@uai/renderer-ui': path.resolve('$PROJ/packages/renderer-ui/src'),
  };
  console.log('Alias check:');
  for (const [k,v] of Object.entries(alias)) {
    const exists = require('fs').existsSync(v);
    console.log('  ' + k + ' => ' + v + ' [' + (exists ? 'OK' : 'MISSING') + ']');
  }
" 2>&1

echo ""
echo "=== Launch with ELECTRON_ENABLE_LOGGING ==="
cd "$APP" && ELECTRON_ENABLE_LOGGING=1 npm start 2>&1 &
APP_PID=$!
sleep 20
echo ""
echo "=== Process alive? ==="
kill -0 $APP_PID 2>/dev/null && echo "YES - app is running" || echo "NO - app crashed"
kill $APP_PID 2>/dev/null
