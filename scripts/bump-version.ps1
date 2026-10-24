# 版本号统一修改（pyproject.toml 是唯一来源）
param([Parameter(Mandatory=$true)][string]$Version)
$Root = Split-Path $PSScriptRoot -Parent
$pyproject = Join-Path $Root "pyproject.toml"
$content = Get-Content $pyproject -Raw
$new = $content -replace '(?m)^(\s*version\s*=\s*")[^"]+(")', "${1}$Version${2}"
Set-Content $pyproject $new -NoNewline
Write-Host "版本已更新为 $Version" -ForegroundColor Green
Select-String -Path $pyproject -Pattern '^\s*version'
