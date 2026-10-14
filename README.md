# Caddy Manager Lite

个人使用的轻量 Caddy 反向代理管理面板。正式部署使用 Flask + Waitress，管理「域名 → 上游地址」规则，Caddy 负责自动申请和续期 HTTPS 证书。

当前版本：`1.0.0`

## 一键安装

支持 Debian/Ubuntu + systemd 的 VPS。将仓库复制到服务器后执行：

```bash
sudo ./scripts/install.sh
```

安装脚本会安装 Caddy、Flask、Waitress，备份已有 Caddy 配置，创建面板 systemd 服务，并让 Caddy 使用 `/var/lib/caddy-manager/Caddyfile`。面板默认只监听 `127.0.0.1:7080`，建议通过 HTTPS 域名或 Tailscale 访问。

常用维护命令：

```bash
sudo ./scripts/backup.sh
sudo systemctl status caddy-manager
sudo systemctl status caddy
sudo ./scripts/uninstall.sh
```

卸载脚本会恢复安装前的 Caddyfile，保留 `/var/lib/caddy-manager` 运行数据，不会自动删除站点配置和备份。

## 本地运行

本地 Flask 运行需要 Python 3.9+ 和 Flask/Waitress：

```bash
export CADDY_MANAGER_SKIP_CADDY=1 # 本地预览 UI 时使用；服务器正式运行不要设置
python3 flask_app.py
```

打开 <http://127.0.0.1:7080>，首次打开会要求设置管理员账号、密码和确认密码。认证信息保存在数据目录的 `auth.json` 中，密码只保存为加盐哈希。

## 手动 systemd 部署

服务器上可以把项目放到 `/opt/caddy-manager`，创建数据目录并让它和 Caddy 使用同一个配置目录：

```bash
sudo install -d -o caddy -g caddy /var/lib/caddy-manager
sudo cp deploy/caddy-manager.env.example /etc/caddy-manager.env
sudo chmod 600 /etc/caddy-manager.env
sudo cp deploy/caddy-manager.service /etc/systemd/system/caddy-manager.service
sudo systemctl daemon-reload
sudo systemctl enable --now caddy-manager
sudo systemctl status caddy-manager
```

`caddy-manager.service` 默认以 `caddy` 用户运行，使用 `/usr/bin/python3` 和 Waitress；示例配置把 Caddyfile 和备份放在 `/var/lib/caddy-manager`，避免给面板 root 权限。需要同时让 Caddy systemd 服务使用这个 Caddyfile（可通过 systemd drop-in 覆盖 `ExecStart`）。面板默认只监听 `127.0.0.1:7080`。

正式运行时，取消 `CADDY_MANAGER_SKIP_CADDY`，并确保 `caddy` 在 PATH 中。面板会在每次新增、编辑、删除或恢复站点时：

1. 生成候选 Caddyfile；
2. 执行 `caddy validate`；
3. 校验成功后替换配置并执行 `caddy reload`；
4. reload 失败时恢复旧配置。

## 环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `CADDY_MANAGER_HOST` | `127.0.0.1` | 面板监听地址 |
| `CADDY_MANAGER_PORT` | `7080` | 面板端口 |
| `CADDY_MANAGER_DATA` | `./data` | 站点和备份目录 |
| `CADDYFILE` | `/etc/caddy/Caddyfile` | Caddyfile 路径 |
| `CADDY_BIN` | `caddy` | Caddy 可执行文件路径 |
| `CADDY_ADMIN_URL` | `http://127.0.0.1:2019/config/` | Caddy 状态检查地址 |
| `CADDY_MANAGER_SKIP_CADDY` | `0` | 设为 `1` 仅用于 UI 本地预览 |

面板默认只监听本机。若要从其他设备访问，请通过 Tailscale、SSH 隧道或 HTTPS 反代暴露；不要把 Caddy Admin API (`:2019`) 暴露到公网。首次设置完成后，面板使用登录会话保护管理接口。

## 当前边界

已支持站点增删改、备注、启停、证书状态检查、自动续签提示、错误提示、配置校验、应用回滚、配置导入导出和 Caddy 状态检查。证书由 Caddy 自动续签；修改同一域名的上游或备注不会重新申请证书。暂不包含多用户、泛域名 DNS 验证、TCP/UDP 转发、流量统计和 Docker 自动发现。

`server.js` 保留为早期 Node 原型，不再作为正式服务。首尔服务器实测同等页面和站点数据下，Node RSS 约 116 MB，Flask + Waitress RSS 约 37 MB；已切换为 Flask 并移除面板专用 Node.js，SillyTavern 自带的 Node 运行时不受影响。
