#!/usr/bin/env bash
set -Eeuo pipefail

# Bootstrap installer. It is safe to run through:
# bash <(wget -qO- https://raw.githubusercontent.com/weidaye1122/CaddyManager/main/install.sh)

REPO_URL="${CADDY_MANAGER_REPO:-https://github.com/weidaye1122/CaddyManager}"
REF="${CADDY_MANAGER_VERSION:-main}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
if [[ -f "${SCRIPT_DIR:-}/scripts/install.sh" && -f "${SCRIPT_DIR:-}/flask_app.py" ]]; then
  bash "$SCRIPT_DIR/scripts/install.sh" "$@"
  exit $?
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行：bash <(wget -qO- https://raw.githubusercontent.com/weidaye1122/CaddyManager/main/install.sh)" >&2
  exit 1
fi

if command -v wget >/dev/null 2>&1; then
  download() { wget -qO "$2" "$1"; }
elif command -v curl >/dev/null 2>&1; then
  download() { curl -fsSL "$1" -o "$2"; }
else
  echo "需要 wget 或 curl。" >&2
  exit 1
fi

tmp_dir="$(mktemp -d -t caddy-manager-install.XXXXXX)"
trap 'rm -rf "$tmp_dir"' EXIT
archive="$tmp_dir/source.tar.gz"

if [[ "$REF" == v* || "$REF" == [0-9]* ]]; then
  archive_url="$REPO_URL/archive/refs/tags/$REF.tar.gz"
else
  archive_url="$REPO_URL/archive/refs/heads/$REF.tar.gz"
fi

echo "下载 Caddy Manager $REF ..."
download "$archive_url" "$archive"
tar -xzf "$archive" -C "$tmp_dir"
source_dir="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d -print -quit)"

if [[ -z "$source_dir" || ! -f "$source_dir/scripts/install.sh" ]]; then
  echo "安装包内容不完整。" >&2
  exit 1
fi

bash "$source_dir/scripts/install.sh" "$@"
