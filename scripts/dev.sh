#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "请先按 docs/DEVELOPMENT.md 创建 .venv 并安装 requirements-dev.txt。" >&2
  exit 1
fi

# Always override inherited server settings; this launcher is local-only.
export CADDY_MANAGER_HOST=127.0.0.1
export CADDY_MANAGER_PORT="${CADDY_MANAGER_DEV_PORT:-17080}"
export CADDY_MANAGER_DATA="$PROJECT_DIR/.local/data"
export CADDYFILE="$CADDY_MANAGER_DATA/Caddyfile"
export CADDY_MANAGER_SKIP_CADDY=1
umask 077
cd "$PROJECT_DIR"
printf '本地面板：http://127.0.0.1:%s\n测试数据：%s\n已跳过 Caddy 命令、Admin API 和证书连接；按 Ctrl+C 停止。\n' \
  "$CADDY_MANAGER_PORT" "$CADDY_MANAGER_DATA"
exec "$PYTHON" flask_app.py
