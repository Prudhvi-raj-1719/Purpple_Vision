# Store configuration (Phase 1)

Per-store camera geometry and pipeline tuning live under `stores/{store_key}/`.
Processors read these files via `pipeline/store_config.py` (Phase 2).

## Layout

```
stores/
├── store_1/          # Brigade Bangalore (Purple Vision defaults)
│   ├── store.json
│   ├── cam1.json … cam5.json
│   └── videos.json
└── store_2/          # NOTEBK Footage2 / competition footage
    ├── store.json
    ├── cam1.json, cam3.json, cam5.json (CAM2/CAM4 disabled — no footage)
    └── videos.json   # CAM3 uses ``cam3_clips`` (entry 1/2), not a single CAM3 mp4
```

### Demo cameras by store

| Store | Runnable in `demo_runner` | Skipped |
|-------|---------------------------|---------|
| `store_1` | CAM1–CAM5 (Brigade mp4s) | — |
| `store_2` | CAM1, CAM3 (2 entry clips → one `cam3_events.jsonl`), CAM5 | CAM2 (disabled), CAM4 (no `cam4.json`) |

## Load

```python
from pipeline.store_config import StoreConfig, get_store_config, load_store_config

# Active store from env (default store_1):
cfg = get_store_config()

# Explicit store:
cfg = load_store_config("store_2")
```

### Environment

| Variable | Default | Effect |
|----------|---------|--------|
| `PURPPLE_STORE` | `store_1` | Which `stores/{key}/` tree hydrates `pipeline/config.py` at import |
| `STORE_ID` | from `store.json` | Overrides competition `store_id` in emitters |
| `YOLO_MODEL_PATH` | from `store.json` | Overrides model weights path |

```powershell
$env:PURPPLE_STORE = "store_2"
python -m pipeline.cam1_processor
```

Or pass `store=` into `process_cam*_video(..., store=load_store_config("store_2"))`.

## JSON schema (version 1)

### `store.json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `schema_version` | int | yes | Must be `1` |
| `store_key` | string | yes | Directory name (`store_1`, `store_2`) |
| `store_id` | string | yes | Competition `store_id` |
| `display_name` | string | yes | Human label |
| `database_path` | string | no | Relative SQLite path (Phase 4+) |
| `pos_csv_path` | string | yes | Relative POS CSV path |
| `pos_store_code` | string | no | POS filter code (store_1) |
| `pos_sale_date` | string | yes | `YYYY-MM-DD` |
| `yolo_model_path` | string | yes | Relative model weights path |
| `output_subdir` | string | yes | Under `data/outputs/pipeline/` |
| `default_event_confidence` | number | yes | Canonical event confidence |
| `camera_competition_ids` | object | yes | `CAM1`…`CAM5` → competition camera_id |

### `cam1.json` / `cam2.json`

| Field | Type | Required |
|-------|------|----------|
| `schema_version` | int | yes |
| `camera_key` | string | yes |
| `enabled` | bool | yes |
| `competition_camera_id` | string | if enabled |
| `coordinate_system` | `"normalized"` | yes |
| `zones` | object | zone name → `[[x,y],…]` |
| `zone_id_map` | object | optional brand → competition zone_id |
| `overlap` | object | `min_overlap_pct`, `min_zone_stability_frames`, `lost_track_frames` |
| `dwell` | object | `min_dwell_seconds`, `min_zone_dwell_ms` |
| `detection` | object | `confidence_threshold`, `iou_threshold`, `process_every_n_frames`, `progress_log_every_n_frames` |

### `cam3.json`

| Field | Type | Required |
|-------|------|----------|
| `schema_version` | int | yes |
| `camera_key` | string | yes |
| `enabled` | bool | yes |
| `entry` | object | `line_polygon`, `store_ref`, `line_style`, `entry_plane_y_norm`, `invert_retail_semantics` |
| `detection` | object | confidence, iou, imgsz, max_det, frame skip |
| `byte_track` | object | activation, min consecutive, max_time_lost |
| `recovery` | object | stability, threshold, track-loss, late-entry flags |
| `reentry` | object | time window, location dist, entry y tolerance |
| `reid` | object | enabled + OSNet/session thresholds |

### `cam4.json` (optional — store_1 only when staff-camera footage exists)

Omit this file entirely for stores without CAM4 footage (e.g. store_2). The loader treats a missing file as CAM4 disabled.

| Field | Type | Required |
|-------|------|----------|
| `schema_version` | int | yes |
| `camera_key` | string | yes |
| `enabled` | bool | yes |
| `detection` | object | frame skip, progress log, confidence, iou |
| `emit_events` | bool | yes | Always `false` (robustness only) |

### `cam5.json`

| Field | Type | Required |
|-------|------|----------|
| `schema_version` | int | yes |
| `camera_key` | string | yes |
| `enabled` | bool | yes |
| `coordinate_system` | `"normalized"` \| `"pixel"` | yes |
| `annotation_canvas` | object | if pixel: `width`, `height` |
| `zones` | object | normalized coords or pixel arrays |
| `zone_priority` | string[] | yes |
| `zone_id_map` | object | optional |
| `overlap`, `dwell`, `detection` | object | same as CAM1 |

### `videos.json`

| Field | Type | Required |
|-------|------|----------|
| `schema_version` | int | yes |
| `cctv_dir` | string | yes | Relative directory for MP4s |
| `cameras` | object | per `CAMn`: `video`, `clip_start` (optional if multi-clip) |
| `cam3_clips` | array | store_2 only: `clip_id`, `video`, `clip_start`, optional `process_every_n_frames` (overrides `cam3.json` detection stride per clip) |
