# 正式发版流程

## 流程概览

```text
日常：修改 → 必要检查 → 保存到 GitHub
需要给使用者更新时：准备版本号和更新说明 → 检查 → 发布版本
```

普通代码推送不发版。**推送正式版本标签会自动发布到 GitHub**，只在本次任务明确包含正式发版时执行。发布工作流不连接服务器、不执行部署。

日常可直接提交到 `main`，分支和 PR 都是可选工具。基础自动检查提供反馈，主分支只保留防强制覆盖和防删除。完整 Linux 检查按需运行，发版时自动执行。

发布当前只支持递增的稳定版本 `vX.Y.Z`，不支持预发布、自动降级或将旧版本重新设为最新。已经发布的标签和附件不修改；修复通过新版本发布。

## 哪些文件负责什么

| 文件 | 职责 |
| --- | --- |
| `.github/workflows/checks.yml` | 普通分支推送和 PR 检查 |
| `.github/workflows/release.yml` | 正式标签触发检查、打包和 Release 发布 |
| `scripts/release.py` | 核对版本、生成源码包、安装入口和 SHA256 清单 |
| `install.sh` | 下载正式附件，校验后再调用包内的安装脚本 |
| `scripts/install.sh` | Debian/Ubuntu 系统安装与服务检查 |
| `scripts/install_metadata.py` | 读取包或源码身份，保存安装状态 |

## 准备一个版本

以下用下一个版本 `v1.0.2` 举例，它尚未发布。需要更新时再完成：

1. 将 `VERSION` 和 README 的“当前版本”同步为 `1.0.2`。
2. 将本次内容从 CHANGELOG 的“未归入新版本”移到 `## 1.0.2 — YYYY-MM-DD`，使用实际发布日期，并保留历史版本说明。
3. 完成与改动有关的验收。修改安装、服务或 Caddy 行为时，另外在隔离 Debian/Ubuntu 环境验证；单元测试不能代替系统安装验收。
4. 运行：

   ```bash
   bash scripts/check.sh
   .venv/bin/python scripts/release.py --tag v1.0.2 --check
   ```

5. 检查差异，将本次修改保存并推送到 `main`。如果主动使用了分支，再合并；不要求必须走 PR。

`--check` 仅验证版本、所需文件和更新说明，不生成发布包，也不表示已通过所有发布验收。

## 触发发布

确认发布授权、远端 `main` 对应提交及干净工作区后再执行。不要为了发版覆盖本机未提交修改。

```bash
git switch main
git pull --ff-only
git status --short
git tag -a v1.0.2 -m "Caddy Manager 1.0.2"
git push origin v1.0.2
```

`Release` 工作流会：

1. 确认标签代码已经包含在远端 `main` 的历史中，标签、VERSION、README 和 CHANGELOG 对应。
2. 在 Python 3.11、3.12 下运行统一检查，并在隔离 Debian 12、Ubuntu 24.04 容器中验证真实安装、旧版本升级和恢复。
3. 从干净的标签提交打包，拒绝标签与当前提交不一致、缺少说明、存在更高版本等情况。
4. 先创建不可公开安装的 Release 草稿并上传全部附件，成功后才公开并标为最新版本。这个草稿步骤由工作流自动完成，不需要额外点击发布。

工作流在仓库内串行发布，避免多个版本同时更新最新版本。发布检查失败时不会公开新 Release；上传中断可能留下草稿，修复环境问题后可重跑。已经正式发布的版本不会被重跑覆盖；代码需要改动时另发新版本。

## 发布附件

| 附件 | 内容 |
| --- | --- |
| `caddy-manager.tar.gz` | 对应提交中纳入 Git 的源码，另带 `release.json` 记录完整提交号和标签 |
| `install.sh` | 同一提交的正式安装入口 |
| `SHA256SUMS` | 上述两个附件的 SHA256 校验值 |

GitHub 自带的 “Source code” 下载和上述安装包不同，自动生成的源码包没有 `release.json`，不用于新安装入口。

本地也可从干净的已打标签提交生成同样附件：

```bash
.venv/bin/python scripts/release.py --tag v1.0.2
```

输出在 `dist/`，不会提交到 Git。相同提交和工具链重复打包应得到相同校验值。打包只读取 Git 已跟踪内容，因此应在提交前确认没有误纳入凭据或数据；忽略的 `.venv/`、`.local/` 和 `dist/` 不会进入包。

## 发布后的附件验收

现有工作流在发布前验证标签源码。正式 Release 公开后，还需验证实际下载的附件；完成这些步骤后再将本次发版标记为验收完成。复用现有下载、元数据和 Linux 检查能力，无需另建发布系统，也不增加日常推送的检查范围。

1. 从默认最新入口和本次固定版本入口分别下载三个附件，核对 SHA256、包内版本及提交身份。两个入口应取得本次发布的同一组附件；如果另一个新版本已成为最新，先核实原因。
2. 对实际下载的包运行两种发行版的 `--package` 检查，覆盖新安装、旧版升级、账号/站点/环境/本地证书保留、服务重启、备份数据恢复和卸载保留数据。
3. 在隔离环境另做程序版本回滚演练，按下文核对；现有 `--package` 检查不包含这一步。

以下命令在仓库目录运行，以已公开的本次标签 `v1.0.2` 为例；替换为实际发布标签。仅用于下载和一次性容器验证，不在宿主机执行安装脚本：

