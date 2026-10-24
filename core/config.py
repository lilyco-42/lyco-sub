"""集中配置：环境变量 > 配置文件 > 默认值。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _data_dir() -> Path:
    raw = os.environ.get("LYCOSUB_HOME")
    base = Path(raw) if raw else Path.home() / ".lyco-sub"
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Settings:
    """运行时配置。所有字段都可用 LYCOSUB_<NAME> 环境变量覆盖。"""

    data_dir: Path = field(default_factory=_data_dir)
    # LLM 翻译（OpenAI 兼容）
    llm_api_key: str = ""
    llm_api_base: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    # 默认引擎
    asr_engine: str = "funasr"
    # ffmpeg
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    # 服务
    host: str = "127.0.0.1"
    port: int = 8043

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        s.llm_api_key = os.environ.get("LYCOSUB_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", s.llm_api_key)
        s.llm_api_base = os.environ.get("LYCOSUB_LLM_API_BASE") or os.environ.get("OPENAI_BASE_URL", s.llm_api_base)
        s.llm_model = os.environ.get("LYCOSUB_LLM_MODEL", s.llm_model)
        s.asr_engine = os.environ.get("LYCOSUB_ASR_ENGINE", s.asr_engine)
        s.ffmpeg = os.environ.get("LYCOSUB_FFMPEG", s.ffmpeg)
        s.ffprobe = os.environ.get("LYCOSUB_FFPROBE", s.ffprobe)
        s.host = os.environ.get("LYCOSUB_HOST", s.host)
        s.port = int(os.environ.get("LYCOSUB_PORT", s.port))
        return s

    @property
    def jobs_dir(self) -> Path:
        d = self.data_dir / "jobs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def uploads_dir(self) -> Path:
        d = self.data_dir / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        return d
