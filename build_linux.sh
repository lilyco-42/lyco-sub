#!/usr/bin/env bash
# Linux 打包。CI 里需要: sudo apt-get install -y gcc patchelf ccache
set -euo pipefail
cd "$(dirname "$0")"

MODE="${1:-release}"

if [ ! -x .venv/bin/python ]; then
  echo "缺少虚拟环境，先执行: uv venv .venv --python 3.11" >&2
  exit 1
fi

echo "==> 安装打包依赖"
uv pip install --python .venv/bin/python nuitka

echo "==> 开始构建 ($MODE)"
.venv/bin/python build_nuitka.py "$MODE"

if [ -d dist/lycosub.dist ]; then
  SIZE=$(du -sm dist/lycosub.dist | cut -f1)
  echo "==> 完成，产物 ${SIZE} MB"
  echo "    运行: dist/lycosub.dist/lycosub.bin"
fi
