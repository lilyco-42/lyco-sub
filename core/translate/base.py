"""翻译器接口。

实测结论：免费通道（必应 / 谷歌网页版）当前全部失效 ——
必应 auth 端点 404、谷歌返回 429。所以这里只保留 LLM 一条可靠路径，
但接口留成可插拔，将来有可用免费通道可以补。
"""

from __future__ import annotations

from typing import Iterable


class TranslateError(RuntimeError):
    """翻译失败。"""


class Translator:
    name: str = "base"
    label: str = "未命名"
    needs_key: bool = True
    notes: str = ""

    def available(self) -> tuple[bool, str]:
        return True, ""

    def translate_batch(self, texts: list[str], target: str, source: str | None = None) -> list[str]:
        raise NotImplementedError

    def describe(self) -> dict:
        ok, reason = self.available()
        return {
            "name": self.name,
            "label": self.label,
            "needs_key": self.needs_key,
            "available": ok,
            "reason": reason,
            "notes": self.notes,
        }


_REGISTRY: dict[str, Translator] = {}


def register(t: Translator) -> Translator:
    _REGISTRY[t.name] = t
    return t


def get_translator(name: str) -> Translator:
    if name not in _REGISTRY:
        raise TranslateError(f"未知翻译器: {name}，可用: {', '.join(_REGISTRY)}")
    return _REGISTRY[name]


def list_translators() -> Iterable[Translator]:
    return _REGISTRY.values()
