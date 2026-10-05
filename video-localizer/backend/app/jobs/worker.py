import logging
import queue
import threading
from collections.abc import Callable
from typing import Protocol

from app.models.store import JobStore


class JobExecutor(Protocol):
    def submit(self, job_id: str, retry: bool = False) -> None: ...


class LocalWorker:
    def __init__(self, store: JobStore, process: Callable[[str], None]) -> None:
        self.store, self.process = store, process
        self.queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self.handlers: dict[str, Callable[[str], None]] = {}
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self.run, name="localizer-worker", daemon=True)
        self.closing = False

    def start(self) -> None:
        self.store.recover()
        self.thread.start()

    def submit(self, job_id: str, retry: bool = False) -> None:
        with self.lock:
            if self.closing:
                raise RuntimeError("Worker is shutting down")
            self.store.schedule(job_id, retry)
            self.queue.put(("job", job_id))

    def submit_task(self, kind: str, identifier: str) -> None:
        with self.lock:
            if self.closing or kind not in self.handlers:
                raise RuntimeError("Worker unavailable for this task")
            self.queue.put((kind, identifier))

    def run(self) -> None:
        while True:
            task = self.queue.get()
            try:
                if task is None:
                    return
                kind, job_id = task
                if kind != "job":
                    try:
                        self.handlers[kind](job_id)
                    except Exception:
                        logging.exception("Unhandled %s worker failure for %s", kind, job_id)
                    continue
                with self.lock:
                    job = self.store.claim(job_id)
                if job is not None:
                    try:
                        self.process(job_id)
                    except Exception as exc:
                        # Last-resort guard; pipeline normally captures and logs each failure.
                        logging.exception("Unhandled worker failure for %s", job_id)
                        self.store.fail(job_id, f"Worker failure: {type(exc).__name__}: {exc}")
            finally:
                self.queue.task_done()

    def close(self) -> None:
        with self.lock:
            self.closing = True
            self.queue.put(None)
        self.thread.join()  # Graceful shutdown preserves active source and finishes its job.
