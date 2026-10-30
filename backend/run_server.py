"""Starts the VERITAS seller backend (API + in-process worker pool)."""

import os
import sys

import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("VERITAS_HOST", "127.0.0.1"),
        port=int(os.getenv("VERITAS_PORT", "8020")),
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("VERITAS_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        log_config=None,  # app.logging_setup configures redacting handlers
    )
