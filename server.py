"""FastAPI 后端 —— 只提供服务，UI 由浏览器加载（与 rembg-ui 同构）。

设计原则：
- HTTP API 与 CLI 调的是同一个 core.pipeline，不存在两套逻辑；
- 每个 endpoint 都能被脚本/AI 直接调用，不依赖浏览器状态；
- 返回结构稳定，便于 agent 解析。
"""

from __future__ import annotations

import shutil
import uuid
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import media
from core.asr import list_engines
from core.config import Settings
from core.jobs import JobManager
from core.pipeline import JobSpec
from core.render.burn import QUALITY_CRF
from core.subtitles import metrics, read_srt
from core.translate import list_translators
from core.translate import llm as llm_module

settings = Settings.load()
llm_module.build(settings)
jobs = JobManager(settings)

FRONTEND = Path(__file__).parent / "frontend" / "index.html"

app = FastAPI(title="lyco-sub", version="0.1.0",
              description="字幕生成工作台 API — 转录 / 翻译 / 烧录")


@app.on_event("startup")
def _startup() -> None:
    jobs.start()


# ---------------- 能力发现 ----------------

@app.get("/api/capabilities")
def capabilities() -> dict:
    """一次拿到全部引擎状态，AI 用这个决定调什么。"""
    return {
        "asr": [e.describe() for e in list_engines()],
        "translators": [t.describe() for t in list_translators()],
        "qualities": list(QUALITY_CRF.keys()),
        "burn_modes": ["none", "soft", "hard"],
        "llm": {"model": settings.llm_model, "base": settings.llm_api_base,
                "configured": bool(settings.llm_api_key)},
    }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "data_dir": str(settings.data_dir)}


# ---------------- 媒体 ----------------

@app.post("/api/probe")
async def probe(file: UploadFile = File(...)) -> dict:
    """上传并探测媒体信息。"""
    dst = settings.uploads_dir / f"probe-{file.filename}"
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        return media.probe(dst, settings).as_dict()
    except media.MediaError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        dst.unlink(missing_ok=True)


# ---------------- 任务 ----------------

@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    asr_engine: str = Form("funasr"),
    language: str = Form(""),
    translate_to: str = Form(""),
    translator: str = Form("llm"),
    burn_mode: str = Form("none"),
    quality: str = Form("ultra"),
) -> dict:
    """上传视频并提交处理任务。"""
    job_id = uuid.uuid4().hex[:12]
    safe_name = Path(file.filename or "input.mp4").name
    dst = settings.uploads_dir / f"{job_id}-{safe_name}"
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    spec = JobSpec(
        input_path=str(dst),
        out_dir="",  # 交给 JobManager 按 job id 生成，保证 id 与产物目录一致
        asr_engine=asr_engine,
        language=language or None,
        translate_to=translate_to or None,
        translator=translator,
        burn_mode=burn_mode,
        quality=quality,
    )
    job = jobs.submit(spec, job_id=job_id)
    return {"job_id": job.id, "status": job.status}


@app.post("/api/jobs/by-path")
def create_job_by_path(payload: dict) -> dict:
    """直接给本地路径（桌面/CLI 场景，免上传）。"""
    path = payload.get("path", "")
    if not Path(path).exists():
        raise HTTPException(400, f"文件不存在: {path}")
    job_id = uuid.uuid4().hex[:12]
    spec = JobSpec(
        input_path=path,
        out_dir=str(settings.jobs_dir / job_id),
        asr_engine=payload.get("asr_engine", "funasr"),
        language=payload.get("language") or None,
        translate_to=payload.get("translate_to") or None,
        translator=payload.get("translator", "llm"),
        burn_mode=payload.get("burn_mode", "none"),
        quality=payload.get("quality", "ultra"),
    )
    job = jobs.submit(spec, job_id=job_id)
    return {"job_id": job.id, "status": job.status}


@app.get("/api/jobs")
def list_jobs() -> dict:
    return {"jobs": [j.public() for j in jobs.list()]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在")
    return job.public()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    return {"cancelled": jobs.cancel(job_id)}


@app.get("/api/jobs/{job_id}/download/{name}")
def download(job_id: str, name: str) -> FileResponse:
    path = settings.jobs_dir / job_id / name
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=path.name)


# ---------------- 字幕工具 ----------------

@app.post("/api/subtitles/metrics")
async def subtitle_metrics(file: UploadFile = File(...)) -> dict:
    """给一份 SRT 打质量分，用来对比引擎。"""
    raw = (await file.read()).decode("utf-8", errors="replace")
    from core.subtitles import parse_srt
    cues = parse_srt(raw)
    return {"cues": len(cues), "metrics": metrics(cues)}


# ---------------- 前端 ----------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    if not FRONTEND.exists():
        return HTMLResponse("<h1>lyco-sub</h1><p>前端未构建</p>")
    return HTMLResponse(FRONTEND.read_text(encoding="utf-8"))


if (Path(__file__).parent / "frontend").exists():
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "frontend")), name="static")


def main() -> None:
    import uvicorn

    url = f"http://{settings.host}:{settings.port}"
    print(f"lyco-sub 启动: {url}")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
