"""
Durable SQLite (WAL) job store and queue.

Order safety
  * Every submission must carry an Idempotency-Key (seller-hosted-api-v1).
  * Both the idempotency key and the HireCrew orderId are UNIQUE: one paid order maps
    to exactly one research job, even if HireCrew retries with a new key.
  * Same key or same orderId with the *same* brief -> the existing job is returned.
  * Same key or same orderId with a *different* order/brief -> IdempotencyConflict (HTTP 409).
  * Submissions are serialised with BEGIN IMMEDIATE, so concurrent duplicates cannot
    both insert; the UNIQUE constraints are a second line of defence.

Queue semantics
  * queued -> running (claim) -> delivered | failed, or running -> queued for a retry.
  * A claim sets a random lease token and an expiry. Every state change out of
    "running" must present that token, so a worker whose lease expired (and whose job
    was re-claimed after a crash or restart) can never deliver or fail it a second time.
  * Expired leases are re-claimable; once attempts are exhausted the job is failed.
"""

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id            TEXT PRIMARY KEY,
    order_id          TEXT NOT NULL UNIQUE,
    idempotency_key   TEXT NOT NULL UNIQUE,
    request_hash      TEXT NOT NULL,
    brief             TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('queued', 'running', 'delivered', 'failed')),
    attempts          INTEGER NOT NULL DEFAULT 0,
    max_attempts      INTEGER NOT NULL,
    available_at      REAL NOT NULL,
    lease_token       TEXT,
    lease_expires_at  REAL,
    outcome           TEXT,
    report            TEXT,
    sources_json      TEXT,
    limitations_json  TEXT,
    clarification_json TEXT,
    retrieved_at      TEXT,
    error_code        TEXT,
    error_message     TEXT,
    agent_id          TEXT,
    agent_version     TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs (status, available_at);
CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs (status, lease_expires_at);
"""

TERMINAL = ("delivered", "failed")


class IdempotencyConflict(Exception):
    """The idempotency key or order ID was already used with a different request."""


class LeaseLost(Exception):
    """The worker no longer owns the job (lease expired and it was re-claimed or finished)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_hash(order_id: str, brief: str) -> str:
    return hashlib.sha256(f"{order_id}\x00{brief}".encode("utf-8")).hexdigest()


class JobStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=30000")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write_txn(self) -> Iterator[sqlite3.Connection]:
        """Exclusive write transaction (serialises submissions and claims across processes)."""
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ health

    def ping(self) -> bool:
        with self._connect() as conn:
            return conn.execute("SELECT 1").fetchone()[0] == 1

    # ------------------------------------------------------------- submission

    def create_or_get(
        self, order_id: str, brief: str, idempotency_key: str, max_attempts: int
    ) -> Tuple[Dict[str, Any], bool]:
        """Returns (job, created). Raises IdempotencyConflict on a mismatched duplicate."""
        rh = request_hash(order_id, brief)
        with self._write_txn() as conn:
            existing = conn.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ? OR order_id = ?",
                (idempotency_key, order_id),
            ).fetchall()
            for row in existing:
                if row["request_hash"] != rh:
                    raise IdempotencyConflict(
                        "This idempotency key or order ID was already used for a different request."
                    )
            if existing:
                return dict(existing[0]), False

            now = _now_iso()
            job_id = f"veritas-job-{uuid.uuid4().hex}"
            conn.execute(
                "INSERT INTO jobs (job_id, order_id, idempotency_key, request_hash, brief, status, "
                "max_attempts, available_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)",
                (job_id, order_id, idempotency_key, rh, brief, max_attempts, time.time(), now, now),
            )
            return dict(conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()), True

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ queue

    def claim_next(self, lease_seconds: float) -> Optional[Dict[str, Any]]:
        """Atomically claims the next runnable job, recovering expired leases first."""
        now = time.time()
        with self._write_txn() as conn:
            # Expired leases whose attempts are exhausted can never run again.
            conn.execute(
                "UPDATE jobs SET status='failed', error_code='RESEARCH_TIMEOUT', "
                "error_message='The research job did not finish within the allowed attempts.', "
                "lease_token=NULL, lease_expires_at=NULL, finished_at=?, updated_at=? "
                "WHERE status='running' AND lease_expires_at <= ? AND attempts >= max_attempts",
                (_now_iso(), _now_iso(), now),
            )
            row = conn.execute(
                "SELECT job_id FROM jobs WHERE "
                "(status='queued' AND available_at <= ?) OR (status='running' AND lease_expires_at <= ?) "
                "ORDER BY available_at, created_at LIMIT 1",
                (now, now),
            ).fetchone()
            if not row:
                return None
            token = secrets.token_hex(16)
            now_iso = _now_iso()
            conn.execute(
                "UPDATE jobs SET status='running', attempts=attempts+1, lease_token=?, lease_expires_at=?, "
                "started_at=COALESCE(started_at, ?), updated_at=? WHERE job_id=?",
                (token, now + lease_seconds, now_iso, now_iso, row["job_id"]),
            )
            return dict(conn.execute("SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)).fetchone())

    def _finish(self, job_id: str, lease_token: str, assignments: str, params: tuple) -> None:
        with self._write_txn() as conn:
            cur = conn.execute(
                f"UPDATE jobs SET {assignments}, lease_token=NULL, lease_expires_at=NULL, updated_at=? "
                "WHERE job_id=? AND status='running' AND lease_token=?",
                (*params, _now_iso(), job_id, lease_token),
            )
            if cur.rowcount != 1:
                raise LeaseLost(job_id)

    def mark_delivered(
        self,
        job_id: str,
        lease_token: str,
        *,
        outcome: str,
        report: str,
        sources: List[Dict[str, Any]],
        limitations: List[str],
        clarification_questions: List[str],
        retrieved_at: str,
        agent_id: str,
        agent_version: str,
    ) -> None:
        self._finish(
            job_id, lease_token,
            "status='delivered', outcome=?, report=?, sources_json=?, limitations_json=?, "
            "clarification_json=?, retrieved_at=?, agent_id=?, agent_version=?, "
            "error_code=NULL, error_message=NULL, finished_at=?",
            (outcome, report, json.dumps(sources), json.dumps(limitations),
             json.dumps(clarification_questions), retrieved_at, agent_id, agent_version, _now_iso()),
        )

    def mark_failed(self, job_id: str, lease_token: str, *, code: str, message: str) -> None:
        self._finish(
            job_id, lease_token,
            "status='failed', error_code=?, error_message=?, finished_at=?",
            (code, message, _now_iso()),
        )

    def schedule_retry(self, job_id: str, lease_token: str, *, code: str, message: str, delay_seconds: float) -> None:
        self._finish(
            job_id, lease_token,
            "status='queued', error_code=?, error_message=?, available_at=?",
            (code, message, time.time() + delay_seconds),
        )
