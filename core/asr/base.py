"""ASR 引擎接口 + 注册表。

设计约束（来自实测）：
- 引擎可能随时不可用（未装依赖 / 云端接口失效），必须能探测并降级；
- 每个引擎自报 capabilities，UI 和 CLI 据此决定展示什么；
- 返回统一的 [{start,end,text}]，上层不关心具体引擎。
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from typing import Callable, Iterable


class EngineUnavailable(RuntimeError):
    """引擎依赖缺失或服务不可达。"""


@dataclass
class ASRResult:
    engine: str
    segments: list[dict]
    language: str = ""
    duration: float = 0.0
    elapsed: float = 0.0
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "language": self.language,
            "duration": round(self.duration, 3),
            "elapsed": round(self.elapsed, 2),
            "segments": self.segments,
            "meta": self.meta,
        }


class ASREngine:
    """所有引擎的基类。"""

    name: str = "base"
    label: str = "未命名"
    # offline: 纯本地推理；cloud: 依赖第三方服务
    kind: str = "offline"
    needs: tuple[str, ...] = ()
    notes: str = ""

    def available(self) -> tuple[bool, str]:
        """返回 (是否可用, 原因)。"""
        for mod in self.needs:
            if importlib.util.find_spec(mod) is None:
                return False, f"缺少 Python 包: {mod}"
        return True, ""

    def transcribe(self, audio_path: str, *, language: str | None = None,
                   progress: Callable[[int, str], None] | None = None,
                   **opts) -> ASRResult:
        raise NotImplementedError

    def describe(self) -> dict:
        ok, reason = self.available()
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "available": ok,
            "reason": reason,
            "notes": self.notes,
        }


_REGISTRY: dict[str, ASREngine] = {}


def register(engine: ASREngine) -> ASREngine:
    _REGISTRY[engine.name] = engine
    return engine


def get_engine(name: str) -> ASREngine:
    if name not in _REGISTRY:
        raise EngineUnavailable(f"未知引擎: {name}，可用: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]


def list_engines() -> Iterable[ASREngine]:
    return _REGISTRY.values()
