#!/bin/bash
# 并起前后端开发服务
cd "$(dirname "$0")/.." || exit 1

(cd backend && setsid nohup python3 -m uvicorn app.main:app --reload --port 8300 > /tmp/tsh_api.log 2>&1 < /dev/null &) &&
(cd frontend && pnpm dev > /tmp/tsh_vite.log 2>&1 &) &&
echo "API: http://localhost:8300/docs | Vite: http://localhost:5173"
