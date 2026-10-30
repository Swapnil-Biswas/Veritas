"""Shared fakes for backend tests (isolated unit tests only; never used for the live end-to-end test)."""

import asyncio
from datetime import datetime, timezone

from agent.schemas.output import ResearchReportOutput, ResearchStatus
from agent.schemas.source import SourceRecord


def source(url="https://example.org/doc", title="Example doc"):
    return SourceRecord(title=title, url=url, retrievedAt=datetime.now(timezone.utc).isoformat(),
                        relevance=0.9, claimsSupported=["claim"], isPrimary=True, evidenceSnippet="snippet")


def success_output(sources=None, report="# Report\nFinding (https://example.org/doc)"):
    return ResearchReportOutput(status=ResearchStatus.SUCCESS, report=report,
                                sources=[source()] if sources is None else sources,
                                retrievedAt="2026-10-31T00:00:00+00:00", limitations=["gap A"])


def runner_returning(output):
    async def run(_payload):
        return output
    return run


def runner_raising(exc):
    async def run(_payload):
        raise exc
    return run


def runner_sleeping(seconds):
    async def run(_payload):
        await asyncio.sleep(seconds)
        return success_output()
    return run


class ScriptedRunner:
    """Returns/raises the given items in order, recording every call."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    async def __call__(self, _payload):
        self.calls += 1
        item = self.items.pop(0) if len(self.items) > 1 else self.items[0]
        if isinstance(item, BaseException):
            raise item
        return item
