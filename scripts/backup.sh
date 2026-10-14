#!/usr/bin/env bash
set -Eeuo pipefail

DATA_DIR="${CADDY_MANAGER_DATA:-/var/lib/caddy-manager}"
ENV_FILE="${CADDY_MANAGER_ENV_FILE:-/etc/caddy-manager.env}"
BACKUP_DIR="${CADDY_MANAGER_BACKUP_DIR:-/var/backups/caddy-manager}"
timestamp="$(date +%Y%m%d-%H%M%S)"
archive="$BACKUP_DIR/caddy-manager-$timestamp.tar.gz"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行。" >&2
  exit 1
fi
mkdir -p "$BACKUP_DIR"
tar -czf "$archive" -C / "$DATA_DIR" "${ENV_FILE#/}"
echo "$archive"
