# Bridge Validation Report - Pipeline to Product

**Store:** `STORE_BLR_002`  
**Metric date (UTC):** `2026-04-10`  
**Bridge script:** `scripts/bridge_pipeline_to_product.py`

## 1. Event ingestion (`ingest_event_dicts`)

| Metric | Value |
|--------|-------|
| Source files | cam1_events.jsonl, cam2_events.jsonl |
| Loaded from JSONL | 66 |
| Ingested (new) | 0 |
| Duplicates skipped | 66 |
| Rejected | 0 |

## 2. POS ingestion (`ingest_pos_transaction_dicts`)

| Metric | Value |
|--------|-------|
| Source CSV | `E:\Purpple_Vision\data\generated\pos\purpple_pos_transactions.csv` |
| Loaded from CSV | 24 |
| Ingested (new) | 0 |
| Duplicates skipped | 24 |
| Rejected | 0 |

## 3. Database verification

| Table | Total (store) | For metric day |
|-------|---------------|----------------|
| `events` | 66 | 66 |
| `pos_transactions` | 24 | 24 |

## 4. Sessions (`build_sessions`)

- Sessions created: **0**
- Customer (non-staff) sessions: **0**

> Note: Sessions open on ENTRY/REENTRY only. Zone-only pipeline demo events
> produce zero sessions until CAM3 entry events are ingested.

## 5. Analytics (direct compute functions — same as API handlers)

### Metrics (`compute_store_metrics`)

- unique_visitors: **0**
- conversion_rate: **0.0**
- total_sessions: **0**
- billing_reach_rate: **0.0**
- queue_abandonment_rate: **0.0**
- current_queue_depth: **0**

### Funnel (`compute_store_funnel`)

- unique_visitors: count=0, drop_off_pct=None
- reached_any_zone: count=0, drop_off_pct=None
- billing_queue: count=0, drop_off_pct=None
- converted_visitors: count=0, drop_off_pct=None
- overall_conversion_rate: **0.0**

### Heatmap (`compute_store_heatmap`)

- zones reported: **0**

### Anomalies (`compute_store_anomalies`)

- alerts: **0**

## 6. API compatibility check

| API endpoint | Internal function used | Compatible |
|--------------|------------------------|------------|
| `POST /events/ingest` | `ingest_event_dicts` | Yes — same code path |
| `POST /pos/ingest` | `ingest_pos_transaction_dicts` | Yes — same code path |
| `GET /stores/{id}/metrics` | `compute_store_metrics` | Yes |
| `GET /stores/{id}/funnel` | `compute_store_funnel` | Yes |
| `GET /stores/{id}/heatmap` | `compute_store_heatmap` | Yes |
| `GET /stores/{id}/anomalies` | `compute_store_anomalies` | Yes |

## 7. Load notes / errors

- cam1_events.jsonl: 24 events loaded
- cam2_events.jsonl: 42 events loaded
- purpple_pos_transactions.csv: 24 transactions loaded
