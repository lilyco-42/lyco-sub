"""音视频探测与音频抽取 —— 全部走 ffmpeg/ffprobe 子进程。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Settings


class MediaError(RuntimeError):
    """媒体处理失败。"""


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    vcodec: str
    acodec: str
    has_audio: bool
    size: int

    def as_dict(self) -> dict:
        return {
            "duration": round(self.duration, 3),
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 3),
            "vcodec": self.vcodec,
            "acodec": self.acodec,
            "has_audio": self.has_audio,
            "size": self.size,
        }


def _run(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError as exc:
        raise MediaError(f"找不到可执行文件: {cmd[0]}，请安装 ffmpeg 并确认在 PATH 中") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"命令超时: {' '.join(cmd[:3])}") from exc


def probe(path: str | Path, settings: Settings) -> MediaInfo:
    """读取媒体元信息。"""
    path = Path(path)
    if not path.exists():
        raise MediaError(f"文件不存在: {path}")

    cp = _run([
        settings.ffprobe, "-v", "error",
        "-show_entries", "format=duration,size",
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate",
        "-of", "json", str(path),
    ], timeout=120)
    if cp.returncode != 0:
        raise MediaError(f"ffprobe 失败: {cp.stderr.strip()[:400]}")

    data = json.loads(cp.stdout or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})

    fps = 0.0
    raw_fps = video.get("r_frame_rate", "0/1")
    if "/" in raw_fps:
        num, den = raw_fps.split("/", 1)
        try:
            fps = float(num) / float(den) if float(den) else 0.0
        except ValueError:
            fps = 0.0

    return MediaInfo(
        duration=float(fmt.get("duration") or 0.0),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=fps,
        vcodec=video.get("codec_name", ""),
        acodec=audio.get("codec_name", ""),
        has_audio=bool(audio),
        size=int(fmt.get("size") or 0),
    )


def extract_audio(src: str | Path, dst: str | Path, settings: Settings,
                  sample_rate: int = 16000) -> Path:
    """抽 16k 单声道 PCM —— ASR 引擎统一输入格式。"""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cp = _run([
        settings.ffmpeg, "-y", "-v", "error",
        "-i", str(src), "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-c:a", "pcm_s16le", str(dst),
    ])
    if cp.returncode != 0 or not dst.exists():
        raise MediaError(f"抽音频失败: {cp.stderr.strip()[:400]}")
    return dst
