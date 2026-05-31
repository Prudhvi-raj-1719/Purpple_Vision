"""Event sink protocol for pipeline modules."""

from __future__ import annotations

from typing import Any, Protocol


class EventSink(Protocol):
    """Accept NOTEBK-shaped behavioural events for adapter-backed emission."""

    def emit_notbk(self, row: dict[str, Any]) -> object | None: ...
