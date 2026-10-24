"""lyco-sub 命令行 —— 一等公民是 AI/脚本，人类也能用。

约定（这是给 agent 用的契约）：
- 进度/日志一律走 stderr，stdout 只放最终结果；
- --json 时 stdout 是一个 JSON 对象，字段稳定；
- 退出码：0 成功 / 1 运行失败 / 2 用法错误 / 3 引擎不可用 / 4 输入不存在；
- 所有命令都支持 --dry-run 先看会做什么。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core import media
from core.asr import EngineUnavailable, get_engine, list_engines
from core.config import Settings
from core.pipeline import JobSpec, run_job
from core.subtitles import cues_from_segments, metrics, read_srt, write_srt
from core.translate import TranslateError, get_translator, list_translators
from core.translate import llm as llm_module

EXIT_OK = 0
EXIT_RUN_FAIL = 1
EXIT_USAGE = 2
EXIT_ENGINE = 3
EXIT_NO_INPUT = 4


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for k, v in payload.items():
            if isinstance(v, (dict, list)):
                print(f"{k}: {json.dumps(v, ensure_ascii=False)}")
            else:
                print(f"{k}: {v}")


# ---------------- engines ----------------

def cmd_engines(args: argparse.Namespace) -> int:
    settings = Settings.load()
    llm_module.build(settings)
    data = {
        "asr": [e.describe() for e in list_engines()],
        "translators": [t.describe() for t in list_translators()],
    }
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK

    print("ASR 引擎:")
    for e in data["asr"]:
        mark = "OK  " if e["available"] else "OFF "
        print(f"  {mark}{e['name']:<10} {e['label']}")
        if not e["available"]:
            print(f"        原因: {e['reason']}")
        if e["notes"]:
            print(f"        说明: {e['notes']}")
    print("\n翻译器:")
    for t in data["translators"]:
        mark = "OK  " if t["available"] else "OFF "
        print(f"  {mark}{t['name']:<10} {t['label']}")
        if not t["available"]:
            print(f"        原因: {t['reason']}")
    return EXIT_OK


# ---------------- probe ----------------

def cmd_probe(args: argparse.Namespace) -> int:
    settings = Settings.load()
    if not Path(args.input).exists():
        _log(f"文件不存在: {args.input}")
        return EXIT_NO_INPUT
    try:
        info = media.probe(args.input, settings).as_dict()
    except media.MediaError as exc:
        _log(str(exc))
        return EXIT_RUN_FAIL
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"时长   : {info['duration']}s")
        print(f"分辨率 : {info['width']}x{info['height']} @ {info['fps']}fps")
        print(f"编码   : video={info['vcodec']} audio={info['acodec']}")
        print(f"音轨   : {'有' if info['has_audio'] else '无'}")
        print(f"体积   : {info['size'] / 1024 / 1024:.1f} MB")
    return EXIT_OK


# ---------------- transcribe ----------------

def cmd_transcribe(args: argparse.Namespace) -> int:
    settings = Settings.load()
    src = Path(args.input)
    if not src.exists():
        _log(f"文件不存在: {src}")
        return EXIT_NO_INPUT

    try:
        engine = get_engine(args.engine)
    except EngineUnavailable as exc:
        _log(str(exc))
        return EXIT_ENGINE

    ok, reason = engine.available()
    if not ok:
        _log(f"引擎不可用: {reason}")
        return EXIT_ENGINE

    out_dir = Path(args.out_dir) if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    wav = out_dir / f"{src.stem}.16k.wav"

    if args.dry_run:
        _emit({"would_extract": str(wav),
               "engine": args.engine,
               "output": str(out_dir / f"{src.stem}.{args.engine}.srt")}, args.json)
        return EXIT_OK

    _log("抽取音频…")
    try:
        media.extract_audio(src, wav, settings)
    except media.MediaError as exc:
        _log(str(exc))
        return EXIT_RUN_FAIL

    _log(f"识别中（{args.engine}）…")
    try:
        result = engine.transcribe(str(wav), language=args.language or None,
                                   progress=lambda p, m: _log(f"  [{p:3d}%] {m}"))
    except EngineUnavailable as exc:
        _log(f"引擎失败: {exc}")
        return EXIT_ENGINE
    except Exception as exc:  # noqa: BLE001
        _log(f"识别失败: {type(exc).__name__}: {exc}")
        return EXIT_RUN_FAIL

    cues = cues_from_segments(result.segments)
    srt_path = write_srt(cues, out_dir / f"{src.stem}.{args.engine}.srt")
    m = metrics(cues)

    payload = {
        "ok": True,
        "engine": result.engine,
        "language": result.language,
        "elapsed": round(result.elapsed, 2),
        "srt": str(srt_path),
        "cues": len(cues),
        "metrics": m,
        "segments": result.segments if args.include_segments else None,
    }
    if not args.include_segments:
        payload.pop("segments")
    _emit(payload, args.json)
    return EXIT_OK


# ---------------- translate ----------------

def cmd_translate(args: argparse.Namespace) -> int:
    settings = Settings.load()
    src = Path(args.input)
    if not src.exists():
        _log(f"文件不存在: {src}")
        return EXIT_NO_INPUT

    if args.translator == "llm":
        llm_module.build(settings)
    try:
        tr = get_translator(args.translator)
    except TranslateError as exc:
        _log(str(exc))
        return EXIT_ENGINE
    ok, reason = tr.available()
    if not ok:
        _log(f"翻译器不可用: {reason}")
        return EXIT_ENGINE

    cues = read_srt(src)
    if not cues:
        _log("字幕文件里没有解析到任何条目")
        return EXIT_RUN_FAIL

    if args.dry_run:
        _emit({"would_translate": len(cues), "to": args.to,
               "output": str(src.with_suffix(f".{args.to}.srt"))}, args.json)
        return EXIT_OK

    _log(f"翻译 {len(cues)} 条到 {args.to}…")
    try:
        got = tr.translate_batch([c.text for c in cues], args.to)
    except TranslateError as exc:
        _log(f"翻译失败: {exc}")
        return EXIT_RUN_FAIL

    from core.subtitles import Cue
    translated = [Cue(c.index, c.start, c.end, got[i] if i < len(got) else c.text)
                  for i, c in enumerate(cues)]
    out = src.with_suffix(f".{args.to}.srt")
    write_srt(translated, out)

    payload = {"ok": True, "out": str(out), "cues": len(translated), "to": args.to}
    _emit(payload, args.json)
    return EXIT_OK


# ---------------- run (full pipeline) ----------------

def cmd_run(args: argparse.Namespace) -> int:
    settings = Settings.load()
    src = Path(args.input)
    if not src.exists():
        _log(f"文件不存在: {src}")
        return EXIT_NO_INPUT

    out_dir = Path(args.out_dir) if args.out_dir else src.parent / f"{src.stem}.lycosub"
    spec = JobSpec(
        input_path=str(src),
        out_dir=str(out_dir),
        asr_engine=args.engine,
        language=args.language or None,
        translate_to=args.to or None,
        translator=args.translator,
        burn_mode=args.burn,
        quality=args.quality,
    )

    if args.dry_run:
        _emit({"input": str(src), "out_dir": str(out_dir),
               "asr_engine": spec.asr_engine, "translate_to": spec.translate_to,
               "burn_mode": spec.burn_mode, "quality": spec.quality}, args.json)
        return EXIT_OK

    result = run_job(spec, settings,
                     progress=lambda p, m: _log(f"[{p:3d}%] {m}"))

    if not result.ok:
        _log(f"失败: {result.error}")
        if result.trace:
            _log(result.trace)
        return EXIT_RUN_FAIL

    payload = {"ok": True, "outputs": result.outputs,
               "steps": [{"step": s["step"], "elapsed": s["elapsed"]} for s in result.steps]}
    _emit(payload, args.json)
    return EXIT_OK


# ---------------- serve ----------------

def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = Settings.load()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    if args.lan:
        settings.host = "0.0.0.0"
    _log(f"lyco-sub 服务: http://{settings.host}:{settings.port}")
    uvicorn.run("server:app", host=settings.host, port=settings.port, reload=False)
    return EXIT_OK


# ---------------- parser ----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lycosub",
        description="字幕生成工作台：转录 / 翻译 / 烧录。人类可用，AI 可脚本化。",
        epilog="示例: lycosub run demo.mp4 --engine funasr --to en --burn hard --json",
    )
    p.add_argument("--version", action="version", version="lyco-sub 0.1.0")
    sub = p.add_subparsers(dest="command", required=True)

    pe = sub.add_parser("engines", help="列出可用引擎及其状态")
    pe.add_argument("--json", action="store_true")
    pe.set_defaults(func=cmd_engines)

    pp = sub.add_parser("probe", help="探测媒体信息")
    pp.add_argument("input")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_probe)

    pt = sub.add_parser("transcribe", help="只转录，输出 SRT")
    pt.add_argument("input")
    pt.add_argument("--engine", default="funasr", help="funasr | whisper | jianying")
    pt.add_argument("--language", default="", help="zh / en / auto")
    pt.add_argument("--out-dir", default="")
    pt.add_argument("--include-segments", action="store_true", help="JSON 里带上逐句时间轴")
    pt.add_argument("--dry-run", action="store_true")
    pt.add_argument("--json", action="store_true")
    pt.set_defaults(func=cmd_transcribe)

    ptr = sub.add_parser("translate", help="翻译已有 SRT")
    ptr.add_argument("input")
    ptr.add_argument("--to", required=True, help="目标语言，如 en / ja / zh-Hans")
    ptr.add_argument("--translator", default="llm")
    ptr.add_argument("--dry-run", action="store_true")
    ptr.add_argument("--json", action="store_true")
    ptr.set_defaults(func=cmd_translate)

    pr = sub.add_parser("run", help="端到端：转录 → 翻译 → 烧录")
    pr.add_argument("input")
    pr.add_argument("--engine", default="funasr")
    pr.add_argument("--language", default="")
    pr.add_argument("--to", default="", help="目标语言，留空则不翻译")
    pr.add_argument("--translator", default="llm")
    pr.add_argument("--burn", default="none", choices=["none", "soft", "hard"])
    pr.add_argument("--quality", default="ultra", choices=["ultra", "high", "medium", "low"])
    pr.add_argument("--out-dir", default="")
    pr.add_argument("--dry-run", action="store_true")
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_run)

    ps = sub.add_parser("serve", help="启动 Web 服务")
    ps.add_argument("--host", default="")
    ps.add_argument("--port", type=int, default=0)
    ps.add_argument("--lan", action="store_true", help="监听 0.0.0.0，允许手机访问")
    ps.set_defaults(func=cmd_serve)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _log("已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
