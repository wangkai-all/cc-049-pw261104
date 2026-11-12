#!/usr/bin/env bash
# Start the Vite dev server (proxies /api to 127.0.0.1:8000).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
if [ ! -d node_modules ]; then
  npm install --cache "${NPM_CACHE_DIR:-/tmp/npm-cache-sampler}"
fi
exec npm run dev
