"""Clip-start helpers for pipeline emitters (store_1 single-file vs store_2 multi-clip CAM3)."""

from __future__ import annotations

from pipeline.config import emitter_clip_start_by_camera
from pipeline.store_config import get_store_config


def test_store_1_cam3_single_clip_start() -> None:
    cfg = get_store_config("store_1")
    anchors = emitter_clip_start_by_camera("CAM3", store=cfg)
    assert "CAM3" in anchors
    assert anchors["CAM3"].tzinfo is not None


def test_store_2_cam3_multi_clip_starts() -> None:
    cfg = get_store_config("store_2")
    anchors = emitter_clip_start_by_camera("CAM3", store=cfg)
    assert "CAM3" not in anchors
    assert set(anchors) == {"CAM3:entry1", "CAM3:entry2"}
    assert anchors["CAM3:entry1"].year == 2026


def test_store_2_cam1_has_single_anchor() -> None:
    cfg = get_store_config("store_2")
    anchors = emitter_clip_start_by_camera("CAM1", store=cfg)
    assert anchors == {"CAM1": anchors["CAM1"]}
