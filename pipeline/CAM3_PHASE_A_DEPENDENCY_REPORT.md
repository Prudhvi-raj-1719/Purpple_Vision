# CAM3 Phase A — Dependency Report

Phase A copies the NOTEBK CAM3 architecture into Purple Vision with Purpple import paths only.

**Phase B (done):** store-config hydration via `build_cam3_processor_config(get_store_config())`. **No runtime wiring** — `pipeline/entry_exit.py` remains the active CAM3 path. See `CAM3_PHASE_B_CONFIG_MAPPING.md`.

## Copied / created files

| File | Source (NOTEBK) | Status |
|------|-----------------|--------|
| `pipeline/entry_retail.py` | `project/entry_retail.py` | Copied; local stability constants |
| `pipeline/cam3_processor.py` | `project/events/cam3_events.py` | Copied; Purpple imports; Phase A stubs |
| `pipeline/cam3_layout.py` | *(new)* | `build_cam3_layout()` — Phase B consumer |
| `pipeline/cam3_emitter.py` | `project/events/event_emitter.py` | Adapted; `Cam3EventEmitter` + Purpple rows |
| `pipeline/cam3/__init__.py` | — | Package |
| `pipeline/cam3/visitor_registry.py` | `project/events/visitor_registry.py` | Copied |
| `pipeline/cam3/reentry_session.py` | `project/events/reentry_session.py` | Copied |
| `pipeline/cam3/time_utils.py` | `project/events/event_time.py` | Merged; uses `pipeline.config.parse_clip_start` fallback |
| `pipeline/reid/__init__.py` | — | Package |
| `pipeline/reid/osnet_reid.py` | `project/reid/osnet_reid.py` | Copied |
| `pipeline/reid/reid_manager.py` | `project/reid/reid_manager.py` | Copied |
| `pipeline/reid/session_store.py` | `project/reid/session_store.py` | Copied |
| `pipeline/reid/settings.py` | `project/configs/reid_config.py` | Defaults module (not store-driven until Phase B) |

## Intentionally not ported

| NOTEBK | Purpple replacement |
|--------|---------------------|
| `events/event_schema.py` | `app/models.Event` + `pipeline/event_adapter.py` |
| `events/event_type_map.py` | `event_adapter.EVENT_TYPE_MAP` (includes `REENTRY`) |
| `events/zone_id_map.py` | `event_adapter.ZONE_ID_MAP` (CAM1/CAM5) |
| `configs/camera_timing_config.py` | `stores/store_*/cam3.json` via `store_config` (Phase B) |
| `configs/reid_config.py` | `cam3.json` `reid` block (Phase B) + `reid/settings.py` defaults (Phase A) |
| `configs/competition_config.py` | `store.json` + `camera_competition_ids` |

## Unresolved / optional runtime dependencies

Import-time (stdlib + existing Purpple stack):

- `cv2`, `numpy`, `supervision`, `ultralytics` — same as other camera processors

Optional (only when ReID enabled in Phase B+):

- `torch`, `torchreid` — see NOTEBK `requirements-reid.txt`; not added to Purpple root requirements in Phase A

Phase A module-level gaps (by design — fixed in Phase B):

- `cam3_processor.CAM3_LAYOUT` empty until `build_cam3_layout(store)` wired
- `cam3_processor.process_cam3_video()` raises `RuntimeError` (not wired)
- `cam3_processor.main()` still references legacy module constants (`_FOOTAGE2`, `CAM3_LAYOUT`) — do not run until Phase B
- `ReIDManager.video_utc_for_frame()` uses `time_utils` without `clip_start_by_key` until emitter passes store clip map (Phase B)
- `pipeline/reid/settings.py` static defaults — not read from `store.cam3.reid` until Phase B

## Files still needing migration (Phases B–E)

| Phase | Work |
|-------|------|
| **B** | Wire `build_cam3_layout(get_store_config())` into `cam3_processor`; load detection/byte_track/recovery/reentry/reid from `EntryCameraConfig`; pass `clip_start_by_key` to `Cam3EventEmitter`; remove `_CAM3_PHASE_A_STUB` constants |
| **C** | `demo_runner.py`, `run_pipeline_demo.py` → `from pipeline.cam3_processor import process_cam3_video`; delete `pipeline/entry_exit.py` |
| **D** | Validate `PURPPLE_STORE=store_1` (polygon, ReID off, frame skip 10) |
| **E** | Validate `store_2` (horizontal_y, inverted semantics, ReID, dual clips) |

## Unchanged (per Phase A constraints)

- `pipeline/entry_exit.py` — **still active**
- `pipeline/cam1_processor.py`, `cam2_processor.py`, `cam4_processor.py`, `queue.py`
- `scripts/demo_runner.py`, `app/**`
- `pipeline/emit.py`, `event_adapter.py`, `sink.py`

## Import graph (target modules)

```
cam3_processor → entry_retail, cam3_emitter, reid/*, config
cam3_emitter   → cam3/{visitor_registry,reentry_session,time_utils}, config, emit (TYPE_CHECKING)
cam3_layout    → store_config
reid_manager   → cam3/reentry_session, cam3/time_utils, entry_retail, reid/*
```
