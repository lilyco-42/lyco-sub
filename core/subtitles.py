"""SRT / ASS / VTT 读写与质量度量 —— 不依赖第三方字幕库。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Cue:
    index: int
    start: float  # 秒
    end: float
    text: str

    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _fmt_srt(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _parse_srt_time(raw: str) -> float:
    raw = raw.strip().replace(",", ".")
    m = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", raw)
    if not m:
        raise ValueError(f"非法时间戳: {raw}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


_SRT_BLOCK = re.compile(
    r"(\d+)\s*\n(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*\n(.*?)(?=\n\s*\n|\Z)",
    re.S,
)


def parse_srt(text: str) -> list[Cue]:
    """宽松解析 SRT：容忍 BOM、CRLF、缺序号。"""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for m in _SRT_BLOCK.finditer(text):
        idx, start, end, body = m.group(1), m.group(2), m.group(3), m.group(4)
        lines = [ln.strip() for ln in body.strip().split("\n") if ln.strip()]
        if not lines:
            continue
        cues.append(Cue(int(idx), _parse_srt_time(start), _parse_srt_time(end), "\n".join(lines)))
    return cues


def read_srt(path: str | Path) -> list[Cue]:
    return parse_srt(Path(path).read_text(encoding="utf-8", errors="replace"))


def write_srt(cues: list[Cue], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(f"{i}\n{_fmt_srt(c.start)} --> {_fmt_srt(c.end)}\n{c.text.strip()}\n")
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def cues_from_segments(segments: list[dict]) -> list[Cue]:
    """从 ASR 的 [{start,end,text}] 构造 cue 列表。"""
    cues = []
    for i, s in enumerate(segments, 1):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        cues.append(Cue(i, float(s["start"]), float(s["end"]), text))
    return cues


def metrics(cues: list[Cue]) -> dict:
    """字幕质量度量 —— 用来对比不同引擎，而不是靠肉眼。"""
    if not cues:
        return {"cues": 0, "chars": 0, "cps": 0.0, "avg_chars": 0.0,
                "has_punct": False, "overlong": 0, "overlap": 0}
    chars = sum(len(c.text) for c in cues)
    speech = sum(c.duration() for c in cues)
    all_text = "".join(c.text for c in cues)
    overlong = sum(1 for c in cues if len(c.text) > 40)
    overlap = 0
    for prev, cur in zip(cues, cues[1:]):
        if cur.start < prev.end - 0.01:
            overlap += 1
    return {
        "cues": len(cues),
        "chars": chars,
        "cps": round(chars / speech, 2) if speech > 0 else 0.0,
        "avg_chars": round(chars / len(cues), 1),
        "has_punct": bool(re.search(r"[，。？！、；：,?!;:]", all_text)),
        "overlong": overlong,
        "overlap": overlap,
    }
