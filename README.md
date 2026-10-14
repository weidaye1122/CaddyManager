# Caddy Manager Lite

一个轻量的 Caddy 反向代理管理面板，适合个人服务器和小型 VPS。

面板使用 Flask + Waitress 提供 Web 管理界面，Caddy 负责反向代理、HTTPS 证书申请和自动续期。面板只管理“域名 → 上游地址”规则，不替代 Caddy 本身。

当前版本：`1.0.0`

## 功能

- 添加、编辑、删除和启停反向代理站点
- 配置域名、上游地址和上游协议
- 站点备注
- Caddy 配置校验、应用和失败回滚
- 证书申请中、正常、即将续期和异常状态提示
- 修改同一域名的上游或备注时复用现有证书
- 配置导入、导出和备份
- 首次设置管理员账号和密码
- Favicon、PWA 和 Apple 主屏图标

## 一键安装

支持 Debian/Ubuntu + systemd 的 VPS。请使用 root 执行：

```bash
bash <(wget -qO- https://raw.githubusercontent.com/weidaye1122/CaddyManager/main/install.sh)
```

固定安装指定版本：

```bash
CADDY_MANAGER_VERSION=v1.0.0 bash <(wget -qO- https://raw.githubusercontent.com/weidaye1122/CaddyManager/main/install.sh)
```

安装脚本会：

1. 安装 Caddy、Flask 和 Waitress；
2. 备份已有 Caddyfile 和 systemd drop-in；
3. 安装面板服务；
4. 让 Caddy 使用面板生成的 Caddyfile；
5. 校验并启动 Caddy 和面板。

面板默认监听 `127.0.0.1:7080`。首次访问时设置管理员账号和密码。需要从其他设备访问时，建议通过 HTTPS 域名、Tailscale 或 SSH 隧道进入面板。

## 手动安装

```bash
git clone https://github.com/weidaye1122/CaddyManager.git
cd CaddyManager
sudo ./scripts/install.sh
```

## 数据和配置

运行数据默认位于 `/var/lib/caddy-manager/`：

```text
auth.json       管理员密码哈希
sites.json      站点配置
Caddyfile       面板生成的 Caddy 配置
backups/        配置备份
```

环境文件默认位于 `/etc/caddy-manager.env`，其中不保存管理员密码。常用环境变量如下：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CADDY_MANAGER_HOST` | `127.0.0.1` | 面板监听地址 |
| `CADDY_MANAGER_PORT` | `7080` | 面板监听端口 |
| `CADDY_MANAGER_DATA` | `/var/lib/caddy-manager` | 面板数据目录 |
| `CADDYFILE` | `/var/lib/caddy-manager/Caddyfile` | Caddy 配置文件 |
| `CADDY_BIN` | `/usr/bin/caddy` | Caddy 可执行文件 |
| `CADDY_ADMIN_URL` | `http://127.0.0.1:2019/config/` | Caddy Admin API 地址 |

不要把 `auth.json`、`sites.json`、备份文件、环境文件或私钥提交到 Git 仓库。

## 维护

查看服务状态：

```bash
sudo systemctl status caddy-manager
sudo systemctl status caddy
```

备份面板数据和环境配置：

```bash
sudo /opt/caddy-manager/scripts/backup.sh
```

卸载面板并保留数据目录：

```bash
sudo /opt/caddy-manager/scripts/uninstall.sh
```

安装脚本会保留原有 Caddyfile，并通过 `/etc/systemd/system/caddy.service.d/` 的 drop-in 配置 Caddy，不直接改写发行版提供的 Caddy service 文件。

## 开发和测试

创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-flask.txt
```

本地启动：

```bash
export CADDY_MANAGER_SKIP_CADDY=1
python flask_app.py
```

运行测试：

```bash
python -m unittest discover -s tests -v
```

## 安全提示

- 不要把 Caddy Admin API 的 `2019` 端口暴露到公网。
- 面板建议只监听本机，或通过 HTTPS、Tailscale、VPN 和 SSH 隧道访问。
- 不要提交管理员密码、访问令牌、私钥和生产环境备份。
- 应用配置前会先执行 Caddy 配置校验。

## 许可证

[MIT License](LICENSE)
