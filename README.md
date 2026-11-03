# Caddy Manager Lite

一个轻量的 Caddy 反向代理管理面板，适合个人服务器和小型 VPS。

面板使用 Flask + Waitress 提供 Web 管理界面，Caddy 负责反向代理、HTTPS 证书申请和自动续期。面板只管理“域名 → 上游地址”规则，不替代 Caddy 本身。

当前版本：`1.0.0`

开发中的变更见 [更新记录](CHANGELOG.md)，本地改动不代表已发布新版本。

## 项目文档

- [本地开发说明](docs/DEVELOPMENT.md)：目录用途、启动、测试和每次修改的流程。
- [发布、备份与恢复](docs/OPERATIONS.md)：版本管理、备份范围和恢复步骤。
- [正式发版流程](docs/RELEASING.md)：从版本准备、自动检查到发布包及安装升级。
- [本地清理计划](docs/CLEANUP.md)：检查频率、文件保留规则和空间增长处理。
- [开发约定](AGENTS.md)：维护项目时遵循的规则。
- [修改记录模板](docs/templates/CHANGE.md)：记录需求、完成条件、验证和交付状态。

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

支持 Debian/Ubuntu + systemd 的 VPS。默认安装最新正式 Release，不安装 `main` 的开发源码。请使用 root 执行：

```bash
caddy_installer="$(mktemp)" && curl -fL https://github.com/weidaye1122/CaddyManager/releases/latest/download/install.sh -o "$caddy_installer" && bash "$caddy_installer" && rm -f "$caddy_installer"
```

固定安装指定版本（以下以 `v1.0.1` 为例，使用前确认该版本已在发布页提供附件）：

```bash
caddy_installer="$(mktemp)" && curl -fL https://github.com/weidaye1122/CaddyManager/releases/download/v1.0.1/install.sh -o "$caddy_installer" && CADDY_MANAGER_VERSION=v1.0.1 bash "$caddy_installer" && rm -f "$caddy_installer"
```

如果仓库尚未发布包含新流程的正式 Release，上述地址暂不可用。历史 `v1.0.0` 仅有源码标签，不含新安装入口需要的发布附件。新入口遇到缺包或校验失败会停止，不会回退安装开发源码。首次启用顺序见 [正式发版流程](docs/RELEASING.md)。

安装脚本会：

1. 下载正式发布包并核对 SHA256，再安装 Caddy、Flask 和 Waitress；
2. 备份已有 Caddyfile 和 systemd drop-in；
3. 安装面板服务；
4. 让 Caddy 使用面板生成的 Caddyfile；
5. 校验并启动 Caddy 和面板，启用开机自启和异常自动重启；
6. 写入安装版本、来源提交和安装检查状态。

面板默认监听 `127.0.0.1:7080`。首次访问时设置管理员账号和密码。需要从其他设备访问时，建议通过 HTTPS 域名、Tailscale 或 SSH 隧道进入面板。

## 从源码安装（开发或恢复）

这个入口安装当前目录中的源码，不会自动选择正式版本。运行前核对当前提交及本地改动；源码安装会记录为 `git` 或 `directory` 来源。

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

下表为安装脚本提供的默认配置；本地开发使用下文的独立启动入口。

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

升级前先备份并核对恢复范围，再运行所选正式版本的安装命令。已有服务器不会因为 GitHub 出现新版本而自动升级。

新安装流程会保存版本记录，默认位置如下：

```bash
cat /opt/caddy-manager/VERSION
cat /opt/caddy-manager/install-info.json
```

记录中的 `ready` 表示安装脚本的服务检查完成；`installing` 或 `failed` 表示未完成。真实域名和 HTTPS 仍需检查。旧安装若没有这些文件，需要通过原部署记录核对，不能据此猜测版本。

Caddy 和面板安装后均会随系统开机启动。异常退出时，Caddy 等待 5 秒自动重启，面板等待 3 秒自动重启；手动停止服务不会触发自动拉起。再次执行安装脚本会更新这两项服务设置。

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

使用 Python 3.11 或 3.12 创建独立环境，安装固定版本依赖（以下以 3.12 为例）：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

本地启动：

```bash
bash scripts/dev.sh
```

打开 <http://127.0.0.1:17080>。测试数据保存在 `.local/data/`，此入口跳过 Caddy 命令、Admin API 和证书连接，按 `Ctrl+C` 停止。端口占用时可设置 `CADDY_MANAGER_DEV_PORT=17081`。

运行统一检查：

```bash
bash scripts/check.sh
```

详细流程及验证范围见 [本地开发说明](docs/DEVELOPMENT.md)。

## 安全提示

- 不要把 Caddy Admin API 的 `2019` 端口暴露到公网。
- 面板建议只监听本机，或通过 HTTPS、Tailscale、VPN 和 SSH 隧道访问。
- 不要提交管理员密码、访问令牌、私钥和生产环境备份。
- 应用配置前会先执行 Caddy 配置校验。

## 许可证

[MIT License](LICENSE)
