#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/caddy-manager}"
DATA_DIR="${CADDY_MANAGER_DATA:-/var/lib/caddy-manager}"
ENV_FILE="${CADDY_MANAGER_ENV_FILE:-/etc/caddy-manager.env}"
CADDYFILE="${CADDYFILE:-$DATA_DIR/Caddyfile}"
SERVICE_NAME="caddy-manager.service"
CADDY_DROPIN_DIR="/etc/systemd/system/caddy.service.d"
CADDY_DROPIN="$CADDY_DROPIN_DIR/caddy-manager.conf"
BACKUP_ROOT="/var/backups/caddy-manager"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 运行：sudo ./scripts/install.sh" >&2
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1 || ! command -v systemctl >/dev/null 2>&1; then
  echo "当前脚本需要 Debian/Ubuntu 的 apt-get 和 systemd。" >&2
  exit 1
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="$BACKUP_ROOT/$timestamp"
mkdir -p "$backup_dir" "$DATA_DIR" "$APP_DIR"

echo "[1/7] 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates caddy python3-flask python3-waitress

echo "[2/7] 备份现有配置"
[[ -f /etc/caddy/Caddyfile ]] && cp -a /etc/caddy/Caddyfile "$backup_dir/Caddyfile.before-manager"
[[ -f "$CADDY_DROPIN" ]] && cp -a "$CADDY_DROPIN" "$backup_dir/caddy-manager.conf.before-manager"
[[ -f "$ENV_FILE" ]] && cp -a "$ENV_FILE" "$backup_dir/caddy-manager.env.before-manager"
printf '%s\n' "$backup_dir" > "$DATA_DIR/.last-install-backup"

echo "[3/7] 安装面板文件"
if [[ "$SOURCE_DIR" != "$APP_DIR" ]]; then
  mkdir -p "$APP_DIR"
  cp -a "$SOURCE_DIR/flask_app.py" "$SOURCE_DIR/public" "$SOURCE_DIR/requirements-flask.txt" "$APP_DIR/"
  mkdir -p "$APP_DIR/scripts"
  cp -a "$SOURCE_DIR/scripts/backup.sh" "$SOURCE_DIR/scripts/uninstall.sh" "$APP_DIR/scripts/"
fi
chown -R root:root "$APP_DIR"
chmod 755 "$APP_DIR"

echo "[4/7] 初始化 Caddy 数据目录"
if [[ ! -f "$CADDYFILE" ]]; then
  if [[ -f /etc/caddy/Caddyfile ]]; then
    cp -a /etc/caddy/Caddyfile "$CADDYFILE"
  else
    printf '%s\n' '# Caddy Manager will add sites here.' > "$CADDYFILE"
  fi
fi
chown -R caddy:caddy "$DATA_DIR"
chmod 750 "$DATA_DIR"

echo "[5/7] 写入环境和 systemd 服务"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<EOF
CADDY_MANAGER_HOST=127.0.0.1
CADDY_MANAGER_PORT=7080
CADDY_MANAGER_DATA=$DATA_DIR
CADDYFILE=$CADDYFILE
CADDY_BIN=/usr/bin/caddy
CADDY_ADMIN_URL=http://127.0.0.1:2019/config/
EOF
  chmod 600 "$ENV_FILE"
fi
cp "$SOURCE_DIR/deploy/caddy-manager.service" "/etc/systemd/system/$SERVICE_NAME"
mkdir -p "$CADDY_DROPIN_DIR"
cat > "$CADDY_DROPIN" <<EOF
[Service]
ExecStart=
ExecStart=/usr/bin/caddy run --environ --config $CADDYFILE
ExecReload=
ExecReload=/usr/bin/caddy reload --config $CADDYFILE --force
Restart=on-failure
RestartSec=5s
EOF

echo "[6/7] 校验并启动服务"
chown caddy:caddy "$CADDYFILE"
/usr/bin/caddy validate --config "$CADDYFILE" --adapter caddyfile
systemctl daemon-reload
systemctl enable caddy
systemctl restart caddy
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "[7/7] 检查结果"
for service in caddy "$SERVICE_NAME"; do
  systemctl is-enabled --quiet "$service"
  systemctl is-active --quiet "$service"
  case "$(systemctl show --property=Restart --value "$service")" in
    on-failure|always) ;;
    *) echo "错误：$service 的异常自动重启策略未生效，请检查 systemd 覆盖配置。" >&2; exit 1 ;;
  esac
done
echo "安装完成。首次访问面板时设置管理员账号和密码。"
echo "Caddy 和面板均已启用开机自启及异常自动重启。"
echo "面板默认监听：http://127.0.0.1:7080"
echo "备份目录：$backup_dir"
