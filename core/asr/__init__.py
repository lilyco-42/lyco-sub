"""ASR 引擎注册表 —— 每个引擎实现同一个接口，可插拔。

注意：引擎模块必须在导入时执行 register()，所以这里要显式 import 它们。
新增引擎时，记得在下面加一行导入，否则不会出现在 engines 列表里。
"""

from __future__ import annotations

from .base import ASREngine, ASRResult, EngineUnavailable, get_engine, list_engines

# --- 导入即注册（顺序无关）---
from . import sherpa_engine  # noqa: F401,E402
from . import funasr_engine  # noqa: F401,E402
from . import funasr_fast  # noqa: F401,E402
from . import whisper_engine  # noqa: F401,E402
from . import jianying_engine  # noqa: F401,E402

__all__ = ["ASREngine", "ASRResult", "EngineUnavailable", "get_engine", "list_engines"]
