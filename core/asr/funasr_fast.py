"""FunASR 快速引擎 —— 不加载标点模型，用 token 时间戳自建断句。

为什么要单独做一个引擎（实测数据）：

| 配置 | 加载耗时 | 有时间戳 |
|---|---|---|
| paraformer + vad + punc | 27–31s | ✅ |
| paraformer + vad（本引擎） | 4.6–5.2s | ✅（token 级） |
| SenseVoiceSmall | 3.7–4.1s | ❌ 只有 text，无法做字幕 |

结论：**punc 模型是启动慢的主因，而且它不是必需的**。
paraformer 的 generate() 在不开 punc 时仍返回 token 级 timestamp 数组，
自己按静音间隔切句即可，省掉 21–26 秒。

代价：没有标点符号。需要标点时用 funasr（完整版）或后置补标点。
"""

from __future__ import annotations

import time
from typing import Callable

from .base import ASREngine, ASRResult, EngineUnavailable, register

# 断句参数（可被 transcribe 的 opts 覆盖）
MAX_CHARS = 18      # 单行最大字数（CJK）
MAX_DUR = 6.0       # 单条最大时长（秒）
GAP_MS = 350        # 静音间隔超过此值就断句


class FunASRFastEngine(ASREngine):
    name = "funasr-fast"
    label = "FunASR 快速版（本地 / 无标点 / 5 秒就绪）"
    kind = "offline"
    needs = ("funasr", "modelscope", "torch")
    notes = ("不加载标点模型，加载从 31s 降到 5s。用 token 时间戳自建断句，"
             "输出无标点。适合桌面 app 快速出稿，需要标点时再用 funasr 完整版。")

    _model = None

    def _load(self):
        if FunASRFastEngine._model is None:
            from funasr import AutoModel

            FunASRFastEngine._model = AutoModel(
                model="paraformer-zh",
                vad_model="fsmn-vad",
                # 关键：不传 punc_model
                disable_update=True,
                hub="ms",
            )
        return FunASRFastEngine._model

    def transcribe(self, audio_path: str, *, language: str | None = None,
                   progress: Callable[[int, str], None] | None = None,
                   max_chars: int = MAX_CHARS, max_dur: float = MAX_DUR,
                   gap_ms: int = GAP_MS, **opts) -> ASRResult:
        ok, reason = self.available()
        if not ok:
            raise EngineUnavailable(reason)

        def _p(pct: int, msg: str):
            if progress:
                progress(pct, msg)

        _p(5, "加载 FunASR 快速模型…")
        model = self._load()

        _p(40, "识别中…")
        t0 = time.time()
        raw = model.generate(input=audio_path, batch_size_s=300)
        elapsed = time.time() - t0

        item = raw[0] if raw else {}
        tokens = [t for t in (item.get("text") or "").split(" ") if t]
        stamps = item.get("timestamp") or []

        if not tokens:
            return ASRResult(engine=self.name, segments=[], language="zh", elapsed=elapsed)
        if len(tokens) != len(stamps):
            # 对不齐就退化成整段一条，宁可粗糙也不输出错位时间轴
            seg = {"start": round(stamps[0][0] / 1000, 3),
                   "end": round(stamps[-1][1] / 1000, 3),
                   "text": "".join(tokens)}
            return ASRResult(engine=self.name, segments=[seg], language="zh",
                             elapsed=elapsed,
                             meta={"warning": f"token/stamp 不齐: {len(tokens)}/{len(stamps)}"})

        _p(75, "断句中…")
        segments: list[dict] = []
        cur: list[str] = []
        start: int | None = None
        end: int = 0

        def flush() -> None:
            nonlocal cur, start, end
            text = "".join(cur).strip()
            if text and start is not None:
                segments.append({"start": round(start / 1000, 3),
                                 "end": round(end / 1000, 3),
                                 "text": text})
            cur, start = [], None

        for tok, (s, e) in zip(tokens, stamps):
            if start is None:
                start, end = s, e
                cur = [tok]
                continue
            gap = s - end
            chars = sum(len(c) for c in cur)
            dur = (e - start) / 1000
            if gap >= gap_ms or chars >= max_chars or dur >= max_dur:
                flush()
                start, end = s, e
                cur = [tok]
            else:
                cur.append(tok)
                end = e
        flush()

        _p(92, f"得到 {len(segments)} 句")
        return ASRResult(
            engine=self.name,
            segments=segments,
            language="zh",
            duration=segments[-1]["end"] if segments else 0.0,
            elapsed=elapsed,
            meta={"tokens": len(tokens), "no_punctuation": True,
                  "model": "paraformer-zh + fsmn-vad (no punc)"},
        )


register(FunASRFastEngine())
