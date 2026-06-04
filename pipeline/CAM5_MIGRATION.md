# CAM5 migration summary

NOTEBK `events/cam5_events.py` → Purpple `cam5_processor.py` + `cam5_layout.py`.

## Store configuration (already present)

| Store | `cam5.json` | Video (`videos.json`) |
|-------|-------------|------------------------|
| **store_1** | Normalized polygons, frame skip **10** | `data/cctv/Brigade_Bangalore/CAM 5.mp4` |
| **store_2** | Pixel zones on 1646×1850 canvas, frame skip **5** | `data/cctv_footage2/billing_area.mp4` |

## Runtime

| Before | After |
|--------|--------|
| `pipeline.queue` | `pipeline.cam5_processor` |
| Partial store wiring (detection only) | Full `cam5.json`: overlap, dwell, zones, detection |
| Hardcoded `MIN_*` module constants | `build_cam5_processor_config(store)` |

## Rollback

```python
from pipeline.queue import CAMERA_KEY as CAM5_KEY, process_cam5_video
```

`pipeline/queue.py` is unchanged.

## CLI

```powershell
$env:PURPPLE_STORE = "store_1"   # or store_2
python -m pipeline.cam5_processor
```
