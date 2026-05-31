"""Person detection module using YOLO11m on CCTV video frames."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import supervision as sv
from ultralytics import YOLO

from pipeline.config import CONFIDENCE_THRESHOLD, IOU_THRESHOLD, MODEL_PATH, PERSON_CLASS_ID


@lru_cache(maxsize=1)
def load_yolo_model(model_path: str | None = None) -> YOLO:
    """Load YOLO11m (cached singleton per process)."""
    path = str(model_path or MODEL_PATH)
    return YOLO(path)


def detect_persons(
    frame_bgr: np.ndarray,
    yolo_model: YOLO,
    *,
    conf: float = CONFIDENCE_THRESHOLD,
    iou: float = IOU_THRESHOLD,
    class_id: int = PERSON_CLASS_ID,
) -> sv.Detections:
    """Run YOLO and return person-only detections."""
    results = yolo_model.predict(
        source=frame_bgr,
        conf=conf,
        iou=iou,
        classes=[class_id],
        verbose=False,
        stream=False,
    )
    detections = sv.Detections.from_ultralytics(results[0])
    del results
    return detections
