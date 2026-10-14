#!/usr/bin/env bash
set -Eeuo pipefail

DATA_DIR="${CADDY_MANAGER_DATA:-/var/lib/caddy-manager}"
ENV_FILE="${CADDY_MANAGER_ENV_FILE:-/etc/caddy-manager.env}"
SERVICE_NAME="caddy-manager.service"
CADDY_DROPIN="/etc/systemd/system/caddy.service.d/caddy-manager.conf"
BACKUP_DIR="$(cat "$DATA_DIR/.last-install-backup" 2>/dev/null || true)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行。" >&2
  exit 1
fi

systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/$SERVICE_NAME" "$CADDY_DROPIN"
if [[ -n "$BACKUP_DIR" && -f "$BACKUP_DIR/Caddyfile.before-manager" ]]; then
  cp -a "$BACKUP_DIR/Caddyfile.before-manager" /etc/caddy/Caddyfile
fi
systemctl daemon-reload
systemctl restart caddy
rm -f "$ENV_FILE"
echo "面板已卸载，Caddy 已恢复。运行数据保留在：$DATA_DIR"
echo "如需删除运行数据，请先确认后手动删除。"
