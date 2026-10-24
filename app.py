"""统一入口 —— 双击启动 Web，带参数走 CLI。

这是打包成桌面 exe 的入口。设计动机：

用户双击 exe 时没有参数，期望「打开界面」；
AI/脚本调用时带参数，期望「执行命令」。
一个入口同时满足，避免出两个 exe（用户分不清该点哪个）。

    lycosub.exe                          → 启动 Web，自动开浏览器
    lycosub.exe transcribe a.mp4 --json  → CLI 行为，stdout 只有 JSON
    lycosub.exe --help                   → 显示帮助
    lycosub.exe --version                → 显示版本
"""

from __future__ import annotations

import sys

# CI 的 Windows runner 默认 stdout 是 cp1252，打印中文会崩（踩过）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except (AttributeError, ValueError):
    pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # 无参数 → 桌面模式：起服务 + 开浏览器
    if not argv:
        import server

        server.main()
        return 0

    # 有参数 → CLI 模式
    import cli

    return cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
