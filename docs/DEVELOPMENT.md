# 本地开发说明

## 目录用途

| 位置 | 用途 |
| --- | --- |
| `flask_app.py` | API、账号、站点数据、Caddy 配置生成和证书检查 |
| `public/` | HTML、JavaScript、CSS、图标及 PWA 文件 |
| `tests/` | 使用临时数据与模拟 Caddy 命令的自动化测试 |
| `scripts/` | 本地启动、检查、发布打包，以及 Linux 安装、备份和卸载脚本 |
| `deploy/` | systemd 服务及服务器环境配置示例 |
| `docs/` | 开发、发布与恢复说明；`templates/` 存放记录模板 |
| `.github/workflows/` | 普通推送/PR 自动检查，正式标签触发发布；不执行服务器部署 |
| `legacy/` | 保留的历史实现，不是当前开发入口 |
| `.venv/` | 本机 Python 虚拟环境，可按依赖文件重建，Git 忽略 |
| `.local/data/` | 本地测试账号和站点数据，Git 忽略，停止服务后仍保留 |
| `dist/` | 发布打包输出，可重新生成，Git 忽略 |
| `../本地资料/` | 仓库外的讨论记录、验证材料和备份 |

## 首次准备

以下命令均在 `CaddyManager/` 中运行。开发基线为 Python 3.11 或 3.12、Bash 和 Git。无需安装 Node.js 或 Caddy；前端直接提供静态文件，没有打包步骤。

先确认 Python 版本。macOS 自带的 `python3` 可能较旧；已安装 Python 3.12 时可以使用 `python3.12`。

```bash
python3.12 --version
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

使用 Python 3.11 时将前两行的命令名换成 `python3.11`。无需 `sudo`，无需修改全局 Python 环境。

`requirements-dev.txt` 固定本地和 CI 的依赖版本，包含运行依赖及其间接依赖；`requirements-flask.txt` 保留运行依赖的允许范围。升级依赖时在干净虚拟环境中重新解析、同步固定版本并检查，不随手混入功能修改。Linux 安装脚本使用发行版的 Python 包，其兼容性需要在目标系统另行验证。

## 启动与停止

```bash
bash scripts/dev.sh
```

打开 <http://127.0.0.1:17080>，首次访问自行设置一个仅供本机测试的账号。按 `Ctrl+C` 停止。

这个入口强制使用回环地址、仓库内 `.local/data/` 和跳过 Caddy 的开发模式，覆盖终端中同名的服务器设置，不读取 `/etc/caddy-manager.env`。它不会调用 Caddy、访问 Admin API 或连接证书端口。证书显示“待检查 / 开发模式：未检查证书”属于预期行为，不能用于判断真实 HTTPS 是否正常。

端口占用时选择另一个端口，不停止不明进程：

```bash
CADDY_MANAGER_DEV_PORT=17081 bash scripts/dev.sh
```

需要重新开始测试时，先停止本地服务，再将 `.local/data/` 整个移到仓库外的本地备份目录。重新启动会创建空数据。不要在运行中移动数据，不要导入真实服务器备份。`.local/` 和 `.venv/` 应是本机普通目录，不要链接到服务器数据目录。

直接运行 `python flask_app.py` 会遵循进程环境和程序默认值，不具备上述入口的固定本地配置，因此日常开发统一使用脚本。

## 每次修改的流程

1. 查看 `git status`，明确修改原因及完成条件。较大的改动可复制 [记录模板](templates/CHANGE.md) 到 `../本地资料/讨论与记录/`。
2. 在 `codex/简短任务名` 分支修改，保留无关工作；不要用复制“最终版文件夹”的方式管理代码版本。
3. 运行统一检查，处理失败后再继续：

   ```bash
   bash scripts/check.sh
   ```

4. 按修改范围进行页面操作检查，必要时补行为测试。
5. 查看差异，更新说明和 [更新记录](../CHANGELOG.md)。检查提交范围中没有 `.local/`、账号、备份或环境实值。
6. 在记录中写清楚结果、遗留问题及是否已提交、发布或部署。

检查脚本包含依赖一致性、Python 语法、自动化测试、Shell 语法和已跟踪差异格式检查。发布测试使用临时 Git 仓库和本地下载替身，不执行系统安装或访问 GitHub。Shell 检查仅解析语法。GitHub 工作流配置了 Python 3.11 / 3.12 检查；推送后需要查看实际运行结果，不能把本机通过当作远端通过。

准备正式版本时使用 [正式发版流程](RELEASING.md)，普通开发推送不会自动发布。

## Linux 集成检查

需要 Docker 和 Buildx，使用一次性 Debian 12 / Ubuntu 24.04 容器运行真实 systemd、Caddy 和发行版 Python 依赖：

```bash
.venv/bin/python scripts/check_linux.py --base debian:bookworm-slim
.venv/bin/python scripts/check_linux.py --base ubuntu:24.04
```

检查使用当前 `HEAD` 已提交源码，升级起点为历史 `v1.0.0`；因此先保存需要验证的代码提交。每个发行版分别执行新安装和旧版升级场景，验证账号、站点、环境配置和本地证书保留、服务异常重启、实际备份归档恢复及卸载保留数据。

日志在 `.local/linux-tests/`。脚本只删除自己创建的容器、镜像和独立 Buildx 缓存，不清理其他项目的 Docker 资源。容器为运行 systemd 使用特权模式，但不挂载主机目录、不映射主机端口。不要把测试容器用于生产运行。

HTTPS 测试使用 `qa.localhost` 和 Caddy 的本地 CA，验证真实 TLS 和反向代理；公共 DNS、ACME 申请/续期、物理机重启仍属于具体部署的验收范围。

正式发布后可用 `--package /绝对路径/caddy-manager.tar.gz` 验证实际发布附件。GitHub 普通检查及正式发版都包含两个发行版的集成任务，使用公开仓库的标准 Linux runner。

## 按改动选择验证

| 修改范围 | 除统一检查外，需要验证的内容 |
| --- | --- |
| 页面和交互 | 实际打开页面，检查相关表单、提示、刷新及需要支持的屏幕宽度；变更 JavaScript 时可用 `node --check public/app.js` 和 `node --check public/sw.js` 检查语法 |
| 账号 | 首次设置、错误密码、登录退出、重启后的登录，不能输出密码或哈希 |
| 站点和持久化 | 增删改、备注、启停、重复域名、重启后数据仍在、导出再导入 |
| Caddy 配置 | 生成内容、校验失败、重载失败回滚；另在隔离的真实 Caddy 环境检查代理和 HTTPS |
| 安装和服务 | 在一次性 Debian/Ubuntu 环境验证安装、升级、服务重启、保留数据及恢复流程 |
| 依赖 | 从依赖清单新建环境，跑检查；生产发行版依赖单独验证 |

自动化测试通过可以证明其覆盖的逻辑，没有实际完成的页面、证书、Linux 服务或生产验证应明确写“未验证”。
