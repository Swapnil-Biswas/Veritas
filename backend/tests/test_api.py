"""Seller API contract, validation, auth, idempotency and security tests."""

import asyncio
import json
import logging
import unittest
import uuid

from fastapi.testclient import TestClient

from agent.schemas.output import ResearchReportOutput, ResearchStatus
from app.adapter import VeritasAgentAdapter
from app.config import settings
from app.logging_setup import RedactingFilter
from app.main import app
from tests.helpers import ScriptedRunner, success_output

AUTH = {"Authorization": f"Bearer {settings.seller_token}"}


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.state.start_worker = False  # tests drive the worker explicitly
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        app.state.start_worker = True

    def headers(self, key=None):
        return {**AUTH, "Idempotency-Key": key or f"key-{uuid.uuid4()}"}

    def submit(self, brief="Compare the self-hosted runner support of two CI products.", order=None, key=None):
        return self.client.post("/jobs", json={"orderId": order or f"order-{uuid.uuid4().hex[:12]}", "brief": brief},
                                headers=self.headers(key))

    def process_with(self, *items):
        worker = app.state.worker
        worker.adapter = VeritasAgentAdapter(timeout_seconds=5, runner=ScriptedRunner(*items))
        while asyncio.run(worker.run_once()):
            pass


class TestSubmission(ApiTestCase):
    def test_valid_submission_returns_queued_job(self):
        r = self.submit()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "queued")
        self.assertRegex(body["jobId"], r"^veritas-job-[0-9a-f]{32}$")

    def test_missing_order_id(self):
        r = self.client.post("/jobs", json={"brief": "A valid research brief"}, headers=self.headers())
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "INVALID_REQUEST"))
        self.assertIn("orderId", r.json()["error"]["message"])

    def test_missing_brief(self):
        r = self.client.post("/jobs", json={"orderId": "o-1"}, headers=self.headers())
        self.assertEqual(r.status_code, 400)
        self.assertIn("brief", r.json()["error"]["message"])

    def test_invalid_json_and_non_object_bodies(self):
        r = self.client.post("/jobs", content=b"{not json", headers={**self.headers(), "Content-Type": "application/json"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "INVALID_JSON"))
        r = self.client.post("/jobs", json=["orderId", "brief"], headers=self.headers())
        self.assertEqual(r.status_code, 400)

    def test_invalid_field_types_and_charset(self):
        r = self.client.post("/jobs", json={"orderId": 123, "brief": "A valid research brief"}, headers=self.headers())
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/jobs", json={"orderId": "bad id/../x", "brief": "A valid research brief"},
                             headers=self.headers())
        self.assertEqual(r.status_code, 400)

    def test_oversized_brief_and_body_rejected(self):
        r = self.submit(brief="x" * (settings.max_brief_chars + 1))
        self.assertIn(r.status_code, (400, 413))
        big = json.dumps({"orderId": "o-big", "brief": "y" * (settings.max_body_bytes + 10)})
        r = self.client.post("/jobs", content=big, headers={**self.headers(), "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_idempotency_key_required(self):
        r = self.client.post("/jobs", json={"orderId": "o-k", "brief": "A valid research brief"}, headers=AUTH)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "IDEMPOTENCY_KEY_REQUIRED"))


class TestAuth(ApiTestCase):
    def test_missing_and_malformed_authorization(self):
        r = self.client.post("/jobs", json={"orderId": "o", "brief": "A valid research brief"},
                             headers={"Idempotency-Key": "k"})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/jobs", json={"orderId": "o", "brief": "A valid research brief"},
                             headers={"Authorization": "Basic abc", "Idempotency-Key": "k"})
        self.assertEqual(r.status_code, 401)

    def test_wrong_token_rejected_for_submit_and_poll(self):
        bad = {"Authorization": "Bearer wrong-token-value-xyz", "Idempotency-Key": "k"}
        self.assertEqual(self.client.post("/jobs", json={"orderId": "o", "brief": "A valid brief"}, headers=bad).status_code, 403)
        job_id = self.submit().json()["jobId"]
        self.assertEqual(self.client.get(f"/jobs/{job_id}", headers=bad).status_code, 403)
        self.assertEqual(self.client.get(f"/jobs/{job_id}").status_code, 401)

    def test_token_in_query_string_is_not_accepted(self):
        job_id = self.submit().json()["jobId"]
        r = self.client.get(f"/jobs/{job_id}?token={settings.seller_token}")
        self.assertEqual(r.status_code, 401)


