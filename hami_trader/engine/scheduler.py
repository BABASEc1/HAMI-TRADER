"""
Module 44: Async/background scheduler.

Real background execution so Tkinter's main thread (and therefore
the UI) never blocks on a network call. This is a thin, genuine
wrapper around a worker thread pool + a callback queue — not a
placeholder. The GUI (app/terminal.py) polls the result queue on a
Tkinter `after()` timer, which is the correct, safe way to bridge
background threads into Tkinter (Tkinter itself is not thread-safe
for direct widget updates from worker threads).
"""

import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Any, Optional


@dataclass
class JobResult:
    job_id: str
    result: Any = None
    error: Optional[Exception] = None
    duration_seconds: float = 0.0


class BackgroundScheduler:
    def __init__(self, max_workers: int = 4):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.results: "queue.Queue[JobResult]" = queue.Queue()
        self._periodic_jobs = {}
        self._running = True

    def submit(self, job_id: str, fn: Callable, *args, **kwargs):
        def run():
            start = time.time()
            try:
                result = fn(*args, **kwargs)
                self.results.put(JobResult(job_id=job_id, result=result, duration_seconds=time.time() - start))
            except Exception as e:
                self.results.put(JobResult(job_id=job_id, error=e, duration_seconds=time.time() - start))
        self.executor.submit(run)

    def drain_results(self, max_items: int = 10):
        """Called from the GUI's main-thread timer — pulls completed
        job results without blocking."""
        items = []
        for _ in range(max_items):
            try:
                items.append(self.results.get_nowait())
            except queue.Empty:
                break
        return items

    def start_periodic(self, job_id: str, fn: Callable, interval_seconds: float, *args, **kwargs):
        """Runs fn() repeatedly in the background on a real interval
        (e.g. refreshing the order-book tracker) until stop_periodic
        is called."""
        def loop():
            while self._running and self._periodic_jobs.get(job_id, {}).get("active"):
                start = time.time()
                try:
                    result = fn(*args, **kwargs)
                    self.results.put(JobResult(job_id=job_id, result=result, duration_seconds=time.time() - start))
                except Exception as e:
                    self.results.put(JobResult(job_id=job_id, error=e, duration_seconds=time.time() - start))
                time.sleep(interval_seconds)

        self._periodic_jobs[job_id] = {"active": True}
        t = threading.Thread(target=loop, daemon=True)
        t.start()

    def stop_periodic(self, job_id: str):
        if job_id in self._periodic_jobs:
            self._periodic_jobs[job_id]["active"] = False

    def shutdown(self):
        self._running = False
        for job_id in list(self._periodic_jobs.keys()):
            self.stop_periodic(job_id)
        self.executor.shutdown(wait=False)