```bash
(
  set -euo pipefail
  caddy_release_tag=v1.0.2
  caddy_release_repo=https://github.com/weidaye1122/CaddyManager
  caddy_release_dir="$(mktemp -d)"
  trap 'rm -rf -- "$caddy_release_dir"' EXIT

  for caddy_selection in latest "$caddy_release_tag"; do
    mkdir "$caddy_release_dir/$caddy_selection"
    if [ "$caddy_selection" = latest ]; then
      caddy_download_url="$caddy_release_repo/releases/latest/download"
    else
      caddy_download_url="$caddy_release_repo/releases/download/$caddy_selection"
    fi
    for caddy_asset in install.sh caddy-manager.tar.gz SHA256SUMS; do
      curl -fLsS --retry 2 "$caddy_download_url/$caddy_asset" \
        -o "$caddy_release_dir/$caddy_selection/$caddy_asset"
    done
    (
      cd "$caddy_release_dir/$caddy_selection"
      if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -c SHA256SUMS
      else
        shasum -a 256 -c SHA256SUMS
      fi
    )
  done
  cmp "$caddy_release_dir/latest/SHA256SUMS" "$caddy_release_dir/$caddy_release_tag/SHA256SUMS"
  tar -xzf "$caddy_release_dir/$caddy_release_tag/caddy-manager.tar.gz" -C "$caddy_release_dir"
  .venv/bin/python - "$caddy_release_dir/caddy-manager" "$caddy_release_tag" <<'PY'
import subprocess
import sys
from pathlib import Path
from scripts.install_metadata import source_info

info = source_info(Path(sys.argv[1]))
commit = subprocess.check_output(['git', 'rev-parse', sys.argv[2] + '^{commit}'], text=True).strip()
if info['tag'] != sys.argv[2] or info['commit'] != commit:
    raise SystemExit('发布包版本或提交身份不一致，已停止验收。')
print(f"发布包身份正确：{info['tag']} ({info['commit']})")
PY
  .venv/bin/python scripts/check_linux.py --base debian:bookworm-slim \
    --package "$caddy_release_dir/$caddy_release_tag/caddy-manager.tar.gz"
  .venv/bin/python scripts/check_linux.py --base ubuntu:24.04 \
    --package "$caddy_release_dir/$caddy_release_tag/caddy-manager.tar.gz"
)
```

程序版本回滚演练使用一次性 Debian/Ubuntu 环境和测试账号、站点。在升级前保存旧程序、配套数据、环境文件、服务与 Caddy 覆盖配置及实际证书存储，安装本次下载的包，再按 [恢复面板数据和程序](OPERATIONS.md#恢复面板数据和程序) 恢复升级前状态。验证旧版本和原账号可用、站点/备注/启停状态及配置完整、代理和本地 HTTPS 正常，记录旧、新版本、恢复范围和结果。涉及数据格式变化时，还需覆盖本次迁移与恢复路径。现有安装脚本没有自动程序升级回滚功能，卸载不能替代这项演练。

将下载校验结果、环境、版本及安装/升级/回滚结论保存到仓库旁 `本地资料/截图与验证/`。日志默认仍在 `.local/linux-tests/`，需保留的结果再复制过去；临时下载由上面的命令收尾。尚未完成的项目明确记为“未验证”，不能用源码检查或下载成功代替安装与回滚验收。公共 DNS、ACME 申请/续期和真实服务器验收仍按部署范围另行记录。

## 安装和升级使用什么版本

- 默认安装入口下载 `releases/latest/download/` 的正式附件。
- 设置 `CADDY_MANAGER_VERSION=v1.0.1` 固定该正式版本，不会因主分支变化而安装其他代码。
- 版本不存在、附件不全、校验失败或版本不一致时停止；没有回退 `main` 的路径。
- `CADDY_MANAGER_REPO` 可指定另一个提供同格式正式附件的仓库地址。该配置意味着信任这个来源；SHA256 用于校验下载内容，不是独立的发行者签名。
- 根目录入口即使在源码目录中运行，也会下载正式包。开发或恢复需要安装当前源码时，明确运行 `scripts/install.sh`；记录会区分 Git 源码、无 Git 目录和正式包。
- 升级是主动操作，先按 [备份与恢复说明](OPERATIONS.md) 完成相应备份，随后运行所选版本安装命令。GitHub 发版不会直接修改已安装服务器。

默认安装记录位于 `/opt/caddy-manager/install-info.json`：

| 字段 | 含义 |
| --- | --- |
| `version` / `tag` / `commit` | 源码版本、正式包标签和完整提交号；未知值明确为空 |
| `source` | `release`、`git` 或 `directory` |
| `dirty` | 源码工作区是否有未提交改动；不适用时为空 |
| `status` | `installing`、`ready` 或 `failed` |
| `recorded_at` | 该状态的 UTC 记录时间 |

`ready` 表示安装脚本完成服务检查，不代表公网域名和 HTTPS 已验收。中断或失败需查看状态和服务日志。这个版本记录不能代替程序、配置、数据及证书的完整备份。

## 已有版本

`v1.0.1` 已按此发布方式提供正式附件；历史 `v1.0.0` 只有源码标签。两者均保留，不因维护流程精简而删除或改写。

已有 `v1.0.1` 记录证明标签源码通过隔离 Linux 检查，公开附件通过下载、校验和解包检查；实际附件的隔离安装及完整程序版本回滚没有记录为已完成。本次补齐后续验收约定，不追记为历史通过。

后续按需要发布递增版本。版本公开、安装检查和现有服务器升级分别说明，不把发布成功当作服务器已经更新。
