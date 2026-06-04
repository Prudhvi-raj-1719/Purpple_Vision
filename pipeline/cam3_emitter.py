"""
CAM3 event emitter: visitor registry, reentry, optional ReID.

Phase A: same wiring as NOTEBK ``events/event_emitter.py``, adapted for Purpple:
- NOTEBK-shaped rows use internal ``ENTRY`` / ``EXIT`` / ``REENTRY`` (see ``event_adapter``).
- Optional ``PipelineEmitter.emit_notbk()``; otherwise writes challenge-schema JSONL directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from pipeline.cam3.reentry_session import ReentrySessionManager, parse_utc_from_iso
from pipeline.cam3.time_utils import video_offset_to_utc_iso
from pipeline.cam3.visitor_registry import VisitorRegistry
from pipeline.config import CAMERA_PURPPLE_IDS, DEFAULT_STORE_ID
from pipeline.event_adapter import notbk_event_to_json_dict

from pipeline.cam3_layout import Cam3ProcessorConfig

if TYPE_CHECKING:
    from pipeline.emit import PipelineEmitter
    from pipeline.reid.reid_manager import ReIDManager


@dataclass
class EmitterStats:
    total: int = 0
    entry: int = 0
    exit: int = 0
    reentry: int = 0
    inits: int = 0

    def bump(self, internal_type: str) -> None:
        self.total += 1
        if internal_type == "ENTRY":
            self.entry += 1
        elif internal_type == "EXIT":
            self.exit += 1
        elif internal_type == "REENTRY":
            self.reentry += 1


class Cam3EventEmitter:
    """CAM3 transitions → NOTEBK rows → ``PipelineEmitter`` or direct JSONL."""

    def __init__(
        self,
        output_path: Path | None,
        notbk_camera_id: str,
        *,
        clip_id: Optional[str] = None,
        video_width: int = 0,
        video_height: int = 0,
        enable_reentry: bool = False,
        entry_plane_y_norm: float = 0.54,
        reentry_time_window_seconds: float = 300.0,
        reentry_location_max_norm_dist: float = 0.12,
        reentry_entry_y_tolerance: float = 0.04,
        confidence: float = 0.85,
        store_id: str = "",
        reid_manager: Optional["ReIDManager"] = None,
        heuristic_reentry_fallback: bool = False,
        pipeline_emitter: Optional["PipelineEmitter"] = None,
        clip_start_by_key: Optional[dict[str, str]] = None,
    ) -> None:
        self.notbk_camera_id = notbk_camera_id
        self.camera_id = CAMERA_PURPPLE_IDS.get(notbk_camera_id, notbk_camera_id)
        self.clip_id = clip_id
        self.video_width = video_width
        self.video_height = video_height
        self.confidence = confidence
        self.store_id = store_id
        self.stats = EmitterStats()
        self.registry = VisitorRegistry()
        self.reid_manager = reid_manager
        self.heuristic_reentry_fallback = heuristic_reentry_fallback
        self.pipeline_emitter = pipeline_emitter
        self.clip_start_by_key = clip_start_by_key or {}
        self.reentry: Optional[ReentrySessionManager] = None

        if output_path is not None:
            self.output_path = output_path
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text("", encoding="utf-8")
        else:
            self.output_path = None

        use_heuristic = enable_reentry and (
            reid_manager is None or heuristic_reentry_fallback
        )
        if use_heuristic and video_width > 0 and video_height > 0:
            self.reentry = ReentrySessionManager(
                time_window_seconds=reentry_time_window_seconds,
                location_max_norm_dist=reentry_location_max_norm_dist,
                entry_plane_y_norm=entry_plane_y_norm,
                entry_y_tolerance=reentry_entry_y_tolerance,
            )

    def log_init_terminal(self, init_debug: Dict[str, Any]) -> None:
        self.stats.inits += 1
        print(
            f"[INIT] visitor_id={init_debug.get('visitor_id')} "
            f"initial_side={init_debug.get('initial_side')} "
            f"initial_store_state={init_debug.get('initial_store_state')}"
        )

    def emit_internal(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        internal_type = str(payload.get("event_type", ""))
        byte_track_id = int(payload["visitor_id"])
        video_offset = str(payload["timestamp"])
        center = payload.get("center")
        zone_name = payload.get("zone")

        utc_iso = video_offset_to_utc_iso(
            self.notbk_camera_id,
            video_offset,
            clip_id=self.clip_id,
            clip_start_by_key=self.clip_start_by_key,
        )
        event_utc = parse_utc_from_iso(utc_iso)

        internal_emit_type = internal_type
        reentry_from_vis: Optional[str] = None
        reid_similarity: Optional[float] = None
        reid_matched_vis: Optional[str] = None
        suppress_write = False

        if self.reid_manager is not None:
            vis_id = self.reid_manager.vis_for_track(byte_track_id)

            if internal_type == "ENTRY":
                matched_vis, sim = self.reid_manager.match_entry(
                    byte_track_id, event_utc
                )
                if matched_vis:
                    vis_id = self.reid_manager.link_track(byte_track_id, matched_vis)
                    internal_emit_type = "REENTRY"
                    reentry_from_vis = matched_vis
                    reid_matched_vis = matched_vis
                    reid_similarity = sim
                elif hasattr(self.reid_manager, "_log_debug"):
                    self.reid_manager._log_debug(
                        byte_track_id,
                        vis_id,
                        similarity=sim,
                        matched_vis=None,
                        reason="entry_new_vis",
                    )

            elif internal_type == "EXIT":
                if not self.reid_manager.should_emit_exit(vis_id, event_utc):
                    if hasattr(self.reid_manager, "_log_debug"):
                        self.reid_manager._log_debug(
                            byte_track_id,
                            vis_id,
                            reason="exit_suppressed_duplicate",
                        )
                    suppress_write = True
                else:
                    self.reid_manager.record_exit(vis_id, byte_track_id, event_utc)

            if (
                not suppress_write
                and internal_emit_type in ("ENTRY", "REENTRY")
                and not self.reid_manager.should_emit_entry(vis_id, internal_emit_type)
            ):
                if hasattr(self.reid_manager, "_log_debug"):
                    self.reid_manager._log_debug(
                        byte_track_id,
                        vis_id,
                        reason="entry_suppressed_open_session",
                    )
                suppress_write = True

            if internal_emit_type in ("ENTRY", "REENTRY") and not suppress_write:
                bbox = payload.get("bbox")
                self.reid_manager.open_active_session(
                    vis_id,
                    byte_track_id,
                    event_utc,
                    bbox,
                )
        else:
            vis_id = self.registry.get_vis_id(byte_track_id)

        if (
            internal_type == "ENTRY"
            and internal_emit_type == "ENTRY"
            and self.reentry is not None
            and center is not None
        ):
            matched = self.reentry.match_reentry(
                tuple(center),
                event_utc,
                self.video_width,
                self.video_height,
            )
            if matched:
                vis_id = (
                    self.reid_manager.link_track(byte_track_id, matched)
                    if self.reid_manager
                    else self.registry.link_track(byte_track_id, matched)
                )
                internal_emit_type = "REENTRY"
                reentry_from_vis = matched
                self.reentry.consume_reentry(matched)

        if internal_emit_type in ("ENTRY", "REENTRY") and self.reentry is not None:
            self.reentry.on_entry(vis_id, event_utc)
        elif (
            internal_emit_type == "EXIT"
            and self.reentry is not None
            and center is not None
        ):
            self.reentry.on_exit(
                vis_id,
                byte_track_id,
                tuple(center),
                event_utc,
                self.video_width,
                self.video_height,
            )

        metadata: Dict[str, Any] = {
            "byte_track_id": byte_track_id,
            "video_offset": video_offset,
            "internal_event_type": internal_type,
        }
        if zone_name:
            metadata["sku_zone"] = zone_name
        if self.clip_id:
            metadata["clip_id"] = self.clip_id
        if payload.get("debug"):
            metadata["debug"] = payload["debug"]
        if reid_similarity is not None:
            metadata["reid_similarity"] = round(reid_similarity, 4)
        if reid_matched_vis:
            metadata["reid_matched_vis"] = reid_matched_vis
        if reentry_from_vis:
            metadata["reentry_from_vis"] = reentry_from_vis
            metadata["reentry_match"] = (
                "osnet"
                if self.reid_manager is not None and reid_matched_vis
                else "time_location_cache"
            )
        if internal_emit_type == "REENTRY":
            metadata["is_reentry"] = True

        row: Dict[str, Any] = {
            "visitor_id": vis_id,
            "camera": self.notbk_camera_id,
            "event_type": internal_emit_type,
            "timestamp": video_offset,
            "event_datetime": utc_iso,
            "confidence": self.confidence,
            "metadata": metadata,
        }

        if suppress_write:
            metadata["suppressed"] = True
            row["metadata"] = metadata
            return row

        self._write_row(row, internal_emit_type)
        if (
            self.reid_manager is not None
            and internal_emit_type in ("ENTRY", "REENTRY")
        ):
            self.reid_manager.mark_entry_event_emitted(vis_id)
        return row

    def emit_transition(
        self,
        event_row: Dict[str, Any],
        *,
        center: Optional[Tuple[int, int]] = None,
        bbox: Optional[list[float]] = None,
        adjust_engine: Any = None,
    ) -> Dict[str, Any]:
        payload = dict(event_row)
        if center is not None:
            payload["center"] = center
        if bbox is not None:
            payload["bbox"] = bbox
        row = self.emit_internal(payload)
        meta = row.get("metadata") or {}
        if adjust_engine is not None and meta.get("is_reentry"):
            if hasattr(adjust_engine, "entry_count") and adjust_engine.entry_count > 0:
                adjust_engine.entry_count -= 1
        if adjust_engine is not None and meta.get("suppressed"):
            internal = meta.get("internal_event_type", "")
            if internal == "EXIT" and getattr(adjust_engine, "exit_count", 0) > 0:
                adjust_engine.exit_count -= 1
            elif internal == "ENTRY" and getattr(adjust_engine, "entry_count", 0) > 0:
                adjust_engine.entry_count -= 1
        return row

    def _write_row(self, row: Dict[str, Any], internal_type: str) -> None:
        self.stats.bump(internal_type)
        print("[EVENT]")
        for key, value in row.items():
            print(f"{key}={value}")
        print()

        if self.pipeline_emitter is not None:
            self.pipeline_emitter.emit_notbk(row)
            return

        if self.output_path is not None:
            payload = notbk_event_to_json_dict(
                row,
                store_id=self.store_id or DEFAULT_STORE_ID,
                confidence=self.confidence,
                is_staff=False,
            )
            with self.output_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                handle.flush()

    def print_summary_cam3(self) -> None:
        print("=" * 40)
        print(f"ENTRY count: {self.stats.entry}")
        print(f"EXIT count: {self.stats.exit}")
        print(f"REENTRY count: {self.stats.reentry}")
        print(f"Track initializations (terminal only): {self.stats.inits}")
        if self.output_path is not None:
            print(f"Events written to: {self.output_path.resolve()}")
        elif self.pipeline_emitter is not None:
            print(
                f"Events via PipelineEmitter: "
                f"{self.pipeline_emitter.output_path.resolve()}"
            )


def build_cam3_event_emitter(
    config: Cam3ProcessorConfig,
    *,
    output_path: Path | None,
    clip_id: str | None = None,
    video_width: int = 0,
    video_height: int = 0,
    reid_manager: Optional["ReIDManager"] = None,
    pipeline_emitter: Optional["PipelineEmitter"] = None,
) -> Cam3EventEmitter:
    """Construct emitter from store-driven ``Cam3ProcessorConfig``."""
    return Cam3EventEmitter(
        output_path,
        config.camera_key,
        clip_id=clip_id,
        video_width=video_width,
        video_height=video_height,
        enable_reentry=True,
        entry_plane_y_norm=config.entry_plane_y_norm,
        reentry_time_window_seconds=config.reentry_time_window_seconds,
        reentry_location_max_norm_dist=config.reentry_location_max_norm_dist,
        reentry_entry_y_tolerance=config.reentry_entry_y_tolerance,
        confidence=config.default_event_confidence,
        store_id=config.store_id,
        reid_manager=reid_manager,
        heuristic_reentry_fallback=config.reid.heuristic_fallback,
        pipeline_emitter=pipeline_emitter,
        clip_start_by_key=config.clip_start_by_key,
    )
