"""Runs a declarative test suite against a ready device.

Subscribes to DeviceReady. Loads a YAML suite, runs each case as a
command on the DUT, and emits one TestCaseFinished per case plus a
SuiteFinished at the end. If there were failures it also emits
TriageRequested, which is what wakes the triage agent.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..core.bus import EventBus
from ..core.events import (
    DeviceReady,
    Event,
    SuiteFinished,
    SuiteStarted,
    TestCaseFinished,
    TriageRequested,
)
from ..devices.base import DUT, DUTError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TestCase:
    id: str
    name: str
    command: str


@dataclass(frozen=True)
class Suite:
    name: str
    description: str
    cases: tuple[TestCase, ...]

    @classmethod
    def from_yaml(cls, path: str | Path) -> Suite:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a mapping at the top level")

        raw_cases = data.get("cases") or []
        cases = tuple(
            TestCase(
                id=str(c["id"]),
                name=str(c.get("name", c["id"])),
                command=str(c["command"]),
            )
            for c in raw_cases
        )
        if not cases:
            raise ValueError(f"{path}: suite has no cases")

        return cls(
            name=str(data.get("name", Path(path).stem)),
            description=str(data.get("description", "")),
            cases=cases,
        )


class SuiteRunner:
    """Executes a suite when a device becomes ready."""

    name = "suite-runner"

    def __init__(self, bus: EventBus, device: DUT, suite_path: str | Path) -> None:
        self.bus = bus
        self.device = device
        self.suite = Suite.from_yaml(suite_path)
        bus.subscribe(DeviceReady, self.on_device_ready)

    def on_device_ready(self, event: Event) -> Iterable[Event]:
        assert isinstance(event, DeviceReady)
        emitted: list[Event] = []
        started = time.time()

        self.bus.publish(
            SuiteStarted(
                source=self.name,
                run_id=event.run_id,
                suite=self.suite.name,
                device=event.device,
                case_count=len(self.suite.cases),
            )
        )

        failures: list[TestCaseFinished] = []
        passed = 0

        for case in self.suite.cases:
            case_started = time.time()
            try:
                code, output = self.device.run_command(case.command)
            except DUTError as exc:
                code, output = 1, f"device error: {exc}"

            finished = TestCaseFinished(
                source=self.name,
                run_id=event.run_id,
                suite=self.suite.name,
                case_id=case.id,
                name=case.name,
                passed=code == 0,
                duration_s=time.time() - case_started,
                output=output,
            )
            self.bus.publish(finished)

            if finished.passed:
                passed += 1
            else:
                failures.append(finished)

        emitted.append(
            SuiteFinished(
                source=self.name,
                run_id=event.run_id,
                suite=self.suite.name,
                device=event.device,
                passed=passed,
                failed=len(failures),
                duration_s=time.time() - started,
            )
        )

        if failures:
            log.info("%d failures - requesting triage", len(failures))
            emitted.append(
                TriageRequested(
                    source=self.name,
                    run_id=event.run_id,
                    suite=self.suite.name,
                    failures=tuple(failures),
                    device_log=self.device.collect_logs(),
                )
            )

        return emitted