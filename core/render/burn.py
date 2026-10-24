"""字幕合成。

实测得出的两条铁律：
1. 烧字幕 = 整片重编码。CRF 默认值会让 153MB 变 3MB，
   所以这里**默认 CRF 18**，并明确把体积代价告诉调用方。
2. libass 会把画面转 RGB 再转回，产生轻微偏色（实测平均 1.18/255）。
   这不是 bug，是硬字幕的固有代价；要绝对保真就用软字幕。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings


class RenderError(RuntimeError):
    """渲染失败。"""


# CRF 越小越清晰。实测：18 与源画质接近，28 会明显糊。
QUALITY_CRF = {"ultra": 18, "high": 20, "medium": 23, "low": 28}
QUALITY_PRESET = {"ultra": "slow", "high": "medium", "medium": "medium", "low": "fast"}


@dataclass
class BurnOptions:
    mode: str = "soft"            # soft | hard
    quality: str = "ultra"        # ultra | high | medium | low
    subtitle_lang: str = "chi"    # 软字幕轨语言标记
    font_size: int = 0            # 0 = 用 ASS 自带样式
    margin_v: int = 0             # 0 = 用 ASS 自带样式


def _escape_filter_path(p: Path) -> str:
    """ffmpeg subtitles 滤镜在 Windows 上必须转义盘符冒号和反斜杠。"""
    s = str(p.resolve()).replace("\\", "/")
    if len(s) > 1 and s[1] == ":":
        s = s[0] + "\\:" + s[2:]
    return s.replace("'", "\\'")


def _run(cmd: list[str], settings: Settings, timeout: int = 7200) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as exc:
        raise RenderError(f"找不到 {cmd[0]}，请安装 ffmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError("ffmpeg 超时") from exc


def burn(video: str | Path, subtitle: str | Path, out: str | Path,
         opts: BurnOptions, settings: Settings,
         progress_cb=None) -> Path:
    """把字幕烧进画面（硬字幕）。"""
    video, subtitle, out = Path(video), Path(subtitle), Path(out)
    if not video.exists():
        raise RenderError(f"视频不存在: {video}")
    if not subtitle.exists():
        raise RenderError(f"字幕不存在: {subtitle}")
    out.parent.mkdir(parents=True, exist_ok=True)

    crf = QUALITY_CRF.get(opts.quality, 18)
    preset = QUALITY_PRESET.get(opts.quality, "slow")

    vf = f"subtitles='{_escape_filter_path(subtitle)}'"
    if opts.font_size or opts.margin_v:
        force = []
        if opts.font_size:
            force.append(f"FontSize={opts.font_size}")
        if opts.margin_v:
            force.append(f"MarginV={opts.margin_v}")
        vf += ":force_style='" + ",".join(force) + "'"

    cmd = [
        settings.ffmpeg, "-y", "-v", "error",
        "-i", str(video),
        "-vf", vf,
        "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out),
    ]
    cp = _run(cmd, settings)
    if cp.returncode != 0 or not out.exists():
        raise RenderError(f"烧录失败: {cp.stderr.strip()[:500]}")
    return out


def embed_soft(video: str | Path, subtitle: str | Path, out: str | Path,
               opts: BurnOptions, settings: Settings) -> Path:
    """把字幕作为独立轨道嵌入（软字幕，画面零重编码）。"""
    video, subtitle, out = Path(video), Path(subtitle), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        settings.ffmpeg, "-y", "-v", "error",
        "-i", str(video), "-i", str(subtitle),
        "-map", "0", "-map", "1:0",
        "-c", "copy",
        "-c:s", "mov_text",
        "-metadata:s:s:0", f"language={opts.subtitle_lang}",
        "-movflags", "+faststart",
        str(out),
    ]
    cp = _run(cmd, settings)
    if cp.returncode != 0 or not out.exists():
        raise RenderError(f"软字幕封装失败: {cp.stderr.strip()[:500]}")
    return out
