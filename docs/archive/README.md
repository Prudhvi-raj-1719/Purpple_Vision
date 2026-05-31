# Archive — Historical Reports

Phase reports, audits, validation logs, migration analyses, and retired scripts. For current status see [README.md](../../README.md) and [PROJECT_STATE.md](../../PROJECT_STATE.md).

## Reports

| Report | Topic |
|--------|-------|
| [documentation_cleanup_report.md](documentation_cleanup_report.md) | Documentation reorganization log |
| [project_completion_report.md](project_completion_report.md) | Full repository completion audit |
| [repository_hygiene_report.md](repository_hygiene_report.md) | Pre-cleanup hygiene audit |
| [final_session_gap_report.md](final_session_gap_report.md) | Why 66 events → 0 sessions |
| [bridge_validation_report.md](bridge_validation_report.md) | Pipeline → SQLite bridge validation |
| [dashboard_validation_report.md](dashboard_validation_report.md) | Streamlit Phase 8 validation |
| [dashboard_readiness_report.md](dashboard_readiness_report.md) | Pre-implementation dashboard audit |
| [phase6_product_integration_report.md](phase6_product_integration_report.md) | Product integration architecture |
| [phase5_pos_migration_report.md](phase5_pos_migration_report.md) | Brigade POS migration |
| [pos_migration_audit.md](pos_migration_audit.md) | POS migration gap analysis |
| [purchase_matching_migration_report.md](purchase_matching_migration_report.md) | Purchase matching port |
| [brigade_pos_schema_mapping.md](brigade_pos_schema_mapping.md) | POS schema mapping |
| [cam3_performance_report.md](cam3_performance_report.md) | CAM3 frame-skipping fix |
| [camera_processing_audit.md](camera_processing_audit.md) | Inference frequency audit |
| [PHASE_6A_REPORT.md](PHASE_6A_REPORT.md) | Phase 6A API alignment |
| [PHASE_6B_REPORT.md](PHASE_6B_REPORT.md) | Phase 6B API completeness |

## Retired scripts (`scripts/`)

| Script | Former location | Notes |
|--------|-----------------|-------|
| [run_pipeline.sh](scripts/run_pipeline.sh) | `scripts/` | Phase 0 bash skeleton; use `run_pipeline_demo.py` |
| [run.sh](scripts/run.sh) | `pipeline/` | Duplicate skeleton |
| [capture_dashboard_screenshots.py](scripts/capture_dashboard_screenshots.py) | `scripts/` | One-time validation PNG generator |