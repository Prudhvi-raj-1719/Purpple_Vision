# CAM3 pre–Phase C integration

Production-capable stack in `cam3_processor.py`; orchestration still imports `entry_exit` until Phase C.

## Public API

```python
def process_cam3_video(
    video_path: Path | None = None,
    *,
    emitter: PipelineEmitter | None = None,
    show_window: bool = False,
    store: StoreConfig | None = None,
    camera_id: str | None = None,
    output_path: Path | None = None,
) -> Cam3Stats:
```

`Cam3Stats` matches `entry_exit.EntryExitStats` (`entry_count`, `exit_count`).

## Integration flow

```mermaid
flowchart TB
  subgraph orch [Orchestration - Phase C only]
    DR[demo_runner / run_pipeline_demo]
  end
  subgraph entry [Callable today]
    PCV[process_cam3_video]
    CFG[build_cam3_processor_config]
    STORE[(stores cam3.json + videos.json)]
  end
  subgraph per_clip [Per clip store_2 or single store_1]
    PV[process_video]
    ENG[entry_retail RetailEntryEngine]
    YOLO[YOLO + ByteTrack]
  end
  subgraph emit [Events]
    C3E[Cam3EventEmitter]
    PE[PipelineEmitter.emit_notbk]
    AD[event_adapter]
  end
  DR -.->|Phase C switch| PCV
  PCV --> CFG
  STORE --> CFG
  PCV -->|multi-clip loop| PV
  PCV -->|single CAM3 video| PV
  PV --> ENG
  PV --> YOLO
  PV --> C3E
  C3E -->|pipeline_emitter set| PE
  C3E -->|standalone CLI| JSONL[direct JSONL]
  PE --> AD
```

## Clip UTC

| Key | Source |
|-----|--------|
| `CAM3` | `videos.cameras.CAM3.clip_start` |
| `CAM3:entry1` | `cam3_clips[0].clip_start` |
| `CAM3:entry2` | `cam3_clips[1].clip_start` |

`_hydrate_emitter_clip_starts()` registers these on `PipelineEmitter.clip_start_by_camera`.
`Cam3EventEmitter` uses the same map via `clip_start_by_key` for `event_datetime` in NOTEBK rows.
