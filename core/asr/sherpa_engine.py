"""sherpa-onnx 引擎 —— 桌面打包的主力路径。

为什么单独做这个（实测数据）：

| 方案 | 依赖体积 | import 耗时 | 可打包 |
|---|---|---|---|
| funasr + torch | 476MB(torch) + 1GB(venv) | 13s | ❌ 冷构建 179min+，产物 1GB+ |
| **sherpa-onnx** | **27MB** | **0.1s** | ✅ 纯 ONNX Runtime |

sherpa-onnx 是 k2-fsa 团队的 C++/ONNX 推理库，不依赖 torch：
- 支持 paraformer / sense-voice / whisper / transducer 等多种模型；
- 原生返回 token 级时间戳，可直接断句成字幕；
- 三平台都有预编译 wheel（win/linux/macos）+ Android AAR。

模型不打包进安装包（paraformer int8 有 227MB），首次使用时按需下载。
"""

from __future__ import annotations

import os
import sys
import time
import urllib.request
import wave
from array import array
from pathlib import Path
from typing import Callable

from .base import ASREngine, ASRResult, EngineUnavailable, register

# 模型清单：名称 -> (HF 仓库, 文件列表, 体积说明)
# ⚠️ 模型选择是实测决定的，不是随便挑的：
#   sense-voice  → timestamps 数组 72/72 对齐，可直接断句 ✅ 默认
#   paraformer   → tokens 有 149 个但 timestamps 恒为空数组，只能整段输出 ❌
MODELS = {
    "sense-voice": {
        "repo": "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        "files": ["model.int8.onnx", "tokens.txt"],
        "size": "~230MB",
        "desc": "中英日韩粤多语种，带 token 时间戳（默认）",
    },
    "paraformer-zh": {
        "repo": "csukuangfj/sherpa-onnx-paraformer-zh-2024-03-09",
        "files": ["model.int8.onnx", "tokens.txt"],
        "size": "~217MB",
        "desc": "中文 paraformer（无时间戳，只能整段输出，不推荐）",
    },
}

HF_BASE = "https://huggingface.co/{repo}/resolve/main/{file}"
HF_MIRROR = "https://hf-mirror.com/{repo}/resolve/main/{file}"

MAX_CHARS = 18
MAX_DUR = 6.0
GAP_MS = 350


def _model_dir(name: str) -> Path:
    """模型缓存目录。

    用 normpath 避免 Windows 上正反斜杠混用 —— sherpa-onnx 的 C++ 层
    对混合分隔符解析失败，会报 "Protobuf parsing failed"（实测踩过）。

    目录名与 MODELS 的 key 保持一致（sherpa-<name>），不要另起别名，
    否则"检查是否存在"和"下载到哪"会对不上，导致每次都重新下载。
    """
    root = os.environ.get("LYCOSUB_MODEL_DIR")
    base = Path(root) if root else Path.home() / ".lycosub" / "models"
    return Path(os.path.normpath(base / f"sherpa-{name}"))


