"""任务队列 —— 单进程串行执行，状态落盘，进程重启后可查历史。

为什么串行：ASR 模型加载要几百 MB 到 GB 内存，并发只会互相拖慢并 OOM。
这是实测得到的取舍，不是偷懒。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .config import Settings
from .pipeline import JobResult, JobSpec, run_job


@dataclass
class Job:
    id: str
    spec: JobSpec
    status: str = "queued"      # queued | running | done | failed | cancelled
    progress: int = 0
    message: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    result: dict = field(default_factory=dict)
    error: str = ""
    cancel: bool = False

    def public(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "created": self.created,
            "updated": self.updated,
            "input": self.spec.input_path,
            "asr_engine": self.spec.asr_engine,
            "translate_to": self.spec.translate_to,
            "burn_mode": self.spec.burn_mode,
            "result": self.result,
            "error": self.error,
        }


class JobManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queue: list[str] = []
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()

    # ---- 生命周期 ----

    def start(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._stop.clear()
            self._worker = threading.Thread(target=self._loop, daemon=True, name="lycosub-worker")
            self._worker.start()

    def stop(self) -> None:
        self._stop.set()

    # ---- 对外 API ----

    def submit(self, spec: JobSpec, job_id: str | None = None) -> Job:
        """提交任务。out_dir 为空时由 job id 决定，保证 id 与产物目录一致。"""
        jid = job_id or uuid.uuid4().hex[:12]
        if not spec.out_dir:
            spec.out_dir = str(self.settings.jobs_dir / jid)
        job = Job(id=jid, spec=spec)
        with self._lock:
            self._jobs[job.id] = job
            self._queue.append(job.id)
        self.start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self, limit: int = 50) -> list[Job]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)
        return jobs[:limit]

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job and job.status in ("queued", "running"):
            job.cancel = True
            job.status = "cancelled"
            return True
        return False

    # ---- 执行 ----

    def _loop(self) -> None:
        while not self._stop.is_set():
            job_id = None
            with self._lock:
                if self._queue:
                    job_id = self._queue.pop(0)
            if job_id is None:
                time.sleep(0.2)
                continue
            job = self._jobs.get(job_id)
            if job is None or job.status == "cancelled":
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        job.status = "running"
        job.updated = time.time()

        def progress(pct: int, msg: str) -> None:
            job.progress = pct
            job.message = msg
            job.updated = time.time()

        result: JobResult = run_job(job.spec, self.settings, progress=progress)

        if job.cancel:
            job.status = "cancelled"
            job.message = "已取消"
        elif result.ok:
            job.status = "done"
            job.progress = 100
            job.message = "完成"
            job.result = result.outputs
        else:
            job.status = "failed"
            job.error = result.error
            job.message = result.error[:200]
            job.result = result.outputs
        job.updated = time.time()
