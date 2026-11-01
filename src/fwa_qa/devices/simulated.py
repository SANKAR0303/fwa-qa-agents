"""A fake gateway that behaves enough like real hardware to develop against.

Deterministic when seeded, so tests and demo runs are reproducible.
Failure injection is explicit: set failure_rate to make flashes and
commands fail at a known rate, which is how the triage agent gets
something to chew on.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

from .base import DUT, DeviceInfo, DUTError, FlashResult

_BOOT_SEQUENCE = [
    "[    0.000000] Booting Linux on physical CPU 0x0",
    "[    0.842113] platform: gateway-sim rev B",
    "[    2.104887] mtd: partitions found on MTD device",
    "[    3.551902] wlan0: Wi-Fi driver loaded (802.11ax)",
    "[    4.013776] wlan1: Wi-Fi driver loaded (802.11ax, 5GHz)",
    "[    5.229401] modem: 5G NR module initialised",
    "[    6.887120] netifd: bridge lan up",
    "[    8.330459] system: boot complete",
]

_FAULT_LINES = [
    "[   12.442011] wlan1: association timeout, client aa:bb:cc:dd:ee:01",
    "[   14.901335] modem: NR registration lost (cause=15)",
    "[   15.220817] netifd: bridge lan: port wlan1 flapped",
    "[   18.774290] kernel: BUG: soft lockup - CPU#1 stuck for 22s",
    "[   21.009114] dhcp: no lease offered on wlan0",
]


class SimulatedDUT(DUT):
    """An in-process stand-in for a gateway."""

    def __init__(
        self,
        name: str = "sim-gateway-01",
        seed: int | None = 1337,
        failure_rate: float = 0.0,
        speed: float = 20.0,
    ) -> None:
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be between 0.0 and 1.0")
        if speed <= 0:
            raise ValueError("speed must be positive")
        self.name = name
        self.failure_rate = failure_rate
        self.speed = speed
        self._rng = random.Random(seed)
        self._booted = False
        self._firmware_version: str | None = None
        self._log_buffer: list[tuple[float, str]] = []

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds / self.speed)

    def _log(self, line: str) -> None:
        self._log_buffer.append((time.time(), line))

    def _should_fail(self) -> bool:
        return self._rng.random() < self.failure_rate

    @staticmethod
    def _version_from_path(image_path: str) -> str:
        stem = Path(image_path).stem
        parts = [p for p in stem.replace("_", "-").split("-") if p[:1].isdigit()]
        return parts[-1] if parts else "0.0.0-unknown"

    def flash(self, image_path: str) -> FlashResult:
        started = time.time()
        self._booted = False
        self._log_buffer.clear()
        self._log(f"flash: writing {Path(image_path).name}")
        self._sleep(45.0)
        if self._should_fail():
            self._log("flash: CRC mismatch on partition rootfs")
            return FlashResult(
                success=False,
                version=None,
                duration_s=time.time() - started,
                log="\n".join(line for _, line in self._log_buffer),
            )
        version = self._version_from_path(image_path)
        self._firmware_version = version
        self._log(f"flash: image written, version {version}")
        return FlashResult(
            success=True,
            version=version,
            duration_s=time.time() - started,
            log="\n".join(line for _, line in self._log_buffer),
        )

    def wait_for_boot(self, timeout_s: int = 120) -> bool:
        if self._firmware_version is None:
            raise DUTError("no image flashed - nothing to boot")
        for line in _BOOT_SEQUENCE:
            self._sleep(1.2)
            self._log(line)
        if self._should_fail():
            self._log("[   09.112004] system: watchdog reset during init")
            self._booted = False
            return False
        self._booted = True
        return True

    def info(self) -> DeviceInfo:
        if not self._booted:
            raise DUTError("device is not up - call wait_for_boot first")
        return DeviceInfo(
            model="gateway-sim",
            firmware_version=self._firmware_version or "unknown",
            serial=f"SIM{self._rng.randrange(10**8):08d}",
            capabilities=["wifi6", "wifi6e", "5g-nr", "mesh"],
        )

    def run_command(self, cmd: str, timeout_s: int = 30) -> tuple[int, str]:
        if not self._booted:
            raise DUTError("device is not up - call wait_for_boot first")
        self._sleep(0.8)
        if self._should_fail():
            fault = self._rng.choice(_FAULT_LINES)
            self._log(fault)
            return 1, f"{cmd}: command failed\n{fault}"
        return 0, f"{cmd}: ok"

    def collect_logs(self, since_s: float = 0.0) -> str:
        if since_s <= 0:
            return "\n".join(line for _, line in self._log_buffer)
        cutoff = time.time() - since_s
        return "\n".join(line for ts, line in self._log_buffer if ts >= cutoff)

    def reboot(self) -> bool:
        if self._firmware_version is None:
            raise DUTError("no image flashed - nothing to reboot")
        self._booted = False
        self._log("system: reboot requested")
        self._sleep(10.0)
        return self.wait_for_boot()

    def close(self) -> None:
        self._booted = False