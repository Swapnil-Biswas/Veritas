"""Persistence, idempotency, concurrency and lease-recovery tests for the job store."""

import os
import tempfile
import threading
import time
import unittest

from app.store import IdempotencyConflict, JobStore, LeaseLost


def new_store():
    return JobStore(os.path.join(tempfile.mkdtemp(prefix="veritas-store-"), "jobs.db"))


def deliver(store, job):
    store.mark_delivered(job["job_id"], job["lease_token"], outcome="success", report="r", sources=[],
                         source_details=[], limitations=[], clarification_questions=[], retrieved_at="t",
                         agent_id="a", agent_version="1")


class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.store = new_store()

    def test_duplicate_submission_returns_existing_job(self):
        a, created_a = self.store.create_or_get("order-1", "brief text", "key-1", 3)
        b, created_b = self.store.create_or_get("order-1", "brief text", "key-1", 3)
        self.assertTrue(created_a)
        self.assertFalse(created_b)
        self.assertEqual(a["job_id"], b["job_id"])

    def test_same_order_new_key_same_brief_reuses_job(self):
        a, _ = self.store.create_or_get("order-2", "brief text", "key-2a", 3)
        b, created = self.store.create_or_get("order-2", "brief text", "key-2b", 3)
        self.assertFalse(created)
        self.assertEqual(a["job_id"], b["job_id"])

    def test_same_order_changed_brief_conflicts(self):
        self.store.create_or_get("order-3", "original brief", "key-3", 3)
        with self.assertRaises(IdempotencyConflict):
            self.store.create_or_get("order-3", "changed brief", "key-3b", 3)

    def test_same_key_different_order_conflicts(self):
        self.store.create_or_get("order-4", "brief", "key-4", 3)
        with self.assertRaises(IdempotencyConflict):
            self.store.create_or_get("order-4-other", "brief", "key-4", 3)

    def test_concurrent_duplicate_submissions_create_one_job(self):
        results, errors = [], []

        def submit():
            try:
                results.append(self.store.create_or_get("order-5", "brief", "key-5", 3))
            except Exception as e:  # pragma: no cover - surfaced by assertion below
                errors.append(e)

        threads = [threading.Thread(target=submit) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len({job["job_id"] for job, _ in results}), 1)
        self.assertEqual(sum(1 for _, created in results if created), 1)

    def test_retry_after_restart_returns_same_job(self):
        a, _ = self.store.create_or_get("order-6", "brief", "key-6", 3)
        restarted = JobStore(self.store.db_path)  # fresh instance = process restart
        b, created = restarted.create_or_get("order-6", "brief", "key-6", 3)
        self.assertFalse(created)
        self.assertEqual(a["job_id"], b["job_id"])


class TestQueue(unittest.TestCase):
    def setUp(self):
        self.store = new_store()

    def test_claim_transitions_and_delivery(self):
        job, _ = self.store.create_or_get("order-q1", "brief", "key-q1", 3)
        claimed = self.store.claim_next(60)
        self.assertEqual(claimed["job_id"], job["job_id"])
        self.assertEqual(claimed["status"], "running")
        self.assertIsNone(self.store.claim_next(60))  # nothing else runnable
        deliver(self.store, claimed)
        self.assertEqual(self.store.get(job["job_id"])["status"], "delivered")

    def test_expired_lease_is_recovered_and_stale_worker_cannot_deliver(self):
        self.store.create_or_get("order-q2", "brief", "key-q2", 3)
        first = self.store.claim_next(0.05)  # worker 1 "crashes" holding a short lease
        time.sleep(0.1)
        second = self.store.claim_next(60)  # recovered by worker 2
        self.assertEqual(second["job_id"], first["job_id"])
        self.assertEqual(second["attempts"], 2)
        with self.assertRaises(LeaseLost):
            deliver(self.store, first)  # the stale lease can no longer write
        deliver(self.store, second)
        with self.assertRaises(LeaseLost):
            deliver(self.store, second)  # no double delivery

    def test_exhausted_attempts_fail_on_recovery(self):
        job, _ = self.store.create_or_get("order-q3", "brief", "key-q3", 1)
        self.store.claim_next(0.05)
        time.sleep(0.1)
        self.assertIsNone(self.store.claim_next(60))
        row = self.store.get(job["job_id"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_code"], "RESEARCH_TIMEOUT")

    def test_scheduled_retry_waits_for_backoff(self):
        self.store.create_or_get("order-q4", "brief", "key-q4", 3)
        c = self.store.claim_next(60)
        self.store.schedule_retry(c["job_id"], c["lease_token"], code="X", message="m", delay_seconds=60)
        self.assertEqual(self.store.get(c["job_id"])["status"], "queued")
        self.assertIsNone(self.store.claim_next(60))

    def test_status_check_constraint_rejects_unknown_status(self):
        job, _ = self.store.create_or_get("order-q5", "brief", "key-q5", 3)
        import sqlite3
        conn = sqlite3.connect(self.store.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job["job_id"],))
        conn.close()


if __name__ == "__main__":
    unittest.main()
