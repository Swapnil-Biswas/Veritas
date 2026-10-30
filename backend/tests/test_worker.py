"""Worker reliability: delivery, retries, exhaustion, clarification, restart recovery, DB outage."""

import asyncio
import os
import tempfile
import time
import unittest
from unittest import mock

from agent.schemas.output import ResearchReportOutput, ResearchStatus
from app.adapter import VeritasAgentAdapter
from app.store import JobStore
from app.worker import JobWorker
from tests.helpers import ScriptedRunner, runner_sleeping, success_output


def make(runner, *, max_attempts=3, timeout=5, lease=60):
    store = JobStore(os.path.join(tempfile.mkdtemp(prefix="veritas-worker-"), "jobs.db"))
    adapter = VeritasAgentAdapter(timeout_seconds=timeout, runner=runner)
    worker = JobWorker(store, adapter, concurrency=1, poll_seconds=0.01, lease_seconds=lease, retry_backoff_seconds=0)
    return store, worker


def submit(store, n=1, max_attempts=3):
    return store.create_or_get(f"order-w{n}", "Research brief text", f"key-w{n}", max_attempts)[0]["job_id"]


class TestWorker(unittest.TestCase):
    def test_success_is_delivered_with_report_and_sources(self):
        store, worker = make(ScriptedRunner(success_output()))
        job_id = submit(store)
        self.assertTrue(asyncio.run(worker.run_once()))
        row = store.get(job_id)
        self.assertEqual(row["status"], "delivered")
        self.assertIn("https://example.org/doc", row["sources_json"])
        self.assertEqual(row["agent_version"], "1.0.0")

    def test_transient_failure_is_retried_then_delivered(self):
        runner = ScriptedRunner(RuntimeError("network blip"), success_output())
        store, worker = make(runner)
        job_id = submit(store)
        asyncio.run(worker.run_once())
        self.assertEqual(store.get(job_id)["status"], "queued")
        asyncio.run(worker.run_once())
        row = store.get(job_id)
        self.assertEqual((row["status"], row["attempts"], runner.calls), ("delivered", 2, 2))

    def test_retries_stop_at_max_attempts(self):
        store, worker = make(ScriptedRunner(RuntimeError("down")))
        job_id = submit(store, max_attempts=2)
        asyncio.run(worker.run_once())
        asyncio.run(worker.run_once())
        self.assertFalse(asyncio.run(worker.run_once()))
        row = store.get(job_id)
        self.assertEqual((row["status"], row["error_code"]), ("failed", "RESEARCH_EXECUTION_FAILED"))

    def test_timeout_then_failure_is_recorded(self):
        store, worker = make(runner_sleeping(1), timeout=0.02)
        job_id = submit(store, max_attempts=1)
        asyncio.run(worker.run_once())
        self.assertEqual(store.get(job_id)["error_code"], "RESEARCH_TIMEOUT")

    def test_clarification_fails_job_with_questions(self):
        out = ResearchReportOutput(status=ResearchStatus.NEEDS_CLARIFICATION, retrievedAt="t",
                                   clarificationQuestions=["Which region?"], limitations=["ambiguous"])
        runner = ScriptedRunner(out)
        store, worker = make(runner)
        job_id = submit(store)
        asyncio.run(worker.run_once())
        row = store.get(job_id)
        self.assertEqual((row["status"], row["error_code"], runner.calls), ("failed", "CLARIFICATION_REQUIRED", 1))
        self.assertIn("Which region?", row["clarification_json"])

    def test_job_running_at_crash_is_recovered_after_restart(self):
        store, _ = make(ScriptedRunner(success_output()))
        job_id = submit(store)
        store.claim_next(0.05)  # the old process claimed it and died
        time.sleep(0.1)
        restarted = JobWorker(JobStore(store.db_path), VeritasAgentAdapter(5, runner=ScriptedRunner(success_output())),
                              concurrency=1, poll_seconds=0.01, lease_seconds=60, retry_backoff_seconds=0)
        self.assertTrue(asyncio.run(restarted.run_once()))
        self.assertEqual(store.get(job_id)["status"], "delivered")

    def test_slow_worker_whose_lease_expired_does_not_double_deliver(self):
        store, slow = make(runner_sleeping(0.3), lease=0.05)
        job_id = submit(store)
        fast = JobWorker(store, VeritasAgentAdapter(5, runner=ScriptedRunner(success_output(report="# fast"))),
                         concurrency=1, poll_seconds=0.01, lease_seconds=60, retry_backoff_seconds=0)

        async def race():
            slow_task = asyncio.create_task(slow.run_once())
            await asyncio.sleep(0.1)  # slow worker's lease has expired by now
            await fast.run_once()
            await slow_task

        asyncio.run(race())
        row = store.get(job_id)
        self.assertEqual((row["status"], row["report"]), ("delivered", "# fast"))

    def test_database_outage_does_not_kill_worker_loop(self):
        store, worker = make(ScriptedRunner(success_output()))
        job_id = submit(store)
        real_claim = store.claim_next
        calls = {"n": 0}

        def flaky(lease):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise OSError("database is unavailable")
            return real_claim(lease)

        async def run_loop():
            with mock.patch.object(store, "claim_next", flaky):
                worker.start()
                for _ in range(200):
                    if store.get(job_id)["status"] == "delivered":
                        break
                    await asyncio.sleep(0.01)
                await worker.stop()

        asyncio.run(run_loop())
        self.assertGreaterEqual(calls["n"], 3)
        self.assertEqual(store.get(job_id)["status"], "delivered")


if __name__ == "__main__":
    unittest.main()
