# 打包与发布

## 一句话

`python build_nuitka.py release` 出产物，`./scripts/release.ps1` 用 gh CLI 发 Release。
**桌面包不带 torch**，走 sherpa-onnx。

## 为什么不用 funasr 打包

实测对比（同一台机器，Ryzen 7 8845HS）：

| 指标 | funasr + torch | sherpa-onnx |
|---|---|---|
| 依赖体积 | 1,084 MB | **27 MB** |
| import 耗时 | **13 s** | **0.1 s** |
| 模型加载 | 5 s（无标点）/ 31 s（带标点） | < 1 s |
| Nuitka 冷构建 | 179 min+ | **~20 min** |
| 产物大小 | 1 GB+ | 预计 ~120 MB |

torch 是 476MB，其中大部分桌面场景用不到（CUDA、训练、分布式）。
sherpa-onnx 是 k2-fsa 的纯 ONNX 推理库，三平台都有预编译 wheel。

## 模型分发策略

**模型不进安装包。** paraformer int8 = 227MB，塞进去会让：
- 安装包超过 GitHub Release 单资产 2GiB 限制的风险；
- 用户每次升级都重下 227MB；
- CI 构建时间翻倍。

改为首次使用时下载到 `~/.lycosub/models/`，带断点续传 + 镜像回退：

```
LYCOSUB_MODEL_DIR   自定义模型目录
LYCOSUB_HF_MIRROR   0 关闭 hf-mirror.com 回退
```

⚠️ **实测下载速度只有 0.44–0.81 MB/s**（国内网络），227MB 需要 5–8 分钟。
首次使用必须给用户明确提示，不能静默卡住。

## 构建命令

```powershell
# Windows
.\nuitka.ps1              # release
.\nuitka.ps1 debug        # 带控制台窗口，便于排错
```

```bash
# Linux（CI 需要 gcc patchelf ccache）
./build_linux.sh
```

## 踩过的坑（都在 build_nuitka.py 里防住了）

| 坑 | 现象 | 对策 |
|---|---|---|
| torch._inductor 含非 UTF-8 字符 | Windows(gbk) 下 Nuitka anti-bloat 解析崩溃 | `--nofollow-import-to=torch._inductor` |
| torch/include 约 1 万文件 | macOS codesign 命令行超 ARG_MAX | `--noinclude-data-files=torch/include` |
| 缺 .dist-info | `PackageNotFoundError` | `--include-distribution-metadata` |
| macOS 用 --standalone | 不产出 .app | 必须 `--mode=app`（与 --standalone 互斥） |
| 同 tag 残留草稿 | Release 页出现空壳 | 发布前 `gh release delete` 清草稿 |
| tag push 触发二次 workflow | Linux/macOS job 从未跑过 | 同一 run 内用 job outputs 传 tag |

### 本机特有的坑：MinGW 下载失败

Nuitka 在 Windows 上需要一个**特定版本**的 winlibs-gcc（15.2.0posix-13.0.0-msvcrt-r6），
不接受系统装的 Scoop gcc。它会自动下载，但：

- GitHub Release 在国内网络下经常中断，zip 变成 0 字节；
- 如果同时有别的进程占着那个 zip，会报 `WinError 32`；
- 下载失败后 Nuitka 会删掉损坏的 zip 重试，形成循环。

**手动解决**：

```powershell
$dst = "$env:LOCALAPPDATA\Nuitka\Nuitka\Cache\downloads\gcc\x86_64\15.2.0posix-13.0.0-msvcrt-r6"
New-Item -ItemType Directory -Force -Path $dst | Out-Null
$url = "https://github.com/brechtsanders/winlibs_mingw/releases/download/15.2.0posix-13.0.0-msvcrt-r6/winlibs-x86_64-posix-seh-gcc-15.2.0-mingw-w64msvcrt-13.0.0-r6.zip"
curl.exe -L --retry 5 -C - -o "$dst\winlibs-x86_64-posix-seh-gcc-15.2.0-mingw-w64msvcrt-13.0.0-r6.zip" $url
```

或者装 Visual Studio Build Tools（MSVC 14.3+），Nuitka 会优先用它，不用下 gcc。

## gh CLI 发布

```powershell
# Windows
.\scripts\release.ps1                    # 自动算版本
.\scripts\release.ps1 -Tag v0.2.0
.\scripts\release.ps1 -DryRun            # 只看命令
.\scripts\release.ps1 -SkipBuild         # 用已有产物
```

```bash
# Linux / macOS
./scripts/release.sh
DRY_RUN=1 ./scripts/release.sh
```

前置：`gh auth status` 已登录。

## CI

`.github/workflows/build.yml`：
- `tests` 先跑单测（不过就不出产物）；
- `build-windows` 算 tag → Linux/macOS 复用同一 tag；
- 三平台都**只装轻量依赖**，不装 torch；
- 每个平台缓存 Nuitka 的 C 编译产物，key 用 pyproject.toml 的 hash。

## 本机不编译，一律走 CI

**本机不跑 Nuitka 构建。** 原因：

1. Nuitka 在 Windows 上强依赖特定版本的 winlibs-gcc（15.2.0posix-13.0.0-msvcrt-r6），
   不接受系统装的 Scoop gcc。它会自动下载，但 GitHub Release 在国内网络下经常
   中断，zip 变 0 字节，然后 Nuitka 删掉重试，形成循环；
2. 如果同时有别的进程占着那个 zip，会报 `WinError 32`；
3. 即使绕过（`LYCOSUB_FORCE_LOCAL_GCC=1` + `--experimental=force-accept-windows-gcc`），
   本机编译要占用几十个 gcc 进程、十几分钟，把机器拖死。

正确做法：**push 到 GitHub，让 Actions 的干净环境构建。**

```bash
git push                      # 触发 CI
gh run watch                  # 看进度
gh run view --log-failed      # 看失败原因
```

CI 的 Windows runner 自带 MSVC，不需要下 MinGW，比本机可靠得多。

## 验证状态

| 项目 | 状态 |
|---|---|
| 单元测试（13 个，跨平台） | ✅ 本地 + CI 均通过 |
| sherpa 引擎端到端（转录 1.4s / 烧录 16s） | ✅ 本地实测 |
| CLI 契约（dry-run / JSON / exit code） | ✅ 本地实测 |
| Windows CI 构建 | 🔄 进行中 |
| Linux / macOS CI 构建 | ⏳ 等 Windows 完成 |
| 产物实际启动 | ⏳ 未验证 |

**不要把"CI 在跑"说成"已验证"。**
