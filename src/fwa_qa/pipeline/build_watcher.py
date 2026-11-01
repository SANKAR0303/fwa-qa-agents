"""Detects new firmware builds and announces them on the bus.

Polls a directory for image files. A build is "new" if its path has not
been seen before in this process. Where builds come from is deliberately
behind one method: swap _scan() for an artifact-server or CI query and
nothing else changes.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path

from ..core.bus import EventBus
from ..core.events import BuildDetected

log = logging.getLogger(__name__)

IMAGE_SUFFIXES = (".bin", ".img", ".tar", ".swu")

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)?)")


class BuildWatcher:
    """Watches a directory and publishes BuildDetected for new images."""

    name = "build-watcher"

    def __init__(
        self,
        bus: EventBus,
        watch_dir: str | Path,
        run_id: str = "",
    ) -> None:
        self.bus = bus
        self.watch_dir = Path(watch_dir)
        self.run_id = run_id
        self._seen: set[Path] = set()

    def _scan(self) -> Iterator[Path]:
        """Yield candidate image files. Override for a different source."""
        if not self.watch_dir.is_dir():
            log.warning("watch dir does not exist: %s", self.watch_dir)
            return
        for path in sorted(self.watch_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                yield path

    @staticmethod
    def parse_name(path: Path) -> tuple[str, str]:
        """Pull (version, variant) out of a filename.

        Unparseable names still produce a build - a missing version is
        not a reason to skip testing an image.
        """
        stem = path.stem
        match = _VERSION_RE.search(stem)
        version = match.group(1) if match else "unknown"

        tokens = [t for t in re.split(r"[-_]", stem) if t]
        if version != "unknown" and version in tokens:
            tokens.remove(version)
        variant = tokens[-1] if tokens else "default"

        return version, variant

    def poll(self) -> list[BuildDetected]:
        """Check once for new builds. Returns what it published."""
        found: list[BuildDetected] = []

        for path in self._scan():
            if path in self._seen:
                continue
            self._seen.add(path)

            version, variant = self.parse_name(path)
            event = BuildDetected(
                source=self.name,
                run_id=self.run_id,
                image_path=str(path),
                version=version,
                variant=variant,
            )
            log.info("new build %s (variant %s)", version, variant)
            self.bus.publish(event)
            found.append(event)

        return found

    def mark_seen(self, path: str | Path) -> None:
        """Treat a build as already handled without publishing it."""
        self._seen.add(Path(path))