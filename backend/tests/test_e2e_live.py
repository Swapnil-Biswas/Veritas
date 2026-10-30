"""
Live end-to-end test (no mocks): buyer brief -> seller API -> persistent job -> real VERITAS
agent (network access) -> validated report -> stored result -> status endpoint.

Opt-in because it fetches real web pages:  VERITAS_LIVE_E2E=1 python -m unittest tests.test_e2e_live
"""

import os
import time
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

BRIEF = (
    "Compare GitHub Actions, GitLab CI/CD, and CircleCI for running the automated test suite of a small "
    "private TypeScript repository, citing primary vendor documentation."
)


@unittest.skipUnless(os.getenv("VERITAS_LIVE_E2E") == "1", "set VERITAS_LIVE_E2E=1 to run against the real agent")
class TestLiveEndToEnd(unittest.TestCase):
    def test_real_agent_round_trip(self):
        app.state.start_worker = True
        auth = {"Authorization": f"Bearer {settings.seller_token}"}
        with TestClient(app) as client:
            r = client.post("/jobs", json={"orderId": f"live-{uuid.uuid4().hex[:10]}", "brief": BRIEF},
                            headers={**auth, "Idempotency-Key": str(uuid.uuid4())})
            self.assertEqual(r.status_code, 200)
            job_id = r.json()["jobId"]
            deadline = time.time() + settings.agent_timeout_seconds + 30
            while time.time() < deadline:
                body = client.get(f"/jobs/{job_id}", headers=auth).json()
                if body["status"] in ("delivered", "failed"):
                    break
                time.sleep(1)
        self.assertEqual(body["status"], "delivered", body.get("error"))
        self.assertTrue(body["report"].strip())
        self.assertGreaterEqual(len(body["sources"]), 1)
        for s in body["sources"]:
            self.assertEqual(set(s), {"title", "url"})
            self.assertTrue(s["url"].startswith("https://"))
        self.assertEqual(body["agent"]["id"], "veritas-research-agent")


if __name__ == "__main__":
    unittest.main()
