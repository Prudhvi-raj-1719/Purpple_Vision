# CAM3 Phase B — Configuration mapping

Active runtime remains `pipeline/entry_exit.py`. The new stack reads **`get_store_config()`** only.

## `cam3.json` → runtime

| `cam3.json` path | `StoreConfig` / runtime | Consumer |
|------------------|-------------------------|----------|
| `entry.line_style` | `polygon` → `quad_lr`; `horizontal_y` → `horizontal_y` | `build_cam3_layout()` → `entry_retail` |
| `entry.entry_plane_y_norm` | layout + emitter + reentry | engine, `Cam3EventEmitter` |
| `entry.invert_retail_semantics` | layout `INVERT_RETAIL_SEMANTICS` | `entry_retail` |
| `entry.line_polygon` | `ENTRY_LINE_POLYGON` | geometry |
| `entry.store_ref` | `STORE_REF` | half-plane side |
| `detection.process_every_n_frames` | `Cam3ProcessorConfig.process_every_n_frames` | frame loop |
| `detection.confidence_threshold` | YOLO conf + ByteTrack `det_thresh` | `detect_persons`, tracker |
| `detection.iou_threshold` | YOLO IOU | `detect_persons` |
| `detection.yolo_imgsz` | YOLO `imgsz` (default 960 if null) | `detect_persons` |
| `detection.yolo_max_det` | YOLO `max_det` (default 50 if null) | `detect_persons` |
| `detection.progress_log_every_n_frames` | config field (logging Phase C+) | reserved |
| `byte_track.*` | tracker thresholds + `disable_bytetrack_env` | `create_byte_tracker()` |
| `recovery.*` | layout recovery keys | `build_retail_entry_engine()` |
| `reentry.*` | emitter reentry manager | `build_cam3_event_emitter()` |
| `reid.*` | `ReidSettings` via `reid_settings_from_config()` | `build_reid_manager()` |
| `competition_camera_id` | `Cam3ProcessorConfig.competition_camera_id` | metadata / adapter |

## `videos.json` → runtime

| Source | Runtime | Phase B behavior |
|--------|---------|------------------|
| `cameras.CAM3.video` + `clip_start` | `primary_video_path`, `clip_start_by_key["CAM3"]` | single-clip `main()` path |
| `cam3_clips[]` | `Cam3ProcessorConfig.cam3_clips` | **inventory only** (no processing) |
| `cam3_clips[].clip_id` | `CAM3:{clip_id}` in `clip_start_by_key` | UTC for future clip runs |
| `cam3_clips[].output_events_basename` | per-clip output path under `pipeline_output_dir` | logged, not written |

## Store examples

| Store | `line_style` | `invert_retail_semantics` | frame skip | ReID |
|-------|--------------|---------------------------|------------|------|
| store_1 | `polygon` | `false` | 10 | off |
| store_2 | `horizontal_y` | `true` | 2 | on (+ entry1/entry2 clips in `videos.json`) |

## API entry points

| Function | Role |
|----------|------|
| `load_cam3_processor_config(store=None)` | Hydrate from `PURPPLE_STORE` |
| `build_cam3_layout(store)` | Engine layout dict |
| `list_cam3_clips(store)` | Multi-clip descriptors |
| `build_cam3_event_emitter(config, ...)` | Store-driven emitter |
| `process_cam3_video()` | **Implemented** (orchestration still uses `entry_exit` until Phase C) |