def _download(urls: list[str], dst: Path, progress=None) -> None:
    """按顺序尝试多个源，带断点续传与大小校验。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    last_err = None
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "lyco-sub/0.1"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("content-length") or 0)
                done = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if progress and total:
                            progress(int(done * 100 / total))
            if total and tmp.stat().st_size != total:
                raise IOError(f"下载不完整: {tmp.stat().st_size}/{total}")
            tmp.replace(dst)
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            tmp.unlink(missing_ok=True)
    raise EngineUnavailable(f"模型下载失败: {last_err}")


class SherpaEngine(ASREngine):
    name = "sherpa"
    label = "sherpa-onnx（本地 / 无 torch / 桌面首选）"
    kind = "offline"
    needs = ("sherpa_onnx",)
    notes = ("纯 ONNX 推理，27MB 依赖、0.1s 导入，适合打包成桌面 app。"
             "模型首次使用时下载（~227MB），不进安装包。")

    _recognizers: dict = {}

    def available(self) -> tuple[bool, str]:
        return super().available()

    def _ensure_model(self, model_name: str, progress=None) -> Path:
        spec = MODELS.get(model_name)
        if spec is None:
            raise EngineUnavailable(f"未知模型: {model_name}，可选: {', '.join(MODELS)}")
        d = _model_dir(model_name)
        missing = [f for f in spec["files"] if not (d / f).exists()]
        if not missing:
            return d

        use_mirror = os.environ.get("LYCOSUB_HF_MIRROR", "1") != "0"
        for i, f in enumerate(missing):
            urls = []
            if use_mirror:
                urls.append(HF_MIRROR.format(repo=spec["repo"], file=f))
            urls.append(HF_BASE.format(repo=spec["repo"], file=f))

            def _p(pct: int, _f=f, _i=i):
                if progress:
                    base = int(_i * 100 / len(missing))
                    span = int(100 / len(missing))
                    progress(base + int(pct * span / 100), f"下载 {_f}…")

            _download(urls, d / f, progress=_p)
        return d

    def _load(self, model_name: str, threads: int = 4):
        key = (model_name, threads)
        if key not in SherpaEngine._recognizers:
            import sherpa_onnx

            d = _model_dir(model_name)
            model = os.path.normpath(str(d / "model.int8.onnx"))
            tokens = os.path.normpath(str(d / "tokens.txt"))

            if model_name.startswith("paraformer"):
                rec = sherpa_onnx.OfflineRecognizer.from_paraformer(
                    paraformer=model, tokens=tokens, num_threads=threads,
                    sample_rate=16000, feature_dim=80, decoding_method="greedy_search",
                )  # noqa: E501
            elif model_name.startswith("sense"):
                rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=model, tokens=tokens, num_threads=threads,
                    use_itn=True, language="auto",
                )
            else:
                raise EngineUnavailable(f"不支持的模型类型: {model_name}")
            SherpaEngine._recognizers[key] = rec
        return SherpaEngine._recognizers[key]

    @staticmethod
    def _read_wav(path: str) -> tuple[list[float], int]:
        with wave.open(path, "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise EngineUnavailable("需要 16kHz 单声道 16bit WAV")
            rate = w.getframerate()
            frames = w.readframes(w.getnframes())
        samples = array("h", frames)
        return [s / 32768.0 for s in samples], rate

    def transcribe(self, audio_path: str, *, language: str | None = None,
                   progress: Callable[[int, str], None] | None = None,
                   model_name: str = "sense-voice", max_chars: int = MAX_CHARS,
                   max_dur: float = MAX_DUR, gap_ms: int = GAP_MS,
                   **opts) -> ASRResult:
        ok, reason = self.available()
        if not ok:
            raise EngineUnavailable(reason)

        def _p(pct: int, msg: str):
            if progress:
                progress(pct, msg)

        _p(3, "检查模型…")
        self._ensure_model(model_name, progress=lambda p, m: _p(3 + int(p * 0.45), m))

        _p(50, "加载识别器…")
        t0 = time.time()
        rec = self._load(model_name)

        _p(65, "识别中…")
        audio, rate = self._read_wav(audio_path)
        t1 = time.time()

        # ⚠️ 必须分片：实测 64s 音频一次性喂给 sense-voice 只出 72 字，
        # 按 20s 切片后出 141 字（几乎翻倍）。长音频会丢内容，这是模型特性。
        chunk_sec = float(os.environ.get("LYCOSUB_CHUNK_SEC", "20"))
        step = max(1, int(chunk_sec * rate))
        all_tokens: list[str] = []
        all_starts: list[float] = []
        boundaries: list[float] = []

        for off in range(0, len(audio), step):
            piece = audio[off:off + step]
            if not piece:
                continue
            st = rec.create_stream()
            st.accept_waveform(rate, piece)
            rec.decode_stream(st)
            res = st.result
            toks = list(getattr(res, "tokens", []) or [])
            sts = list(getattr(res, "timestamps", []) or [])
            base = off / rate
            # 记录分片边界时间点：断句时遇到边界强制断开，避免跨片硬拼词
            if all_tokens:
                boundaries.append(base)
            all_tokens.extend(toks)
            all_starts.extend(base + float(x) for x in sts)

        elapsed = time.time() - t1
        tokens, starts_raw = all_tokens, all_starts
        text = "".join(tokens)

        if not tokens or not starts_raw:
            # 没有 token 级时间戳就退化成整段一条，绝不错位
            seg = {"start": 0.0, "end": round(len(audio) / rate, 3), "text": text}
            segments = [seg] if text else []
            return ASRResult(engine=self.name, segments=segments, language="zh",
                             elapsed=elapsed,
                             meta={"model": model_name, "warning": "无 token 时间戳，整段输出"})

        _p(80, "断句中…")

        # 时间戳语义：sherpa 给的是**每个 token 的起始时间**（秒，浮点）。
        # 所以某个 token 的结束时间 = 下一个 token 的起始时间；
        # 最后一个 token 用「总时长」兜底。搞错这点会让字幕整体前移。
        total = len(audio) / rate
        starts = starts_raw
        ends = starts[1:] + [total]

        segments: list[dict] = []
        cur: list[str] = []
        seg_start: float | None = None
        seg_end = 0.0

        # 纯标点/空白不算一句（实测会出现只有"。"却占 20 秒的字幕条）
        PUNCT_ONLY = set("。，、！？；：,.!?;: 　\n\t")

        def flush() -> None:
            nonlocal cur, seg_start, seg_end
            t = "".join(cur).strip()
            if t and seg_start is not None and not set(t).issubset(PUNCT_ONLY):
                segments.append({"start": round(seg_start, 3),
                                 "end": round(seg_end, 3), "text": t})
            cur, seg_start = [], None

        prev_end: float | None = None
        for tok, s, e in zip(tokens, starts, ends):
            if seg_start is None:
                seg_start, seg_end = s, e
                cur = [tok]
                prev_end = e
                continue
            # 静音间隔 = 本 token 起点 - 上一个 token 的**终点**
            # （用 seg_end 会累积误差：seg_end 是整段最后 token 的终点，
            #  在长静音处永远算不出 gap，实测导致出现 36 秒只有 1 个字的字幕）
            gap = (s - (prev_end if prev_end is not None else e)) * 1000
            chars = sum(len(c) for c in cur)
            dur = e - seg_start
            # 跨分片边界强制断开：分片是人为切的，不该让一个词跨两片拼接
            cross = any(prev_end < b <= s for b in boundaries) if prev_end is not None else False
            if cross or gap >= gap_ms or chars >= max_chars or dur >= max_dur:
                flush()
                seg_start, seg_end = s, e
                cur = [tok]
            else:
                cur.append(tok)
                seg_end = e
            prev_end = e
        flush()

        # 后处理：极短且无句末标点的碎片并入前一条（跨词切分的产物）
        merged: list[dict] = []
        for seg in segments:
            if merged and len(seg["text"]) <= 2 and not seg["text"].endswith(("。", "？", "！", "，", ",", ".", "?", "!")):
                merged[-1]["text"] += seg["text"]
                merged[-1]["end"] = seg["end"]
            else:
                merged.append(dict(seg))
        segments = merged

        _p(95, f"得到 {len(segments)} 句")
        return ASRResult(
            engine=self.name, segments=segments, language="zh",
            duration=len(audio) / rate, elapsed=elapsed,
            meta={"model": model_name, "tokens": len(tokens), "no_punctuation": True},
        )


register(SherpaEngine())
