"""Event types passed between pipeline stages and agents.

Everything that happens in a run is an event. Components publish events
and subscribe to the ones they care about; nothing calls anything else
directly. That is what lets you add a new domain agent without touching
existing code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Event:
    """Base event. Every event carries an id, a timestamp and a source."""

    source: str
    run_id: str = ""
    event_id: str = field(default_factory=_new_id)
    at: datetime = field(default_factory=_now)

    @property
    def kind(self) -> str:
        return type(self).__name__


@dataclass(frozen=True)
class BuildDetected(Event):
    """A new firmware image has appeared."""

    image_path: str = ""
    version: str = ""
    variant: str = ""


@dataclass(frozen=True)
class FlashStarted(Event):
    device: str = ""
    image_path: str = ""


@dataclass(frozen=True)
class FlashCompleted(Event):
    device: str = ""
    success: bool = False
    version: str | None = None
    duration_s: float = 0.0
    log: str = ""


@dataclass(frozen=True)
class DeviceReady(Event):
    """Device booted and is accepting commands."""

    device: str = ""
    firmware_version: str = ""


@dataclass(frozen=True)
class SuiteStarted(Event):
    suite: str = ""
    device: str = ""
    case_count: int = 0


@dataclass(frozen=True)
class TestCaseFinished(Event):
    suite: str = ""
    case_id: str = ""
    name: str = ""
    passed: bool = False
    duration_s: float = 0.0
    output: str = ""


@dataclass(frozen=True)
class SuiteFinished(Event):
    suite: str = ""
    device: str = ""
    passed: int = 0
    failed: int = 0
    duration_s: float = 0.0


@dataclass(frozen=True)
class TriageRequested(Event):
    """Ask the triage agent to look at a set of failures."""

    suite: str = ""
    failures: tuple[TestCaseFinished, ...] = ()
    device_log: str = ""


@dataclass(frozen=True)
class FailureCluster:
    """A group of failures the agent believes share a root cause."""

    summary: str
    suspected_cause: str
    case_ids: tuple[str, ...]
    confidence: float
    severity: Severity = Severity.ERROR


@dataclass(frozen=True)
class TriageCompleted(Event):
    suite: str = ""
    clusters: tuple[FailureCluster, ...] = ()
    model: str = ""
    notes: str = ""


@dataclass(frozen=True)
class PipelineFailed(Event):
    """Something went wrong that stops the run."""

    stage: str = ""
    reason: str = ""