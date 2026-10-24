# Windows 一键打包
# 用法: .\nuitka.ps1            → release
#       .\nuitka.ps1 debug      → 带控制台，便于排错
param([string]$Mode = "release")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "缺少虚拟环境，先执行: uv venv .venv --python 3.11" -ForegroundColor Red
    exit 1
}

Write-Host "==> 安装打包依赖" -ForegroundColor Cyan
uv pip install --python .venv\Scripts\python.exe nuitka

Write-Host "==> 开始构建 ($Mode)" -ForegroundColor Cyan
.venv\Scripts\python.exe build_nuitka.py $Mode

$out = "dist\lycosub.dist"
if (Test-Path $out) {
    $size = (Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
    Write-Host ("==> 完成，产物 {0:N0} MB" -f $size) -ForegroundColor Green
    Write-Host "    运行: $out\lycosub.exe"
}
