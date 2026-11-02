"""Execution tracing for the tool layer.

Trace events carry identifiers, tool versions, outcome codes and hashes of
arguments/results. They do not carry raw arguments or result payloads, so an
argument containing a phone number or account name cannot leak through tracing.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol

from .utils import canonical_json, deep_copy_json, now_iso


class TraceSink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...


class InMemoryTraceSink:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def emit(self, event: dict[str, Any]) -> None:
        record = {"at": now_iso(), **deep_copy_json(event)}
        with self._lock:
            self._events.append(record)

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return deep_copy_json(self._events)

    def for_trace(self, trace_id: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self.events()
            if event.get("trace_id") == trace_id
        ]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class NullTraceSink:
    def emit(self, event: dict[str, Any]) -> None:
        return None


class JsonlTraceSink:
    """Append-only JSONL trace sink for local demos and tests.

    Logging failures must not turn a completed operation into a failed one, so
    the registry swallows sink errors. Production deployments should use the
    existing immutable audit infrastructure instead.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(self, event: dict[str, Any]) -> None:
        record = {"at": now_iso(), **deep_copy_json(event)}
        line = canonical_json(record) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()


class CompositeTraceSink:
    def __init__(self, *sinks: TraceSink) -> None:
        self.sinks = sinks

    def emit(self, event: dict[str, Any]) -> None:
        for sink in self.sinks:
            sink.emit(event)


def safe_emit(sink: TraceSink | None, event: dict[str, Any]) -> None:
    if sink is None:
        return
    try:
        sink.emit(event)
    except Exception:
        # Observability must never change side-effect semantics. In production,
        # alert on sink failures out-of-band.
        return None
