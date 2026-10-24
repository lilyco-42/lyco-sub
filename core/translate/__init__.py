"""翻译器注册表。"""

from __future__ import annotations

from .base import TranslateError, Translator, get_translator, list_translators

__all__ = ["Translator", "TranslateError", "get_translator", "list_translators"]
