"""In-memory background queue for GenXBot run creation jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Callable
from uuid import uuid4

from app.schemas import QueueJobStatusResponse, RunTaskRequest
from app.services.orchestrator import GenXBotOrchestrator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunQueueService:
    """Simple in-memory queue with one worker thread."""

    def __init__(self, orchestrator: GenXBotOrchestrator, worker_enabled: bool = True) -> None:
        self._orchestrator = orchestrator
        self._queue: Queue[tuple[str, RunTaskRequest]] = Queue()
        self._jobs: dict[str, QueueJobStatusResponse] = {}
        self._lock = Lock()
        self._stop_event = Event()
        self._worker: Thread | None = None

        if worker_enabled:
            self._worker = Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def enqueue_run(self, request: RunTaskRequest) -> QueueJobStatusResponse:
        job_id = f"job_{uuid4().hex[:10]}"
        job = QueueJobStatusResponse(job_id=job_id, status="queued")
        with self._lock:
            self._jobs[job_id] = job
        self._queue.put((job_id, request))
        return job

    def get_job(self, job_id: str) -> QueueJobStatusResponse | None:
        with self._lock:
            return self._jobs.get(job_id)

    def pending_count(self) -> int:
        return self._queue.qsize()

    def is_worker_alive(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    def _update_job(self, job_id: str, fn: Callable[[QueueJobStatusResponse], None]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            fn(job)
            job.updated_at = _now()
            self._jobs[job_id] = job

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job_id, request = self._queue.get(timeout=0.5)
            except Empty:
                continue

            self._update_job(job_id, lambda j: setattr(j, "status", "running"))
            try:
                run = self._orchestrator.create_run(request)
                self._update_job(
                    job_id,
                    lambda j: (setattr(j, "status", "completed"), setattr(j, "run", run)),
                )
            except Exception as exc:  # pragma: no cover - defensive fallback
                self._update_job(
                    job_id,
                    lambda j: (setattr(j, "status", "failed"), setattr(j, "error", str(exc))),
                )
            finally:
                self._queue.task_done()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1)
