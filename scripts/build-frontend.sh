#!/usr/bin/env bash
# Production-style build of the React app into frontend/dist (then served by FastAPI).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
exec npm run build
