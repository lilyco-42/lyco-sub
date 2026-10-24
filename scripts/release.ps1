# 用 gh CLI 一键发布 —— Windows 侧
#
# 用法:
#   .\scripts\release.ps1                 # 自动算版本号 + 建 tag + 发布
#   .\scripts\release.ps1 -Tag v0.2.0     # 指定 tag
#   .\scripts\release.ps1 -DryRun         # 只打印命令，不执行
#
# 前置: gh auth status 必须已登录，且 dist/ 里有构建产物
param(
    [string]$Tag = "",
    [switch]$DryRun,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "[warn] $msg" -ForegroundColor Yellow }

# --- 1. 前置检查 ---
Step "检查 gh 登录状态"
if ($DryRun) {
    Write-Host "(dry-run) gh auth status"
} else {
    gh auth status 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "未登录 GitHub，先执行: gh auth login" -ForegroundColor Red
        exit 1
    }
}

$repo = if ($DryRun) { "owner/repo" } else { (gh repo view --json nameWithOwner -q .nameWithOwner) }
Step "仓库: $repo"

# --- 2. 版本号 ---
if (-not $Tag) {
    $m = Select-String -Path "pyproject.toml" -Pattern '^\s*version\s*=\s*"([^"]+)"' | Select-Object -First 1
    $ver = if ($m) { $m.Matches[0].Groups[1].Value } else { "0.1.0" }
    $Tag = "v$ver"
}
Step "版本: $Tag"

# --- 3. 构建 ---
if (-not $SkipBuild) {
    Step "构建（Nuitka）"
    if ($DryRun) {
        Write-Host "(dry-run) python build_nuitka.py release"
    } else {
        & python build_nuitka.py release
        if ($LASTEXITCODE -ne 0) { throw "构建失败" }
    }
}

# --- 4. 打包 ---
$zip = "lycosub-windows.zip"
Step "打包 $zip"
if ($DryRun) {
    Write-Host "(dry-run) Compress-Archive dist/lycosub.dist/* $zip"
} elseif (Test-Path "dist/lycosub.dist") {
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path "dist/lycosub.dist/*" -DestinationPath $zip
    $mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
    Write-Host "    $zip = $mb MB"
} else {
    Warn "dist/lycosub.dist 不存在，跳过打包"
    exit 1
}

# --- 5. 清掉同 tag 的旧草稿 ---
# 踩过的坑：同 tag 残留草稿会让 Release 页出现空壳
Step "清理同 tag 的旧草稿"
if ($DryRun) {
    Write-Host "(dry-run) gh release list + delete drafts"
} else {
    $drafts = gh release list --json tagName,isDraft --jq ".[] | select(.isDraft and .tagName==`"$Tag`") | .tagName" 2>$null
    foreach ($d in $drafts) {
        gh release delete $d --yes --cleanup-tag 2>$null
        Warn "已删除旧草稿: $d"
    }
}

# --- 6. 创建 Release ---
Step "创建 Release $Tag"
$notes = @"
## lyco-sub $Tag

视频字幕生成工具：本地 ASR + LLM 翻译 + 烧录，人类用 Web UI，AI 用 CLI。

### 安装

1. 解压 `lycosub-windows.zip`
2. 双击 `lycosub.exe`，浏览器自动打开
3. 首次转录会自动下载模型（~230MB，需联网一次）

### 命令行

```powershell
lycosub.exe --help
lycosub.exe transcribe video.mp4 --engine sherpa --out-dir out
lycosub.exe run video.mp4 --translate --burn
```

### 说明

- 本包**不含 torch**，走 sherpa-onnx（27MB 依赖，0.1s 启动）
- 模型不进安装包，首次使用按需下载
- 未签名，Windows 可能提示"未知发布者"
"@

$notesFile = Join-Path $env:TEMP "lycosub-notes.md"
$notes | Set-Content $notesFile -Encoding UTF8

if ($DryRun) {
    Write-Host "(dry-run) gh release create $Tag $zip --title $Tag --notes-file $notesFile"
} else {
    gh release create $Tag $zip --title $Tag --notes-file $notesFile --verify-tag 2>&1
    if ($LASTEXITCODE -ne 0) {
        # tag 不存在时去掉 --verify-tag
        gh release create $Tag $zip --title $Tag --notes-file $notesFile 2>&1
    }
}

Step "完成"
if (-not $DryRun) {
    gh release view $Tag --json url -q .url
}
