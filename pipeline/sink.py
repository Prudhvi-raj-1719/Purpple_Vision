"""Event sink protocol for pipeline modules."""

from __future__ import annotations

from typing import Any, Protocol


class EventSink(Protocol):
    """Accept internal pipeline rows for challenge-schema JSONL emission."""

    def emit_notbk(self, row: dict[str, Any]) -> object | None: ...
