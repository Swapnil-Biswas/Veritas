"""
Durable job worker.

N asyncio workers poll the SQLite queue. Each claim carries a lease; results are
written back only while the lease is still held (see store.py), so a job is delivered
at most once even if a worker stalls, the process restarts, or a lease expires and
the job is re-claimed. Retryable failures (timeouts, unexpected agent exceptions) are
re-queued with linear backoff until max_attempts; everything else fails immediately.
"""

import asyncio
import logging
from typing import List, Optional

from app.adapter import AdapterError, ClarificationRequired, VeritasAgentAdapter
from app.store import JobStore, LeaseLost

log = logging.getLogger("veritas.worker")


class JobWorker:
    def __init__(
        self,
        store: JobStore,
        adapter: VeritasAgentAdapter,
        *,
        concurrency: int,
        poll_seconds: float,
        lease_seconds: float,
        retry_backoff_seconds: float,
    ):
        self.store = store
        self.adapter = adapter
        self.concurrency = max(1, concurrency)
        self.poll_seconds = poll_seconds
        self.lease_seconds = lease_seconds
        self.retry_backoff_seconds = retry_backoff_seconds
        self._tasks: List[asyncio.Task] = []
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self._stopping.clear()
        self._tasks = [asyncio.create_task(self._loop(i), name=f"veritas-worker-{i}") for i in range(self.concurrency)]

    async def stop(self) -> None:
        self._stopping.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    @property
    def running(self) -> bool:
        return any(not t.done() for t in self._tasks)

    async def _loop(self, idx: int) -> None:
        while not self._stopping.is_set():
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Database unavailable or similar: back off and keep the worker alive.
                log.exception("worker %d: queue poll failed", idx)
                processed = False
            if not processed:
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self.poll_seconds)
                except asyncio.TimeoutError:
                    pass

    # -------------------------------------------------------------- one job

    async def run_once(self) -> bool:
        """Claims and processes at most one job. Returns True if a job was processed."""
        job = await asyncio.to_thread(self.store.claim_next, self.lease_seconds)
        if not job:
            return False
        await self._process(job)
        return True

    async def _process(self, job: dict) -> None:
        job_id, token, attempt = job["job_id"], job["lease_token"], job["attempts"]
        identity = self.adapter.identity
        log.info("job %s: running (attempt %d/%d)", job_id, attempt, job["max_attempts"])
        try:
            result = await self.adapter.run(job["brief"])
            await asyncio.to_thread(
                self.store.mark_delivered, job_id, token,
                outcome=result.outcome, report=result.report, sources=result.sources,
                source_details=result.source_details, limitations=result.limitations,
                clarification_questions=result.clarification_questions, retrieved_at=result.retrieved_at,
                agent_id=result.agent_id, agent_version=result.agent_version,
            )
            log.info("job %s: delivered (%d sources)", job_id, len(result.sources))
        except ClarificationRequired as e:
            await self._fail(job_id, token, e.code, e.public_message,
                             limitations=e.limitations, questions=e.questions, identity=identity)
        except AdapterError as e:
            if e.retryable and attempt < job["max_attempts"]:
                delay = self.retry_backoff_seconds * attempt
                log.warning("job %s: %s, retrying in %.0fs", job_id, e.code, delay)
                await self._guard(self.store.schedule_retry, job_id, token,
                                  code=e.code, message=e.public_message, delay_seconds=delay)
            else:
                await self._fail(job_id, token, e.code, e.public_message, identity=identity)
        except LeaseLost:
            log.warning("job %s: lease lost before delivery; result discarded", job_id)
        except Exception:
            log.exception("job %s: unexpected worker error", job_id)
            await self._fail(job_id, token, "RESEARCH_EXECUTION_FAILED", "The research job could not be completed.",
                             identity=identity)

    async def _fail(self, job_id: str, token: str, code: str, message: str, *,
                    limitations: Optional[list] = None, questions: Optional[list] = None,
                    identity: Optional[dict] = None) -> None:
        log.info("job %s: failed (%s)", job_id, code)
        await self._guard(self.store.mark_failed, job_id, token, code=code, message=message,
                          limitations=limitations, clarification_questions=questions,
                          agent_id=(identity or {}).get("agent_id"), agent_version=(identity or {}).get("version"))

    async def _guard(self, fn, *args, **kwargs) -> None:
        try:
            await asyncio.to_thread(fn, *args, **kwargs)
        except LeaseLost:
            log.warning("job %s: lease lost; state change skipped", args[0])
