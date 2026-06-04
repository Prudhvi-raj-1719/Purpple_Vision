"""Appearance-based Re-ID (CAM3 prototype, ported from NOTEBK)."""

from pipeline.reid.osnet_reid import OsnetEmbedder
from pipeline.reid.reid_manager import ReIDManager

__all__ = ["OsnetEmbedder", "ReIDManager"]
