"""Base class for LLM-backed agents.

The model is reached through one method, complete(), so swapping Ollama
for a hosted API later is a change in one place. Agents own their prompt
and their parsing; the base owns the call, the retry and the JSON
extraction.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from ..core.events import Event

log = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen2.5:7b"

# Small models often wrap JSON in prose or code fences.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMUnavailable(RuntimeError):
    """The model backend could not be reached."""


class Agent(ABC):
    """An agent that reacts to events, optionally consulting a model."""

    name: str = "agent"

    def __init__(self, model: str = DEFAULT_MODEL, temperature: float = 0.1) -> None:
        self.model = model
        self.temperature = temperature

    @abstractmethod
    def handle(self, event: Event) -> Iterable[Event]:
        """React to an event, optionally emitting more."""

    def complete(self, prompt: str, system: str = "") -> str:
        """Send a prompt to the model and return the raw text reply."""
        try:
            import ollama
        except ImportError as exc:
            raise LLMUnavailable("ollama package not installed") from exc

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            reply = ollama.chat(
                model=self.model,
                messages=messages,
                options={"temperature": self.temperature},
            )
        except Exception as exc:
            raise LLMUnavailable(f"model call failed: {exc}") from exc

        return reply["message"]["content"]

    def complete_json(self, prompt: str, system: str = "") -> Any:
        """Call the model and parse its reply as JSON.

        Tolerates code fences and leading prose, which small models
        produce regularly even when told not to.
        """
        raw = self.complete(prompt, system)

        fenced = _FENCE_RE.search(raw)
        if fenced:
            raw = fenced.group(1)

        raw = raw.strip()
        start = min(
            (i for i in (raw.find("{"), raw.find("[")) if i != -1),
            default=-1,
        )
        if start > 0:
            raw = raw[start:]

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("model returned unparseable JSON: %s", raw[:200])
            raise LLMUnavailable("model did not return valid JSON") from exc