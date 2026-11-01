"""Device-under-test abstraction.

Everything above this layer talks to a DUT through this interface only.
A simulated gateway and a real one behind SSH are interchangeable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class FlashResult:
    """Outcome of writing an image to the device."""

    success: bool
    version: str | None
    duration_s: float
    log: str


@dataclass
class DeviceInfo:
    """What the device reports about itself after boot."""

    model: str
    firmware_version: str
    serial: str
    capabilities: list[str] = field(default_factory=list)


class DUTError(Exception):
    """Raised when the device is unreachable or in an unusable state."""


class DUT(ABC):
    """A device under test.

    Implementations must be safe to call in sequence: flash, wait_for_boot,
    then any number of run_command / collect_logs calls.
    """

    name: str

    @abstractmethod
    def flash(self, image_path: str) -> FlashResult:
        """Write a firmware image to the device.

        Does not guarantee the device is up afterwards - call wait_for_boot.
        """

    @abstractmethod
    def wait_for_boot(self, timeout_s: int = 120) -> bool:
        """Block until the device responds, or timeout_s elapses.

        Returns True if the device came up.
        """

    @abstractmethod
    def info(self) -> DeviceInfo:
        """Query the device for its identity and firmware version."""

    @abstractmethod
    def run_command(self, cmd: str, timeout_s: int = 30) -> tuple[int, str]:
        """Run a shell command on the device.

        Returns (exit_code, combined_output).
        """

    @abstractmethod
    def collect_logs(self, since_s: float = 0.0) -> str:
        """Return device logs emitted in the last since_s seconds.

        since_s of 0 means everything buffered.
        """

    @abstractmethod
    def reboot(self) -> bool:
        """Restart the device. Returns True once it is back up."""

    def __enter__(self) -> DUT:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Release any connection held to the device. Override if needed."""
        return None