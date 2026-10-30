"""
Logging with secret redaction.

Application logs never include briefs, reports or headers by design; this filter is a
second line of defence that masks bearer tokens, the configured seller token and
common API-key shapes if they ever reach a log record.
"""

import logging
import os
import re

_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+"),
    re.compile(r"\b(sk|pk|ghp|gho|hf)_[A-Za-z0-9]{16,}\b"),
]


class RedactingFilter(logging.Filter):
    def __init__(self, extra_secrets=()):
        super().__init__()
        self.extra = [s for s in extra_secrets if s and len(s) >= 8]

    def redact(self, text: str) -> str:
        for s in self.extra:
            text = text.replace(s, "[REDACTED]")
        text = _PATTERNS[0].sub(r"\1[REDACTED]", text)
        text = _PATTERNS[1].sub(r"\1[REDACTED]", text)
        return _PATTERNS[2].sub("[REDACTED]", text)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    from app.config import settings

    secrets_to_mask = [settings.seller_token] + [
        os.getenv(k, "") for k in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SEARCH_API_KEY")
    ]
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter(secrets_to_mask))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    logging.getLogger("httpx").setLevel(logging.WARNING)  # avoid logging every fetched URL at INFO
