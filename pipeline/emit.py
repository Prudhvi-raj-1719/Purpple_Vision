"""Schema-compliant event builder and JSONL writer for the detection pipeline."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from app.models import Event

from pipeline.event_adapter import notbk_event_to_event, notbk_event_to_json_dict

logger = logging.getLogger(__name__)


@dataclass
class EmitStats:
    """Counters for pipeline emission."""

    notbk_received: int = 0
    purpple_written: int = 0
    adaptation_errors: int = 0


@dataclass
class PipelineEmitter:
    """
    Collect NOTEBK-shaped events and persist Purpple_Vision schema JSONL.

    All rows pass through ``event_adapter`` before write.
    """

    output_path: Path
    store_id: str
    clip_start_by_camera: dict[str, datetime] = field(default_factory=dict)
    default_confidence: float = 0.85
    stats: EmitStats = field(default_factory=EmitStats)
    _handle: TextIO | None = field(default=None, repr=False)
    _notbk_handle: TextIO | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._notbk_path = self.output_path.with_suffix(".notbk.jsonl")

    def open(self) -> None:
        """Open output files (truncates existing)."""
        self.output_path.write_text("", encoding="utf-8")
        self._notbk_path.write_text("", encoding="utf-8")
        self._handle = self.output_path.open("a", encoding="utf-8")
        self._notbk_handle = self._notbk_path.open("a", encoding="utf-8")

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        if self._notbk_handle is not None:
            self._notbk_handle.close()
            self._notbk_handle = None

    def __enter__(self) -> PipelineEmitter:
        self.open()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def emit_notbk(self, row: dict[str, Any]) -> Event | None:
        """
        Accept a NOTEBK event dict, optionally mirror raw JSONL, adapt, and write.

        Returns the Purpple Event when adaptation succeeds, else None.
        """
        self.stats.notbk_received += 1
        if self._notbk_handle is not None:
            self._notbk_handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        camera_key = str(row.get("camera", "CAM5"))
        clip_start = self.clip_start_by_camera.get(camera_key)

        try:
            event = notbk_event_to_event(
                row,
                store_id=self.store_id,
                clip_start=clip_start,
                confidence=self.default_confidence,
            )
        except (ValueError, KeyError, TypeError) as exc:
            self.stats.adaptation_errors += 1
            logger.warning("Event adaptation failed: %s row=%s", exc, row)
            return None

        self._write_event(event)
        return event

    def emit_adapted_dict(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """Adapt NOTEBK row to JSON dict without persisting (for tests)."""
        camera_key = str(row.get("camera", "CAM5"))
        clip_start = self.clip_start_by_camera.get(camera_key)
        try:
            return notbk_event_to_json_dict(
                row,
                store_id=self.store_id,
                clip_start=clip_start,
                confidence=self.default_confidence,
            )
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("Event adaptation failed: %s", exc)
            return None

    def _write_event(self, event: Event) -> None:
        if self._handle is None:
            raise RuntimeError("PipelineEmitter is not open; call open() first")
        payload = event.model_dump(mode="json")
        self._handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.stats.purpple_written += 1

    @property
    def notbk_mirror_path(self) -> Path:
        return self._notbk_path


def write_events_jsonl(
    rows: list[dict[str, Any]],
    output_path: Path,
    *,
    store_id: str,
    clip_start_by_camera: dict[str, datetime] | None = None,
) -> EmitStats:
    """Batch-write NOTEBK rows to Purpple JSONL via the adapter."""
    with PipelineEmitter(
        output_path=output_path,
        store_id=store_id,
        clip_start_by_camera=clip_start_by_camera or {},
    ) as emitter:
        for row in rows:
            emitter.emit_notbk(row)
        return emitter.stats
