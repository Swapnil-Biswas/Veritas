"""
VERITAS: Language-model client used for research planning and evidence-grounded synthesis.

Any OpenAI-compatible chat-completions endpoint works (LM Studio, Ollama, vLLM, OpenAI, ...).
Configuration (environment):
  VERITAS_LLM_ENDPOINT         base URL, default http://127.0.0.1:1234/v1 (LM Studio)
  VERITAS_LLM_MODEL            model id, default google/gemma-4-e2b
  VERITAS_LLM_API_KEY          optional; sent as a Bearer header, never in the URL
  VERITAS_LLM_TIMEOUT_SECONDS  per-call timeout, default 240
"""

import json
import os
import re
from typing import List

import httpx


class LLMUnavailable(RuntimeError):
    """The language model could not be reached or returned nothing. Transient: callers may retry."""


class LLMClient:
    def __init__(self):
        self.endpoint = os.getenv("VERITAS_LLM_ENDPOINT", "http://127.0.0.1:1234/v1").rstrip("/")
        self.model = os.getenv("VERITAS_LLM_MODEL", "google/gemma-4-e2b")
        self.api_key = os.getenv("VERITAS_LLM_API_KEY", "")
        self.timeout = float(os.getenv("VERITAS_LLM_TIMEOUT_SECONDS", "240"))

    async def chat(self, system: str, user: str, max_tokens: int = 3000) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.endpoint}/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"].get("content") or ""
        except Exception as e:
            raise LLMUnavailable(f"Language model unavailable: {type(e).__name__}") from e
        # Some local reasoning models emit a visible thinking block; it is never report content.
        return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()

    async def chat_list(self, system: str, user: str, max_tokens: int = 2000) -> List[str]:
        """Asks for a JSON list of strings and parses it leniently (empty list on malformed output)."""
        raw = await self.chat(system, user, max_tokens=max_tokens)
        match = re.search(r"\[.*\]", raw, re.S)
        try:
            data = json.loads(match.group(0)) if match else []
        except ValueError:
            data = []
        return [x.strip() for x in data if isinstance(x, str) and x.strip()]
