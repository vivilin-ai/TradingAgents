"""Serial job queue for the Telegram bot.

Analysis jobs are expensive and call shared LLM APIs with rate limits, so
they run one at a time.  The queue feeds a single daemon thread; callers
get a (job_id, queue_position) back immediately and results arrive via an
on_complete callback.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: int
    description: str          # human-readable, e.g. "NVDA 2026-05-30"
    func: Callable[[], Any]   # zero-arg callable that runs the analysis
    on_complete: Callable[["Job", Any, Optional[Exception]], None]
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None


class JobQueue:
    """Thread-safe serial job queue.

    Usage::

        q = JobQueue()
        q.start()
        job_id, pos = q.add("NVDA 2026-05-30", my_func, my_callback)
        # ... later
        q.stop()
    """

    def __init__(self) -> None:
        self._queue: list[Job] = []
        self._current: Optional[Job] = None
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._next_id = 1

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="job-queue")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._event.set()

    # ── Queue management ──────────────────────────────────────────────────────

    def add(
        self,
        description: str,
        func: Callable[[], Any],
        on_complete: Callable[["Job", Any, Optional[Exception]], None],
    ) -> tuple[int, int]:
        """Enqueue a job.

        Returns:
            (job_id, queue_position) where position 0 means it will run next
            after the current job finishes.
        """
        with self._lock:
            job = Job(
                id=self._next_id,
                description=description,
                func=func,
                on_complete=on_complete,
            )
            self._next_id += 1
            self._queue.append(job)
            position = len(self._queue)
        self._event.set()
        return job.id, position

    def get_status(self) -> dict[str, Any]:
        """Return a snapshot of queue state suitable for /status replies."""
        with self._lock:
            current = self._current
            pending = list(self._queue)

        now = datetime.datetime.now()
        result: dict[str, Any] = {"current": None, "pending": []}

        if current:
            elapsed = (now - current.started_at).seconds if current.started_at else 0
            result["current"] = {
                "id": current.id,
                "description": current.description,
                "elapsed_s": elapsed,
            }

        for job in pending:
            result["pending"].append({"id": job.id, "description": job.description})

        return result

    # ── Worker ────────────────────────────────────────────────────────────────

    def _worker(self) -> None:
        while self._running:
            self._event.wait(timeout=1.0)
            self._event.clear()

            while True:
                with self._lock:
                    if not self._queue:
                        break
                    job = self._queue.pop(0)
                    job.started_at = datetime.datetime.now()
                    self._current = job

                logger.info("Starting job #%d: %s", job.id, job.description)
                result, error = None, None
                try:
                    result = job.func()
                except Exception as exc:
                    error = exc
                    logger.error("Job #%d failed: %s", job.id, exc, exc_info=True)
                finally:
                    job.completed_at = datetime.datetime.now()
                    with self._lock:
                        self._current = None

                try:
                    job.on_complete(job, result, error)
                except Exception as exc:
                    logger.warning("on_complete for job #%d raised: %s", job.id, exc)
