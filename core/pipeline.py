"""端到端管线 —— CLI / HTTP / Web 都调这一个入口。

顺序：探针 → 抽音频 → ASR → (翻译) → 落盘 → (合成)
每一步都上报进度，失败时保留已完成产物，方便断点续跑。
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import media
from .asr import EngineUnavailable, get_engine
from .config import Settings
from .render import BurnOptions, burn, embed_soft
from .subtitles import Cue, cues_from_segments, metrics, write_srt
from .translate import get_translator
from .translate import llm as llm_module


@dataclass
class JobSpec:
    input_path: str
    out_dir: str
    asr_engine: str = "funasr"
    language: str | None = None
    translate_to: str | None = None
    translator: str = "llm"
    burn_mode: str = "none"        # none | soft | hard
    quality: str = "ultra"
    asr_opts: dict = field(default_factory=dict)


@dataclass
class JobResult:
    ok: bool
    steps: list[dict] = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    error: str = ""
    trace: str = ""


def run_job(spec: JobSpec, settings: Settings,
            progress: Callable[[int, str], None] | None = None) -> JobResult:
    def _p(pct: int, msg: str):
        if progress:
            progress(max(0, min(100, int(pct))), msg)

    steps: list[dict] = []
    outputs: dict = {}
    out_dir = Path(spec.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(spec.input_path).stem
    started = time.time()

    def step(name: str, fn):
        t0 = time.time()
        detail = fn()
        steps.append({"step": name, "ok": True, "elapsed": round(time.time() - t0, 2),
                      "detail": detail})
        return detail

    try:
        _p(2, "探测媒体信息…")
        info = step("probe", lambda: media.probe(spec.input_path, settings).as_dict())

        if not info.get("has_audio"):
            return JobResult(False, steps, outputs, "该文件没有音轨，无法转录")

        _p(6, "抽取音频…")
        wav = out_dir / f"{stem}.16k.wav"
        step("extract_audio", lambda: str(media.extract_audio(spec.input_path, wav, settings)))

        _p(12, f"启动 ASR 引擎: {spec.asr_engine}")
        engine = get_engine(spec.asr_engine)

        def _asr():
            res = engine.transcribe(
                str(wav),
                language=spec.language,
                progress=lambda p, m: _p(12 + int(p * 0.55), m),
                **spec.asr_opts,
            )
            return res

        asr_result = step("asr", _asr)
        cues: list[Cue] = cues_from_segments(asr_result.segments)
        if not cues:
            return JobResult(False, steps, outputs, "ASR 未识别到任何语音内容")

        src_srt = write_srt(cues, out_dir / f"{stem}.{spec.asr_engine}.srt")
        outputs["source_srt"] = str(src_srt)
        outputs["source_metrics"] = metrics(cues)
        steps.append({"step": "write_source_srt", "ok": True, "elapsed": 0.0,
                      "detail": {"path": str(src_srt), "cues": len(cues)}})

        if spec.translate_to:
            _p(70, f"翻译到 {spec.translate_to}…")

            def _translate():
                if spec.translator == "llm":
                    llm_module.build(settings)
                tr = get_translator(spec.translator)
                texts = [c.text for c in cues]
                got = tr.translate_batch(texts, spec.translate_to, spec.language)
                translated = [
                    Cue(c.index, c.start, c.end, (got[i] if i < len(got) else c.text))
                    for i, c in enumerate(cues)
                ]
                p = write_srt(translated, out_dir / f"{stem}.{spec.translate_to}.srt")
                bilingual = [
                    Cue(c.index, c.start, c.end, f"{c.text}\n{translated[i].text}")
                    for i, c in enumerate(cues)
                ]
                pb = write_srt(bilingual, out_dir / f"{stem}.bilingual.srt")
                return {"translated": str(p), "bilingual": str(pb), "lines": len(translated)}

            tr_detail = step("translate", _translate)
            outputs["translated_srt"] = tr_detail["translated"]
            outputs["bilingual_srt"] = tr_detail["bilingual"]

        if spec.burn_mode in ("soft", "hard"):
            _p(85, f"合成视频（{spec.burn_mode}）…")
            use_sub = outputs.get("bilingual_srt") or outputs.get("translated_srt") or outputs.get("source_srt")
            target = out_dir / f"{stem}.{spec.burn_mode}.mp4"
            opts = BurnOptions(mode=spec.burn_mode, quality=spec.quality)

            def _render():
                if spec.burn_mode == "hard":
                    burn(spec.input_path, use_sub, target, opts, settings)
                else:
                    embed_soft(spec.input_path, use_sub, target, opts, settings)
                return {"path": str(target), "size": target.stat().st_size,
                        "subtitle": use_sub}

            r = step("render", _render)
            outputs["video"] = r["path"]

        _p(100, "完成")
        return JobResult(True, steps, outputs)

    except (EngineUnavailable, Exception) as exc:  # noqa: BLE001 — 管线要吞掉所有异常并回报
        return JobResult(False, steps, outputs, f"{type(exc).__name__}: {exc}",
                         traceback.format_exc())
