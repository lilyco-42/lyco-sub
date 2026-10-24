"""跨平台打包脚本 —— Windows / Linux / macOS。

设计要点（每条都是踩坑换来的）：

1. **不打包 torch**。桌面包默认走 sherpa-onnx（27MB），不装 funasr。
   torch 是 476MB，Nuitka 冷构建要 179 分钟，产物 1GB+，桌面场景完全不划算。
   需要 funasr 的用户用 pip 装源码版，不走打包产物。

2. **模型不进安装包**。paraformer int8 有 227MB，塞进去会让 Release 单资产
   超过 GitHub 的 2GiB 上限（rembg-ui 踩过 422 失败）。首次运行时按需下载。

3. **排除 torch._inductor**。它的模板代码含非 UTF-8 字符，Windows(gbk) 下
   Nuitka 解析会崩。即使不打包 torch 也要防万一（间接依赖可能带进来）。

4. **--noinclude-data-files=torch/include**。torch 头文件约 1 万个，
   macOS codesign 会把它们拼进命令行，超出 ARG_MAX 报
   "command line was too long"（rembg-ui 踩过 macOS 构建失败）。

5. **.dist-info 要打进去**。importlib.metadata 找不到元数据会抛
   PackageNotFoundError（rembg-ui issue #1）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    tomllib = None

ROOT = Path(__file__).parent
APP_NAME = "lyco-sub"
OUTPUT_NAME = "lycosub"

# 需要连同 .dist-info 一起打包的发行版（它们 import 时会读自身版本）
METADATA_DISTRIBUTIONS = ["sherpa-onnx", "fastapi", "uvicorn"]


def _project_version() -> str:
    if tomllib is not None:
        try:
            return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        except Exception:  # noqa: BLE001
            pass
    m = re.search(r'^\s*version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0.0.0"


def _has(dist: str) -> bool:
    import importlib.metadata as md

    try:
        md.version(dist)
        return True
    except Exception:  # noqa: BLE001
        return False


def build(mode: str = "release", with_funasr: bool = False) -> None:
    is_debug = mode == "debug"
    version = _project_version()
    dist_dir = ROOT / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
        print("已清理 dist")

    # macOS 必须用 --mode=app（与 --standalone 互斥，否则不产出 .app）
    mode_flag = "--mode=app" if sys.platform.startswith("darwin") else "--standalone"

    cmd = [
        sys.executable, "-m", "nuitka",
        mode_flag,
        f"--output-folder-name={OUTPUT_NAME}",
        f"--output-filename={OUTPUT_NAME}",
        f"--include-data-dir={ROOT / 'frontend'}=frontend",
        "--include-package=fastapi",
        "--nofollow-import-to=fastapi.agents",
        # 防御性排除：即使环境里装了 torch 也不跟进去
        "--nofollow-import-to=torch",
        "--nofollow-import-to=torch._inductor",
        "--nofollow-import-to=funasr",
        "--nofollow-import-to=modelscope",
        "--nofollow-import-to=whisper",
        "--noinclude-data-files=torch/include",
        "--company-name=lilyco-42",
        f"--product-name={APP_NAME}",
        f"--product-version={version}",
        f"--file-version={version}",
        "--file-description=Subtitle Generator",
        "--copyright=Copyright (c) lilyco-42",
        "--assume-yes-for-downloads",
        f"--output-dir={dist_dir}",
        str(ROOT / "server.py"),
    ]

    if sys.platform.startswith("win"):
        cmd += [
            f"--windows-console-mode={'force' if is_debug else 'disable'}",
            "--include-windows-runtime-dlls=yes",
        ]
        ico = ROOT / "assets" / "lycosub.ico"
        if ico.exists():
            cmd.append(f"--windows-icon-from-ico={ico}")
    elif sys.platform.startswith("darwin"):
        cmd += [
            f"--macos-app-name={APP_NAME}",
            f"--macos-app-version={version}",
            "--macos-signed-app-name=com.lilyco42.lycosub",
            "--macos-app-mode=gui",
        ]
        if not is_debug and shutil.which("create-dmg"):
            cmd.append("--macos-app-create-dmg")
    else:
        pass  # Linux: --standalone 即可，可选 --linux-icon

    for dist in METADATA_DISTRIBUTIONS:
        if _has(dist):
            cmd.append(f"--include-distribution-metadata={dist}")
        else:
            print(f"[warn] 未安装，跳过元数据: {dist}")

    # 本机没装 MSVC、又下不动 winlibs-gcc 时的逃生口：
    # Nuitka 默认拒绝系统装的 gcc（"very dependent on the precise one"），
    # 加这个 flag 才肯用。设置 LYCOSUB_FORCE_LOCAL_GCC=1 启用。
    if os.environ.get("LYCOSUB_FORCE_LOCAL_GCC") == "1":
        cmd.append("--experimental=force-accept-windows-gcc")
        print("[info] 使用本机 gcc（LYCOSUB_FORCE_LOCAL_GCC=1）")

    if not is_debug:
        cmd.append("--python-flag=-O")

    print(f"Building [{mode.upper()}] v{version} ...")
    print(f"  torch 打包: {'是' if with_funasr else '否（默认，走 sherpa-onnx）'}")
    subprocess.run(cmd, check=True)
    print(f"\n产物: {dist_dir}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        print("用法: python build_nuitka.py [release|debug] [--with-funasr]")
        return
    mode = args[0] if args else "release"
    if mode not in ("release", "debug"):
        print(f"未知模式: {mode}（可选 release / debug）")
        sys.exit(2)
    with_funasr = "--with-funasr" in sys.argv
    build(mode, with_funasr)


if __name__ == "__main__":
    main()
