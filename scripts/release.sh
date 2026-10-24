#!/usr/bin/env bash
# 用 gh CLI 一键发布 —— Linux / macOS 侧
#
# 用法:
#   ./scripts/release.sh              # 自动版本号
#   ./scripts/release.sh v0.2.0       # 指定 tag
#   DRY_RUN=1 ./scripts/release.sh    # 只打印
set -euo pipefail

cd "$(dirname "$0")/.."

TAG="${1:-}"
DRY_RUN="${DRY_RUN:-0}"
SKIP_BUILD="${SKIP_BUILD:-0}"

step() { echo -e "\033[36m==> $*\033[0m"; }
warn() { echo -e "\033[33m[warn] $*\033[0m"; }

# --- 前置 ---
step "检查 gh 登录"
if [ "$DRY_RUN" != "1" ]; then
  gh auth status >/dev/null 2>&1 || { echo "未登录，先 gh auth login" >&2; exit 1; }
  REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
else
  REPO="owner/repo"
fi
step "仓库: $REPO"

# --- 版本 ---
if [ -z "$TAG" ]; then
  VER=$(grep -oP '^\s*version\s*=\s*"\K[^"]+' pyproject.toml | head -1)
  TAG="v${VER:-0.1.0}"
fi
step "版本: $TAG"

# --- 构建 ---
if [ "$SKIP_BUILD" != "1" ]; then
  step "构建"
  if [ "$DRY_RUN" = "1" ]; then
    echo "(dry-run) python build_nuitka.py release"
  else
    python build_nuitka.py release
  fi
fi

# --- 打包 ---
OS=$(uname -s)
if [ "$OS" = "Darwin" ]; then
  ASSET="lycosub-macos.zip"
  step "打包 $ASSET"
  if [ "$DRY_RUN" != "1" ]; then
    (cd dist && zip -qr "../$ASSET" ./*.app)
  fi
else
  ASSET="lycosub-linux.tar.gz"
  step "打包 $ASSET"
  if [ "$DRY_RUN" != "1" ]; then
    tar -czf "$ASSET" -C dist/lycosub.dist .
  fi
fi

# --- 清草稿 ---
step "清理同 tag 旧草稿"
if [ "$DRY_RUN" != "1" ]; then
  for d in $(gh release list --json tagName,isDraft \
    --jq ".[] | select(.isDraft and .tagName==\"$TAG\") | .tagName" 2>/dev/null || true); do
    gh release delete "$d" --yes --cleanup-tag 2>/dev/null || true
    warn "已删除旧草稿: $d"
  done
fi

# --- 发布 ---
step "创建 Release $TAG"
if [ "$DRY_RUN" = "1" ]; then
  echo "(dry-run) gh release create $TAG $ASSET"
else
  gh release create "$TAG" "$ASSET" \
    --title "$TAG" \
    --generate-notes \
    --verify-tag 2>/dev/null \
  || gh release create "$TAG" "$ASSET" --title "$TAG" --generate-notes
  gh release view "$TAG" --json url -q .url
fi
