# Synthetic Data Assumptions

This document describes the **per-store synthetic validation fixtures** used to prove analytics when real CCTV ENTRY events are missing or incomplete.

## Flow (unchanged)

```
scripts/generate_synthetic_demo_data.py
        ↓
data/synthetic/store_{1,2}/synthetic_events_*.jsonl + synthetic_pos_*.csv
        ↓
scripts/demo_validation_run.py
        ↓
store_{1,2}_validation.db  (isolated per store)
        ↓
ingestion → sessions → metrics → funnel → dashboard
```

## Store layout

| Store | `store_id` | Shoppers (target) | Top zones | Weak zones | Validation DB | Metric date (UTC) |
|-------|----------|-------------------|-----------|------------|---------------|-------------------|
| store_1 | `STORE_BLR_002` | ~92 | LAKME, PILGRIM, GOODVIBES | FARMSTAY, MARS, ALPS | `store_1_validation.db` | 2026-06-01 |
| store_2 | `STORE_BLR_003` | ~158 | MAMAEARTH, CETAPHIL, NEUTROGENA | D_AND_K, DERMACOMP | `store_2_validation.db` | 2026-04-10 |

Fixture files: `data/synthetic/store_{1,2}/synthetic_events_*.jsonl` and `synthetic_pos_*.csv`.

**Isolation:** store_1 synthetic data is ingested only into `store_1_validation.db`. store_2 never shares that database.

## Event schema

Every synthetic event matches the **challenge Event schema** emitted by `PipelineEmitter`:

- `event_id`, `store_id`, `camera_id`, `visitor_id`, `event_type`, `timestamp`
- `zone_id`, `dwell_ms`, `is_staff`, `confidence`, `metadata`

No NOTEBK rows. No legacy synthetic shapes. Events must pass `app.models.Event` validation via `ingest_event_dicts`.

### Event types used

| Camera | Event types |
|--------|-------------|
| CAM1 (`CAM_SHELF_01`) | `ZONE_ENTER`, `ZONE_DWELL`, `ZONE_EXIT` |
| CAM3 (`CAM_ENTRY_01`) | `ENTRY`, `EXIT`, `REENTRY` |
| CAM5 (`CAM_BILLING_01`) | `BILLING_QUEUE_JOIN`, `BILLING_QUEUE_ABANDON` |

**Queue completed:** There is no separate `queue_completed` event in the challenge schema. A successful queue visit is modeled as `BILLING_QUEUE_JOIN` **without** a subsequent `BILLING_QUEUE_ABANDON`, followed by POS within 0–5 minutes.

## Visitor IDs

Schema pattern: `^VIS_[a-z0-9]+$` (lowercase alphanumerics after `VIS_`).

| Cohort | IDs | Count (per store) |
|--------|-----|-------------------|
| Regular shoppers | `VIS_0001` … `VIS_0100` | 100 |
| Staff-like (not flagged at ingest) | `VIS_staff001`, `VIS_staff002`, `VIS_staff003` | 3 |
| CAM3 same-day reentry | First 20 shoppers | 20 |

> Note: Schema requires `VIS_` prefix with a **lowercase** suffix (`VIS_staff001`). `VIS_STAFF_001` is invalid.

All events set `"is_staff": false`. Staff classification runs later in analytics (`app/staff_detection.py`).

## Staff assumptions

Staff-like visitors are designed to satisfy heuristic thresholds **without** setting `is_staff` on events:

- **≥ 4 sessions** per staff visitor (multi-entry days)
- **≥ 8 unique zones** visited
- **≥ 30 minutes** total store time
- **≥ 3 REENTRY** events across sessions

Expected after ingest + staff analysis (store_1, date 2026-06-01):

- **Staff detected:** ≥ 3 (`VIS_staff001`–`VIS_staff003`)
- **Customer visitors:** total visitors − staff detected

## Reentry assumptions

- **≥ 20** visitors per store include a same-day CAM3 cycle:  
  `ENTRY → shop → EXIT → REENTRY → shop → EXIT` on one `visitor_id`
- Additional multi-session staff journeys use `REENTRY` for sessions after the first
- Exercises: session reconstruction, repeat-visitor metrics, reentry funnel stages

Expected:

- **REENTRY events in fixture:** ≥ 20 per store
- **Repeat visitor analytics:** non-zero on validation dashboard

## Queue assumptions

- Short queues: depth 1–3 off-peak
- Long queues: depth 4–9 at lunch (12:00–14:00) and evening (18:00–20:00)
- **Queue abandoners:** ~12 visitors with `BILLING_QUEUE_ABANDON`
- **Successful billing:** join without abandon → POS correlation window

Expected metrics (approximate, store_1):

| Metric | Expected range |
|--------|------------------|
| `billing_reach_rate` | 0.70 – 0.85 |
| `queue_abandonment_rate` | 0.10 – 0.20 |
| `current_queue_depth` | ≥ 0 (end-of-day snapshot) |

## Purchase / POS assumptions

POS rows use the same shape as production ingest:

`store_id`, `transaction_id`, `timestamp`, `basket_value_inr`

- **≥ 60% conversion** among the 100 base shoppers (target ~62 matched purchases)
- Converted visitors: POS timestamp **30–300 seconds** after queue join (within 0–5 minute window)
- **Matching cases:** `TXN_0001` style IDs aligned to `VIS_0001`
- **Non-matching:** `TXN_NOMATCH_{STORE}` (no visitor journey)
- **Ambiguous:** `TXN_AMBIG_{STORE}` (timestamp near multiple queue joins)

Expected (store_1, after staff analytics filtering):

| Metric | Expected |
|--------|----------|
| Staff detected | ≥ 3 (`VIS_staff001`–`VIS_staff003`) |
| Analytics conversion rate | ≥ 0.60 (100 shopper denominator; staff excluded) |
| Converted visitors (POS correlation) | ≥ 60 |
| Total revenue (INR) | > 0 |

## Expected validation outputs

After `python scripts/demo_validation_run.py --store all`:

| Check | store_1 | store_2 |
|-------|---------|---------|
| Events ingested | = events loaded, 0 rejected | same |
| Customer sessions | ≥ 100 | ≥ 100 |
| Unique visitors | ≥ 100 | ≥ 100 |
| REENTRY events | ≥ 20 | ≥ 20 |
| Conversion rate (analytics) | ≥ 0.60 | ≥ 0.60 |
| Funnel stages populated | yes | yes |
| Heatmap zones | > 0 | > 0 |

Reports:

- `demo_validation_report_store_1.md`
- `demo_validation_report_store_2.md`

## Regenerate fixtures

```powershell
python scripts/generate_synthetic_demo_data.py
python scripts/generate_synthetic_demo_data.py --store store_2
```

## Run validation (does not touch production DB)

```powershell
python scripts/demo_validation_run.py --store all
```

Dashboard (store_1 example):

```powershell
$env:DATABASE_URL = "sqlite:///./data/databases/store_1_validation.db"
$env:DEFAULT_METRIC_DATE = "2026-06-01"
uvicorn app.main:app --port 8000
streamlit run dashboard/streamlit_app.py
```

## Compatibility notes

- Legacy paths `data/synthetic/demo_events.jsonl` and `demo_validation.db` are **deprecated**; use per-store paths above.
- Both stores use `store_id = STORE_BLR_002` in fixtures (challenge ID); separation is by **validation DB file**, not by different store IDs.
- Purchase matching offline (`pipeline/purchase_matching.py`) uses **real pipeline JSONL**, not these synthetic files.
