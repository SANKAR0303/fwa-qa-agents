"""Flashes a detected build onto a device and reports the outcome.

Subscribes to BuildDetected. Emits FlashCompleted always, DeviceReady
only when the device actually came back up. A failed flash is a normal
outcome here, not an exception - it is information the pipeline needs,
not a crash.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ..core.bus import EventBus
from ..core.events import (
    BuildDetected,
    DeviceReady,
    Event,
    FlashCompleted,
    FlashStarted,
    PipelineFailed,
)
from ..devices.base import DUT, DUTError

log = logging.getLogger(__name__)


class Flasher:
    """Drives a DUT through flash and boot in response to a new build."""

    name = "flasher"

    def __init__(
        self,
        bus: EventBus,
        device: DUT,
        boot_timeout_s: int = 120,
        retries: int = 1,
    ) -> None:
        self.bus = bus
        self.device = device
        self.boot_timeout_s = boot_timeout_s
        self.retries = retries
        bus.subscribe(BuildDetected, self.on_build)

    def on_build(self, event: Event) -> Iterable[Event]:
        """Flash the detected image, then wait for the device to boot."""
        assert isinstance(event, BuildDetected)
        emitted: list[Event] = []

        self.bus.publish(
            FlashStarted(
                source=self.name,
                run_id=event.run_id,
                device=self.device.name,
                image_path=event.image_path,
            )
        )

        attempt = 0
        result = None
        while attempt <= self.retries:
            attempt += 1
            try:
                result = self.device.flash(event.image_path)
            except DUTError as exc:
                log.error("flash attempt %d raised: %s", attempt, exc)
                emitted.append(
                    PipelineFailed(
                        source=self.name,
                        run_id=event.run_id,
                        stage="flash",
                        reason=str(exc),
                    )
                )
                return emitted

            if result.success:
                break
            log.warning("flash attempt %d failed", attempt)

        if result is None or not result.success:
            emitted.append(
                FlashCompleted(
                    source=self.name,
                    run_id=event.run_id,
                    device=self.device.name,
                    success=False,
                    duration_s=result.duration_s if result else 0.0,
                    log=result.log if result else "",
                )
            )
            emitted.append(
                PipelineFailed(
                    source=self.name,
                    run_id=event.run_id,
                    stage="flash",
                    reason=f"flash failed after {attempt} attempt(s)",
                )
            )
            return emitted

        emitted.append(
            FlashCompleted(
                source=self.name,
                run_id=event.run_id,
                device=self.device.name,
                success=True,
                version=result.version,
                duration_s=result.duration_s,
                log=result.log,
            )
        )

        try:
            booted = self.device.wait_for_boot(self.boot_timeout_s)
        except DUTError as exc:
            emitted.append(
                PipelineFailed(
                    source=self.name,
                    run_id=event.run_id,
                    stage="boot",
                    reason=str(exc),
                )
            )
            return emitted

        if not booted:
            emitted.append(
                PipelineFailed(
                    source=self.name,
                    run_id=event.run_id,
                    stage="boot",
                    reason="device did not come up after flash",
                )
            )
            return emitted

        emitted.append(
            DeviceReady(
                source=self.name,
                run_id=event.run_id,
                device=self.device.name,
                firmware_version=result.version or "unknown",
            )
        )
        return emitted