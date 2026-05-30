"""Unit tests for the bot job queue."""

from __future__ import annotations

import time
import threading
from tradingagents.bot.queue import Job, JobQueue


def test_job_queue_basic():
    q = JobQueue()
    q.start()

    results = []
    done = threading.Event()

    def work():
        return 42

    def on_complete(job, result, error):
        results.append((result, error))
        done.set()

    job_id, pos = q.add("test job", work, on_complete)
    assert job_id == 1
    assert pos == 1

    done.wait(timeout=3)
    q.stop()

    assert results == [(42, None)]


def test_job_queue_error_isolation():
    q = JobQueue()
    q.start()

    outcomes = []
    all_done = threading.Event()

    def fail():
        raise ValueError("boom")

    def ok():
        return "ok"

    def cb(job, result, error):
        outcomes.append((result, error))
        if len(outcomes) == 2:
            all_done.set()

    q.add("fail", fail, cb)
    q.add("ok", ok, cb)

    all_done.wait(timeout=5)
    q.stop()

    assert len(outcomes) == 2
    # First job errored
    assert outcomes[0][1] is not None
    # Second job succeeded
    assert outcomes[1][0] == "ok"
    assert outcomes[1][1] is None


def test_queue_status():
    q = JobQueue()
    # Before starting, status should show no current job
    status = q.get_status()
    assert status["current"] is None
    assert status["pending"] == []


def test_queue_position():
    q = JobQueue()
    # Don't start worker — jobs pile up
    block = threading.Event()

    def slow():
        block.wait()
        return "slow"

    def fast():
        return "fast"

    def noop(job, result, error):
        pass

    id1, pos1 = q.add("slow", slow, noop)
    id2, pos2 = q.add("fast", fast, noop)

    assert pos1 == 1
    assert pos2 == 2
    block.set()
