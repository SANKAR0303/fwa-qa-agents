"""A small in-process publish/subscribe bus.

Deliberately simple: synchronous, single-threaded, no external broker.
Handlers are called in registration order, and any events they return
are published in turn, so a chain of agents can react to each other.

If this ever needs to span machines, the interface is small enough to
reimplement over a real broker without touching the components.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import TypeVar

from .events import Event

log = logging.getLogger(__name__)

E = TypeVar("E", bound=Event)

Handler = Callable[[Event], "Iterable[Event] | None"]

MAX_CASCADE_DEPTH = 20


class EventBus:
    """Routes events to handlers subscribed by event type."""

    def __init__(self, max_depth: int = MAX_CASCADE_DEPTH) -> None:
        self._handlers: dict[type[Event], list[Handler]] = defaultdict(list)
        self._wildcard: list[Handler] = []
        self._history: list[Event] = []
        self._max_depth = max_depth

    def subscribe(self, event_type: type[E], handler: Handler) -> None:
        """Call handler whenever an event of this type is published."""
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """Call handler for every event. Useful for logging and reports."""
        self._wildcard.append(handler)

    def publish(self, event: Event, _depth: int = 0) -> None:
        """Deliver an event, then deliver anything the handlers emit."""
        if _depth > self._max_depth:
            log.error(
                "event cascade exceeded depth %d at %s - dropping",
                self._max_depth,
                event.kind,
            )
            return

        self._history.append(event)
        log.debug("publish %s from %s", event.kind, event.source)

        for handler in self._wildcard + self._handlers[type(event)]:
            try:
                emitted = handler(event)
            except Exception:
                log.exception("handler failed on %s", event.kind)
                continue

            for follow_up in emitted or ():
                self.publish(follow_up, _depth + 1)

    def history(self, event_type: type[Event] | None = None) -> list[Event]:
        """Every event published so far, optionally filtered by type."""
        if event_type is None:
            return list(self._history)
        return [e for e in self._history if isinstance(e, event_type)]

    def clear(self) -> None:
        """Forget the history. Handlers stay subscribed."""
        self._history.clear()