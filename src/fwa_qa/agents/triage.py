"""Groups test failures by apparent root cause using a local model.

This is the one component where a language model earns its place: the
input is unstructured log text and failure output, and the useful output
is a judgement about which failures are the same problem. Everything
else in this pipeline is deterministic and stays that way.

The model is asked for strict JSON against a fixed schema. If it returns
something unusable, the agent falls back to one cluster per failure
rather than failing the run - a worse answer is better than no report.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ..core.events import (
    Event,
    FailureCluster,
    Severity,
    TestCaseFinished,
    TriageCompleted,
    TriageRequested,
)
from .base import Agent, LLMUnavailable

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a test triage assistant for network gateway
firmware validation. You group test failures that share a root cause.

Rules:
- Return ONLY valid JSON. No prose, no code fences.
- Every failure id given to you must appear in exactly one cluster.
- Do not invent failure ids.
- confidence is 0.0 to 1.0, reflecting how sure you are the grouped
  failures really share one cause.
- severity is one of: info, warning, error, critical.
"""

USER_TEMPLATE = """Suite: {suite}

Failures:
{failures}

Device log:
{device_log}

Group these failures by root cause. Respond with JSON of this shape:

{{
  "clusters": [
    {{
      "summary": "short description of what went wrong",
      "suspected_cause": "the underlying cause you infer",
      "case_ids": ["WIFI-001"],
      "confidence": 0.8,
      "severity": "error"
    }}
  ],
  "notes": "anything else worth flagging, or an empty string"
}}
"""

MAX_LOG_CHARS = 4000


class TriageAgent(Agent):
    """Clusters failures and publishes a triage report."""

    name = "triage-agent"

    def __init__(self, bus, model: str = "qwen2.5:7b") -> None:
        super().__init__(model=model)
        self.bus = bus
        bus.subscribe(TriageRequested, self.handle)

    @staticmethod
    def _format_failures(failures: tuple[TestCaseFinished, ...]) -> str:
        lines = []
        for f in failures:
            lines.append(f"- {f.case_id} ({f.name}): {f.output.strip()}")
        return "\n".join(lines)

    def _fallback(self, request: TriageRequested) -> tuple[FailureCluster, ...]:
        """One cluster per failure, used when the model is unusable."""
        return tuple(
            FailureCluster(
                summary=f.name,
                suspected_cause="not analysed - model unavailable",
                case_ids=(f.case_id,),
                confidence=0.0,
                severity=Severity.ERROR,
            )
            for f in request.failures
        )

    def _parse(self, data: object, valid_ids: set[str]) -> tuple[FailureCluster, ...]:
        """Turn the model's JSON into clusters, dropping anything invalid."""
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")

        clusters = []
        for raw in data.get("clusters", []):
            if not isinstance(raw, dict):
                continue

            ids = tuple(
                str(i) for i in raw.get("case_ids", []) if str(i) in valid_ids
            )
            if not ids:
                continue

            try:
                severity = Severity(str(raw.get("severity", "error")).lower())
            except ValueError:
                severity = Severity.ERROR

            try:
                confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
            except (TypeError, ValueError):
                confidence = 0.5

            clusters.append(
                FailureCluster(
                    summary=str(raw.get("summary", "")).strip() or "unlabelled",
                    suspected_cause=str(raw.get("suspected_cause", "")).strip(),
                    case_ids=ids,
                    confidence=confidence,
                    severity=severity,
                )
            )

        return tuple(clusters)

    def handle(self, event: Event) -> Iterable[Event]:
        assert isinstance(event, TriageRequested)

        if not event.failures:
            return []

        valid_ids = {f.case_id for f in event.failures}
        prompt = USER_TEMPLATE.format(
            suite=event.suite,
            failures=self._format_failures(event.failures),
            device_log=event.device_log[-MAX_LOG_CHARS:],
        )

        notes = ""
        try:
            data = self.complete_json(prompt, SYSTEM_PROMPT)
            clusters = self._parse(data, valid_ids)
            notes = str(data.get("notes", "")) if isinstance(data, dict) else ""
        except (LLMUnavailable, ValueError) as exc:
            log.warning("triage fell back: %s", exc)
            clusters = self._fallback(event)
            notes = f"triage degraded: {exc}"

        # Any failure the model dropped still needs to appear somewhere.
        covered = {cid for c in clusters for cid in c.case_ids}
        missing = valid_ids - covered
        if missing:
            log.warning("model omitted %d failures - adding them", len(missing))
            clusters = clusters + tuple(
                FailureCluster(
                    summary=f.name,
                    suspected_cause="not grouped by model",
                    case_ids=(f.case_id,),
                    confidence=0.0,
                )
                for f in event.failures
                if f.case_id in missing
            )

        return [
            TriageCompleted(
                source=self.name,
                run_id=event.run_id,
                suite=event.suite,
                clusters=clusters,
                model=self.model,
                notes=notes,
            )
        ]