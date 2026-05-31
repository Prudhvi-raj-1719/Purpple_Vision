"""Video frame index to offset timestamp helpers."""

from __future__ import annotations


def video_seconds(frame_index: int, fps: float) -> float:
    if fps <= 0:
        fps = 30.0
    return frame_index / fps


def format_video_offset(frame_index: int, fps: float) -> str:
    """Return NOTEBK-style HH:MM:SS.mmm offset from frame index."""
    total_seconds = video_seconds(frame_index, fps)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
