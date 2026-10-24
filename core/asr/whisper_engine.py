"""faster-whisper —— 本地离线、多语种。CPU 上比 FunASR 慢，但语种覆盖广。"""

from __future__ import annotations

import time
from typing import Callable

from .base import ASREngine, ASRResult, EngineUnavailable, register


class FasterWhisperEngine(ASREngine):
    name = "whisper"
    label = "faster-whisper（本地 / 多语种 / 慢）"
    kind = "offline"
    needs = ("faster_whisper",)
    notes = "MIT。实测 CPU 上 64s 音频 large-v3 需 39s；中文专名易错且可能输出繁体，需配合 initial_prompt。"

    _models: dict = {}

    def _load(self, size: str):
        if size not in FasterWhisperEngine._models:
            from faster_whisper import WhisperModel

            FasterWhisperEngine._models[size] = WhisperModel(
                size, device="cpu", compute_type="int8", cpu_threads=8
            )
        return FasterWhisperEngine._models[size]

    def transcribe(self, audio_path: str, *, language: str | None = None,
                   progress: Callable[[int, str], None] | None = None,
                   model_size: str = "large-v3", initial_prompt: str | None = None,
                   **opts) -> ASRResult:
        ok, reason = self.available()
        if not ok:
            raise EngineUnavailable(reason)

        def _p(pct: int, msg: str):
            if progress:
                progress(pct, msg)

        _p(5, f"加载 whisper {model_size}…")
        model = self._load(model_size)

        _p(35, "识别中…")
        t0 = time.time()
        segs, info = model.transcribe(
            audio_path,
            language=language or None,
            beam_size=5,
            vad_filter=True,
            word_timestamps=False,
            initial_prompt=initial_prompt or None,
        )
        segments = []
        for s in segs:
            text = (s.text or "").strip()
            if text:
                segments.append({
                    "start": round(float(s.start), 3),
                    "end": round(float(s.end), 3),
                    "text": text,
                })
        elapsed = time.time() - t0

        _p(90, f"得到 {len(segments)} 句")
        return ASRResult(
            engine=self.name,
            segments=segments,
            language=info.language,
            duration=float(info.duration),
            elapsed=elapsed,
            meta={"model": model_size, "lang_prob": round(info.language_probability, 3)},
        )


register(FasterWhisperEngine())
