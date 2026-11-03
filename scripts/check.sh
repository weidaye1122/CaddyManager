#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "请先按 docs/DEVELOPMENT.md 创建 .venv 并安装 requirements-dev.txt。" >&2
  exit 1
fi
cd "$PROJECT_DIR"

echo '[1/5] 检查 Python 依赖'
"$PYTHON" -m pip check
echo '[2/5] 检查 Python 语法'
"$PYTHON" -m compileall -q flask_app.py scripts tests
echo '[3/5] 运行隔离的自动化测试'
"$PYTHON" -m unittest discover -s tests -v
echo '[4/5] 检查 Shell 脚本语法（不执行安装或服务操作）'
for script in install.sh scripts/*.sh; do
  bash -n "$script"
done
echo '[5/5] 检查已跟踪文件的未提交差异格式'
git diff --check
git diff --cached --check
echo '本地自动检查通过；页面操作及真实 Caddy 部署需按文档分别验证。'
