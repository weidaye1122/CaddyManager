#!/usr/bin/env bash
set -Eeuo pipefail

download() {
  if command -v curl >/dev/null 2>&1; then
    curl -fLsS --retry 2 "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$2" "$1"
  else
    echo "需要 wget 或 curl。" >&2
    return 1
  fi
}

# Separate download checks from root/service operations for isolated tests.
prepare_release() {
  local work_dir="$1"
  local repo_url="${CADDY_MANAGER_REPO:-https://github.com/weidaye1122/CaddyManager}"
  local ref="${CADDY_MANAGER_VERSION:-latest}"
  local base_url archive expected actual version file
  repo_url="${repo_url%/}"
  if [[ "$ref" == latest ]]; then
    base_url="$repo_url/releases/latest/download"
  elif [[ "$ref" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
    base_url="$repo_url/releases/download/$ref"
  else
    echo "版本必须为 latest 或正式标签（例如 v1.0.1）；开发源码请使用 scripts/install.sh。" >&2
    return 1
  fi
  archive="$work_dir/caddy-manager.tar.gz"
  echo "下载 Caddy Manager 正式发布包：$ref"
  if ! download "$base_url/SHA256SUMS" "$work_dir/SHA256SUMS" || \
     ! download "$base_url/caddy-manager.tar.gz" "$archive"; then
    echo "无法取得完整发布包。请确认已发布该版本；不会回退安装 main 或旧标签源码。" >&2
    return 1
  fi
  expected="$(awk '$2 == "caddy-manager.tar.gz" {print $1}' "$work_dir/SHA256SUMS")"
  if [[ ! "$expected" =~ ^[a-f0-9]{64}$ ]]; then
    echo "发布包校验清单无效。" >&2
    return 1
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$archive")"
  elif command -v shasum >/dev/null 2>&1; then
    actual="$(shasum -a 256 "$archive")"
  else
    echo "需要 sha256sum 或 shasum 校验发布包。" >&2
    return 1
  fi
  if [[ "${actual%% *}" != "$expected" ]]; then
    echo "发布包 SHA256 不匹配，已停止安装；如恰逢版本更新，请重新下载。" >&2
    return 1
  fi
  if ! tar -tzf "$archive" | awk '
    $0 !~ /^caddy-manager\// || $0 ~ /(^|\/)\.\.(\/|$)/ {bad=1}
    END {exit bad ? 1 : 0}'; then
    echo "发布包目录结构无效。" >&2
    return 1
  fi
  tar -xzf "$archive" -C "$work_dir"
  for file in VERSION release.json flask_app.py scripts/install.sh scripts/install_metadata.py; do
    if [[ ! -f "$work_dir/caddy-manager/$file" ]]; then
      echo "发布包缺少文件：$file" >&2
      return 1
    fi
  done
  version="$(cat "$work_dir/caddy-manager/VERSION")"
  if [[ ! "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || \
     [[ "$ref" != latest && "$ref" != "v$version" ]]; then
    echo "发布包版本与请求不一致。" >&2
    return 1
  fi
  echo "发布包校验通过：v$version"
}

main() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "请使用 root 执行安装脚本。" >&2
    return 1
  fi
  CADDY_INSTALL_TMP="$(mktemp -d -t caddy-manager-install.XXXXXX)"
  trap 'rm -rf -- "$CADDY_INSTALL_TMP"' EXIT
  prepare_release "$CADDY_INSTALL_TMP"
  bash "$CADDY_INSTALL_TMP/caddy-manager/scripts/install.sh" "$@"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
