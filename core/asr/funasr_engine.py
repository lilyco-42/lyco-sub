"""FunASR paraformer-zh —— 本地离线、带标点、CPU 极快（实测 RTF 0.052）。"""

from __future__ import annotations

import time
from typing import Callable

from .base import ASREngine, ASRResult, EngineUnavailable, register


class FunASREngine(ASREngine):
    name = "funasr"
    label = "FunASR paraformer-zh（本地 / 带标点 / 最快）"
    kind = "offline"
    needs = ("funasr", "modelscope", "torch")
    notes = "阿里达摩院开源，MIT。中文识别+标点一体，CPU 即可跑，首次需下载约 1GB 模型。"

    _model = None  # 进程内复用，避免重复加载

    def _load(self):
        if FunASREngine._model is None:
            from funasr import AutoModel

            FunASREngine._model = AutoModel(
                model="paraformer-zh",
                vad_model="fsmn-vad",
                punc_model="ct-punc",
                disable_update=True,
                hub="ms",
            )
        return FunASREngine._model

    def transcribe(self, audio_path: str, *, language: str | None = None,
                   progress: Callable[[int, str], None] | None = None,
                   **opts) -> ASRResult:
        ok, reason = self.available()
        if not ok:
            raise EngineUnavailable(reason)

        def _p(pct: int, msg: str):
            if progress:
                progress(pct, msg)

        _p(5, "加载 FunASR 模型…")
        model = self._load()

        _p(35, "识别中…")
        t0 = time.time()
        raw = model.generate(input=audio_path, batch_size_s=300, sentence_timestamp=True)
        elapsed = time.time() - t0

        item = raw[0] if raw else {}
        sentences = item.get("sentence_info") or []

        segments = []
        for s in sentences:
            text = (s.get("text") or "").strip()
            if not text:
                continue
            segments.append({
                "start": round(float(s["start"]) / 1000.0, 3),
                "end": round(float(s["end"]) / 1000.0, 3),
                "text": text,
            })

        _p(90, f"得到 {len(segments)} 句")
        return ASRResult(
            engine=self.name,
            segments=segments,
            language="zh",
            duration=segments[-1]["end"] if segments else 0.0,
            elapsed=elapsed,
            meta={"sentences": len(sentences), "model": "paraformer-zh + ct-punc"},
        )


register(FunASREngine())
