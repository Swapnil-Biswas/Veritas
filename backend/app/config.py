"""
VERITAS seller backend configuration.

All values come from environment variables (see .env.example). No secret has a
default: if HIRECREW_SELLER_TOKEN is unset outside production, a random per-process
token is generated so the API is never reachable with a guessable credential; in
production the service refuses to start without it.
"""

import os
import secrets
from dataclasses import dataclass, field
from typing import List

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass(frozen=True)
class Settings:
    env: str = os.getenv("VERITAS_ENV", "development")
    log_level: str = os.getenv("VERITAS_LOG_LEVEL", "INFO")

    # Seller API authentication (token issued by HireCrew after review)
    seller_token: str = field(default_factory=lambda: os.getenv("HIRECREW_SELLER_TOKEN", ""))

    # Persistence
    db_path: str = os.getenv("VERITAS_DB_PATH", os.path.join(_BACKEND_DIR, "data", "veritas_jobs.db"))

    # Request limits
    max_brief_chars: int = _int("VERITAS_MAX_BRIEF_CHARS", 50000)  # matches the agent's input schema
    max_order_id_chars: int = _int("VERITAS_MAX_ORDER_ID_CHARS", 128)
    max_idempotency_key_chars: int = _int("VERITAS_MAX_IDEMPOTENCY_KEY_CHARS", 255)
    max_body_bytes: int = _int("VERITAS_MAX_BODY_BYTES", 256 * 1024)

    # Worker / queue
    worker_concurrency: int = _int("VERITAS_WORKER_CONCURRENCY", 2)
    worker_poll_seconds: float = _float("VERITAS_WORKER_POLL_SECONDS", 1.0)
    agent_timeout_seconds: float = _float("VERITAS_AGENT_TIMEOUT_SECONDS", 600.0)
    # A claimed job whose lease expires (worker crash/restart) becomes claimable again.
    lease_seconds: float = _float("VERITAS_LEASE_SECONDS", 660.0)
    max_attempts: int = _int("VERITAS_MAX_ATTEMPTS", 3)
    retry_backoff_seconds: float = _float("VERITAS_RETRY_BACKOFF_SECONDS", 30.0)

    # Agent invocation profile (mapped onto the agent's ResearchBriefInput)
    agent_depth: str = os.getenv("VERITAS_AGENT_DEPTH", "standard")
    agent_max_sources: int = _int("VERITAS_AGENT_MAX_SOURCES", 10)

    # Browser origins allowed to call the API. Server-to-server callers (HireCrew) need none.
    cors_origins: List[str] = field(default_factory=lambda: [
        o.strip() for o in os.getenv("VERITAS_CORS_ORIGINS", "").split(",") if o.strip()
    ])

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


def load_settings() -> Settings:
    s = Settings()
    if not s.seller_token:
        if s.is_production:
            raise RuntimeError("HIRECREW_SELLER_TOKEN must be set when VERITAS_ENV=production.")
        object.__setattr__(s, "seller_token", secrets.token_urlsafe(32))
    if len(s.seller_token) < 16:
        raise RuntimeError("HIRECREW_SELLER_TOKEN is too short (minimum 16 characters).")
    return s


settings = load_settings()
