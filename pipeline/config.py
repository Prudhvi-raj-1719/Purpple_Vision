"""Brigade store CCTV paths, zone geometry, and clip timing anchors."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
CCTV_DIR = Path(os.getenv("CCTV_FOOTAGE_DIR", DATA_DIR / "cctv" / "Brigade_Bangalore"))
OUTPUT_DIR = Path(os.getenv("PIPELINE_OUTPUT_DIR", DATA_DIR / "generated"))
MODEL_PATH = Path(os.getenv("YOLO_MODEL_PATH", REPO_ROOT / "models" / "yolo11m.pt"))

DEFAULT_STORE_ID = os.getenv("STORE_ID", "STORE_BLR_002")

# Brigade POS (raw line-item CSV → aggregated invoice JSON).
POS_DIR = DATA_DIR / "pos"
BRIGADE_POS_CSV_PATH = Path(
    os.getenv(
        "BRIGADE_POS_CSV_PATH",
        POS_DIR / "Brigade_Bangalore_10_April_26.csv",
    )
)
BRIGADE_POS_STORE_CODE = "ST1008"
AGGREGATED_POS_DIR = OUTPUT_DIR / "pos"
AGGREGATED_TRANSACTIONS_JSON = AGGREGATED_POS_DIR / "aggregated_transactions.json"
AGGREGATED_TRANSACTIONS_CSV = AGGREGATED_POS_DIR / "aggregated_transactions.csv"
PURPPLE_POS_CSV = AGGREGATED_POS_DIR / "purpple_pos_transactions.csv"

# Pipeline demo outputs + purchase matching (offline analytics).
PIPELINE_DEMO_DIR = OUTPUT_DIR / "pipeline_demo"
PURCHASE_MATCHES_JSON = OUTPUT_DIR / "purchase_matches.json"

# Clip UTC anchors (from NOTEBK camera_timing_config; CAM3 estimated until overlay verified).
CAMERA_CLIP_START: Dict[str, str] = {
    "CAM1": "2026-04-10 20:10:27",
    "CAM2": "2026-04-10 20:10:02",
    "CAM3": "2026-04-10 20:10:15",
    "CAM5": "2026-04-10 20:09:48",
}

CAMERA_VIDEO_FILES: Dict[str, Path] = {
    "CAM1": CCTV_DIR / "CAM 1.mp4",
    "CAM2": CCTV_DIR / "CAM 2.mp4",
    "CAM3": CCTV_DIR / "CAM 3.mp4",
    "CAM5": CCTV_DIR / "CAM 5.mp4",
}

CAMERA_PURPPLE_IDS: Dict[str, str] = {
    "CAM1": "CAM_SHELF_01",
    "CAM2": "CAM_SHELF_02",
    "CAM3": "CAM_ENTRY_01",
    "CAM5": "CAM_BILLING_01",
}

# CAM3 entry line (normalized coordinates).
CAM3_ENTRY_LINE_POLYGON: List[Tuple[float, float]] = [
    (0.5950, 0.4444),
    (0.4498, 0.7510),
    (0.4714, 0.7759),
    (0.6121, 0.4566),
]

# CAM5 billing zones (normalized).
CAM5_ZONES: Dict[str, List[Tuple[float, float]]] = {
    "BillingQueue": [
        (0.0016, 0.1970),
        (0.2625, 0.1934),
        (0.0142, 0.9196),
        (0.0000, 0.7044),
    ],
    "PaymentArea": [
        (0.0763, 0.7326),
        (0.1089, 0.7273),
        (0.2531, 0.2871),
        (0.2267, 0.2871),
        (0.1594, 0.4869),
    ],
}

CAM5_ZONE_PRIORITY: Tuple[str, ...] = ("PaymentArea", "BillingQueue")

PERSON_CLASS_ID = 0
DEFAULT_CONFIDENCE = 0.85
MIN_ZONE_DWELL_MS = 30_000

# Shared zone-engagement pipeline tuning (from NOTEBK cam1/cam2).
OUT_OF_ZONE = "OUT_OF_ZONE"
CONFIDENCE_THRESHOLD = 0.35
IOU_THRESHOLD = 0.5
MIN_OVERLAP_PCT = 10
LOST_TRACK_FRAMES = 30
MIN_ZONE_STABILITY_FRAMES = 15
MIN_DWELL_SECONDS = 2.0
PROCESS_EVERY_N_FRAMES = 10
PROGRESS_LOG_EVERY_N_FRAMES = 100

# CAM1 shelf zones (normalized coordinates). Zone names preserved for events.
CAM1_ZONES: Dict[str, List[Tuple[float, float]]] = {
    "Minimalist_top": [
        (0.7323, 0.0391),
        (0.7298, 0.0651),
        (0.7338, 0.0712),
        (0.7557, 0.0712),
        (0.7821, 0.0625),
        (0.7885, 0.0538),
        (0.7518, 0.0382),
    ],
    "FarmStay": [
        (0.0010, 0.1302),
        (0.0642, 0.7743),
        (0.2168, 0.7077),
        (0.1835, 0.0696),
    ],
    "TheFaceShop": [
        (0.1950, 0.0588),
        (0.2173, 0.6821),
        (0.3727, 0.6024),
        (0.3749, 0.0265),
    ],
    "GoodVibes": [
        (0.3840, 0.0035),
        (0.3786, 0.6108),
        (0.5122, 0.5561),
        (0.5298, 0.0035),
    ],
    "DermaCo": [
        (0.5364, 0.0069),
        (0.5116, 0.5477),
        (0.6191, 0.4993),
        (0.6443, 0.0182),
    ],
    "Minimalist": [
        (0.6488, 0.0208),
        (0.7292, 0.0376),
        (0.6997, 0.4865),
        (0.6212, 0.5208),
    ],
    "Aquologica": [
        (0.7328, 0.0434),
        (0.7872, 0.0562),
        (0.7552, 0.4542),
        (0.7008, 0.4694),
    ],
    "Pilgrim": [
        (0.7945, 0.0557),
        (0.8380, 0.0701),
        (0.8065, 0.4345),
        (0.7589, 0.4470),
    ],
    "D&K": [
        (0.8389, 0.0820),
        (0.8743, 0.0883),
        (0.8446, 0.4173),
        (0.8101, 0.4378),
    ],
}

# CAM2 shelf zones (normalized). Includes LAKME and partner brands.
CAM2_ZONES: Dict[str, List[Tuple[float, float]]] = {
    "MAYBELLINE": [
        (0.8453, 0.1821),
        (0.7621, 0.8552),
        (0.8973, 0.9500),
        (0.9972, 0.2425),
    ],
    "FACESCANADA": [
        (0.6370, 0.7181),
        (0.6663, 0.1349),
        (0.8210, 0.1721),
        (0.7643, 0.8226),
    ],
    "LAKME": [
        (0.5451, 0.1182),
        (0.6663, 0.1326),
        (0.6349, 0.7195),
        (0.5261, 0.6371),
    ],
    "swiss Beauty": [
        (0.4515, 0.1114),
        (0.4438, 0.5596),
        (0.5215, 0.6198),
        (0.5433, 0.1128),
    ],
    "MARS": [
        (0.3897, 0.1062),
        (0.4536, 0.1134),
        (0.4494, 0.5348),
        (0.3778, 0.4920),
    ],
    "ALPS": [
        (0.3369, 0.1060),
        (0.3887, 0.1051),
        (0.3802, 0.4866),
        (0.3350, 0.4537),
    ],
    "LOREAL": [
        (0.2988, 0.1073),
        (0.3377, 0.1058),
        (0.3346, 0.4502),
        (0.2994, 0.4165),
    ],
    "EASTIND": [
        (0.2769, 0.1088),
        (0.2990, 0.1078),
        (0.2982, 0.4100),
        (0.2768, 0.3905),
    ],
}


def parse_clip_start(camera_key: str) -> datetime:
    """Return naive UTC clip start for a NOTEBK-style camera key (e.g. CAM3)."""
    raw = CAMERA_CLIP_START.get(camera_key)
    if raw is None:
        raise KeyError(f"No clip start configured for {camera_key}")
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