class TestIdempotencyApi(ApiTestCase):
    def test_duplicate_submission_returns_same_job(self):
        key, order = f"key-{uuid.uuid4()}", f"order-{uuid.uuid4().hex[:8]}"
        a = self.submit(order=order, key=key).json()
        b = self.submit(order=order, key=key).json()
        self.assertEqual(a["jobId"], b["jobId"])

    def test_retry_after_timeout_with_new_key_reuses_order_job(self):
        order = f"order-{uuid.uuid4().hex[:8]}"
        a = self.submit(order=order).json()
        b = self.submit(order=order).json()  # client timed out and retried with a fresh key
        self.assertEqual(a["jobId"], b["jobId"])

    def test_same_order_with_changed_brief_conflicts(self):
        order = f"order-{uuid.uuid4().hex[:8]}"
        self.submit(order=order, brief="Original research brief text")
        r = self.submit(order=order, brief="A different research brief")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "IDEMPOTENCY_CONFLICT"))

    def test_replay_after_delivery_returns_delivered_status_without_rerun(self):
        key, order = f"key-{uuid.uuid4()}", f"order-{uuid.uuid4().hex[:8]}"
        job_id = self.submit(order=order, key=key).json()["jobId"]
        runner = ScriptedRunner(success_output())
        app.state.worker.adapter = VeritasAgentAdapter(timeout_seconds=5, runner=runner)
        while asyncio.run(app.state.worker.run_once()):
            pass
        replay = self.submit(order=order, key=key).json()
        self.assertEqual((replay["jobId"], replay["status"]), (job_id, "delivered"))
        while asyncio.run(app.state.worker.run_once()):
            pass
        self.assertEqual(app.state.store.get(job_id)["attempts"], 1)  # the agent ran exactly once for this order


class TestPolling(ApiTestCase):
    def test_unknown_and_malformed_job_ids(self):
        self.assertEqual(self.client.get(f"/jobs/veritas-job-{'0' * 32}", headers=AUTH).status_code, 404)
        self.assertEqual(self.client.get("/jobs/..%2F..%2Fetc", headers=AUTH).status_code, 404)

    def test_queued_then_delivered_result(self):
        job_id = self.submit().json()["jobId"]
        r = self.client.get(f"/jobs/{job_id}", headers=AUTH).json()
        self.assertEqual(r["status"], "queued")
        self.process_with(success_output())
        for _ in range(3):  # repeated polling is stable
            body = self.client.get(f"/jobs/{job_id}", headers=AUTH).json()
            self.assertEqual(body["status"], "delivered")
        self.assertTrue(body["report"].startswith("# Report"))
        self.assertEqual(body["sources"], [{"title": "Example doc", "url": "https://example.org/doc"}])
        self.assertEqual(body["retrievedAt"], "2026-10-31T00:00:00+00:00")
        self.assertEqual(body["agent"], {"id": "veritas-research-agent", "version": "1.0.0"})

    def test_failed_job_response_shape(self):
        job_id = self.submit().json()["jobId"]
        bad = ResearchReportOutput(status=ResearchStatus.FAILED, retrievedAt="t", error="internal trace here")
        self.process_with(bad)
        body = self.client.get(f"/jobs/{job_id}", headers=AUTH).json()
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["error"]["code"], "RESEARCH_EXECUTION_FAILED")
        self.assertNotIn("internal trace", json.dumps(body))
        self.assertNotIn("report", body)

    def test_clarification_response_includes_questions(self):
        job_id = self.submit().json()["jobId"]
        q = ResearchReportOutput(status=ResearchStatus.NEEDS_CLARIFICATION, retrievedAt="t",
                                 clarificationQuestions=["What budget?"])
        self.process_with(q)
        body = self.client.get(f"/jobs/{job_id}", headers=AUTH).json()
        self.assertEqual((body["status"], body["error"]["code"]), ("failed", "CLARIFICATION_REQUIRED"))
        self.assertEqual(body["clarificationQuestions"], ["What budget?"])


class TestSecurity(ApiTestCase):
    def test_responses_never_echo_the_seller_token(self):
        for r in (self.submit(), self.client.post("/jobs", json={}, headers=self.headers()),
                  self.client.get("/health"), self.client.get("/nope")):
            self.assertNotIn(settings.seller_token, r.text)

    def test_errors_have_no_stack_traces(self):
        r = self.client.post("/jobs", content=b"\xff\xfe", headers={**self.headers(), "Content-Type": "application/json"})
        self.assertNotIn("Traceback", r.text)
        self.assertIn("error", r.json())

    def test_security_headers_and_no_cors_by_default(self):
        r = self.client.get("/health", headers={"Origin": "https://evil.example"})
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertNotIn("access-control-allow-origin", {k.lower() for k in r.headers})

    def test_log_redaction(self):
        f = RedactingFilter([settings.seller_token])
        rec = logging.LogRecord("x", logging.INFO, "", 0,
                                "auth Bearer %s key=%s sk_live_abcdefghijklmnopqrstuv", (settings.seller_token, "s3cr3t"), None)
        f.filter(rec)
        self.assertNotIn(settings.seller_token, rec.msg)
        self.assertNotIn("s3cr3t", rec.msg)
        self.assertNotIn("sk_live_abcdefghijklmnopqrstuv", rec.msg)

    def test_health_reports_database_and_agent(self):
        body = self.client.get("/health").json()
        self.assertTrue(body["database"])
        self.assertEqual(body["agent"]["agent_id"], "veritas-research-agent")


if __name__ == "__main__":
    unittest.main()
