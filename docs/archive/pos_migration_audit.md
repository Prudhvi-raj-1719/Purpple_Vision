# POS Migration Audit — NOTEBK → Purpple_Vision

**Date:** 2026-05-30  
**NOTEBK source:** `E:\NOTEBK\project\`  
**Purpple_Vision target:** `E:\Purpple_Vision\`

---

## 1. Search results (requested artifacts)

| Artifact | Purpple_Vision | NOTEBK |
|----------|----------------|--------|
| `Brigade_Bangalore_10_April_26.csv` | **Not found** | `project/data/Brigade_Bangalore_10_April_26.csv` |
| `aggregated_transactions.csv` | **Not found** | `project/outputs/aggregated_transactions.csv` |
| `aggregated_transactions.json` | **Not found** | `project/outputs/aggregated_transactions.json` |
| `pos_aggregation.py` | **Not found** | `project/pos/pos_aggregation.py` |
| `purchase_matching.py` | **Not found** | `project/matching/purchase_matching.py` |

No filename matches for any of the five targets inside `Purpple_Vision/`.

---

## 2. Migration status summary

| NOTEBK component | Migrated? | Purpple_Vision equivalent | Notes |
|------------------|-----------|---------------------------|-------|
| Raw POS CSV (`Brigade_Bangalore_…csv`) | **No** | — | Data not copied; path not in `pipeline/config.py` |
| `pos/explore_pos_data.py` | **No** | — | Schema/column exploration only in NOTEBK |
| `pos/pos_aggregation.py` | **No** | Partial: expects pre-aggregated CSV | Line-item → invoice aggregation not ported |
| `matching/normalize_event_timestamps.py` | **No** | `pipeline/video_time.py` + `event_adapter.py` | Clip anchors in `config.py`; no batch normalizer script |
| `matching/inspect_event_timestamps.py` | **No** | — | Diagnostic tooling only in NOTEBK |
| `matching/video_pos_overlap_analysis.py` | **No** | — | Pre-match overlap validation not ported |
| `matching/purchase_matching.py` | **Partial** | `app/pos_correlation.py` | Different model: session conversion vs per-invoice journey match |
| `analytics/retail_analytics.py` | **Partial** | `app/metrics.py`, `funnel.py`, `heatmap.py`, `anomalies.py` | API analytics vs offline report bundle |
| POS HTTP ingest | **New in Purpple** | `app/pos_ingestion.py` | Not in NOTEBK (seed/ORM only there) |
| POS DB persistence | **New in Purpple** | `app/db.py` (`pos_transactions` table) | NOTEBK used JSON/CSV outputs |
| POS CSV seed loader | **New in Purpple** | `scripts/seed_from_sample.py` | Challenge-schema CSV, not Brigade raw format |
| `pipeline/pos_loader.py` | **Stub only** | One-line docstring | Listed in DESIGN.md; no implementation |

---

## 3. POS files present in Purpple_Vision

| Path | Role | Status |
|------|------|--------|
| `app/pos_ingestion.py` | `POST /pos/ingest` — batch validate, idempotent persist | **Implemented** |
| `app/pos_correlation.py` | Session ↔ POS conversion (5 min window) | **Implemented** |
| `app/models.py` | `PosTransaction` Pydantic schema | **Implemented** |
| `app/db.py` | `PosTransactionRecord`, `fetch_store_pos_transactions()` | **Implemented** |
| `scripts/seed_from_sample.py` | Load `pos_transactions.csv` → SQLite | **Implemented** |
| `examples/pos_ingest_endpoint.json` | API example payload | **Present** |
| `tests/test_pos_ingestion.py` | Ingest idempotency / partial success | **Implemented** |
| `tests/test_metrics.py` | POS correlation window tests | **Implemented** |
| `pipeline/pos_loader.py` | Pipeline-side POS load for queue abandon | **Stub** |
| `.env.example` | `POS_TRANSACTIONS_PATH` | **Configured** |

**Expected data files (optional, often gitignored):**

- `./data/pos_transactions.csv` — challenge-format CSV (not Brigade raw)
- `./data/sample_events.jsonl` — companion event seed

**Not present:** Brigade raw CSV, aggregated transaction outputs, purchase match JSON/reports.

---

## 4. POS files still only in NOTEBK

| Path | Purpose |
|------|---------|
| `project/data/Brigade_Bangalore_10_April_26.csv` | Raw line-item POS export (103 rows, multi-column) |
| `project/pos/pos_aggregation.py` | Aggregate by `invoice_number` → CSV/JSON |
| `project/pos/explore_pos_data.py` | Schema discovery, column summary reports |
| `project/outputs/aggregated_transactions.csv` | 24 invoice-level rows (derived) |
| `project/outputs/aggregated_transactions.json` | Same, JSON array |
| `project/matching/purchase_matching.py` | Match invoices to normalized CAM1/2/5 events |
| `project/matching/normalize_event_timestamps.py` | Offset → wall-clock for event JSONL |
| `project/matching/inspect_event_timestamps.py` | Timestamp diagnostic reports |
| `project/matching/video_pos_overlap_analysis.py` | Verify event/POS time overlap before matching |
| `project/outputs/purchase_matches.json` | Per-invoice match results + confidence |
| `project/outputs/reports/purchase_matching_report.txt` | Match summary report |
| `project/analytics/retail_analytics.py` | Offline analytics bundle incl. purchase_matching_analytics |

---

## 5. Current CSV ingestion flow (Purpple_Vision)

```
┌─────────────────────────────────────────────────────────────────┐
│  Input: pos_transactions.csv (challenge schema)                   │
│  Columns: store_id, transaction_id, timestamp, basket_value_inr │
│  Example IDs: STORE_BLR_002, TXN_00441                          │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┴───────────────────┐
         ▼                                       ▼
  scripts/seed_from_sample.py              POST /pos/ingest
  load_pos_csv()                           app/pos_ingestion.py
         │                                       │
         └───────────────────┬───────────────────┘
                             ▼
              PosTransaction.model_validate()
                             │
                             ▼
              pos_transaction_to_record() → SQLite
              table: pos_transactions (PK: transaction_id)
                             │
                             ▼
              fetch_store_pos_transactions(store_id, day)
              used by metrics / funnel / anomalies
```

**Key code locations:**

- CSV parse: `scripts/seed_from_sample.py` → `load_pos_csv()` (lines 94–138)
- HTTP ingest: `app/pos_ingestion.py` → `ingest_pos_transaction_dicts()`
- ORM: `app/db.py` → `PosTransactionRecord`, `fetch_store_pos_transactions()`

**What is NOT ingested today:**

- Brigade raw CSV (`order_date`, `order_time`, `invoice_number`, line items, brands, etc.)
- NOTEBK `aggregated_transactions.json` format (`invoice_number`, `total_amount`, `product_names`, …)

---

## 6. Current purchase matching flow (Purpple_Vision)

Purpple does **session-level POS correlation** at query time, not offline per-invoice matching.

```
CCTV events (ingested) → build_sessions() → VisitorSession
                                              │
                                              ├─ reached_billing: bool
                                              └─ billing_activity_at: datetime | None

POS rows (SQLite) ────────────────────────────┐
                                              ▼
                              app/pos_correlation.py
                              is_session_converted(session, transactions)

Rule (PDF / CHOICES.md):
  txn.timestamp − 5 minutes ≤ billing_activity_at ≤ txn.timestamp
  AND same store_id, non-staff session

Consumers:
  app/metrics.py     → conversion_rate
  app/funnel.py      → converted_visitors
  app/anomalies.py   → conversion baseline checks
```

**Key code:** `app/pos_correlation.py` — `is_session_converted()`, `converted_visitor_ids()`

### NOTEBK purchase matching (not migrated)

```
aggregated_transactions.json
        +
cam{1,2,5}_events_normalized.jsonl
        │
        ▼
purchase_matching.py
  • 5-minute window around transaction_datetime
  • CAM5 QUEUE_ENTER / PAYMENT_ENTER events
  • CAM1/CAM2 ZONE_ENTER for journey
  • confidence_score, journey_summary per invoice
        │
        ▼
purchase_matches.json + purchase_matching_report.txt
```

**Semantic gap:** NOTEBK matches **invoices → event journeys** with confidence scores. Purpple matches **visitor sessions → POS txns** for funnel conversion metrics. Both use a 5-minute window but operate on different entities and produce different outputs.

---

## 7. Schema comparison

| Field | Brigade raw CSV | NOTEBK aggregated | Purpple `PosTransaction` |
|-------|-----------------|-------------------|--------------------------|
| Invoice / txn ID | `invoice_number` | `invoice_number` | `transaction_id` (`TXN_*`) |
| Store | `store_id` (`ST1008`) | — | `store_id` (`STORE_*`) |
| Timestamp | `order_date` + `order_time` | `transaction_datetime` | `timestamp` (UTC ISO) |
| Basket value | sum of `total_amount` | `total_amount` | `basket_value_inr` |
| Products/brands | per line item | `product_names`, `brand_names` | **Not stored** |

A migration bridge must map `ST1008` → `STORE_BLR_002`, `ML0426KAP…` → `TXN_*`, and aggregate line items before Purpple ingest.

---

## 8. Missing migration tasks

| Priority | Task | Source | Target suggestion |
|----------|------|--------|-------------------|
| P0 | Port `pos_aggregation.py` (line-item → invoice) | NOTEBK `pos/pos_aggregation.py` | `pipeline/pos_aggregation.py` or `scripts/aggregate_brigade_pos.py` |
| P0 | Copy or link Brigade raw CSV | NOTEBK `data/` | `data/pos/Brigade_Bangalore_10_April_26.csv` |
| P0 | Brigade → Purpple schema transform | Derived from aggregation | Extend `seed_from_sample.py` or new `scripts/import_brigade_pos.py` |
| P1 | Implement `pipeline/pos_loader.py` | Stub docstring | Load aggregated POS for pipeline-side queue-abandon correlation |
| P1 | Port `normalize_event_timestamps.py` | NOTEBK matching | `scripts/normalize_pipeline_events.py` for demo JSONL → wall-clock |
| P2 | Port `purchase_matching.py` (optional) | NOTEBK matching | `scripts/purchase_matching.py` for validation reports, or enrich API |
| P2 | Port `video_pos_overlap_analysis.py` | NOTEBK matching | Pre-flight check in `run_pipeline_demo.py` |
| P2 | Port `explore_pos_data.py` | NOTEBK pos | One-time data QA script |
| P3 | Store product/brand metadata on POS rows | NOTEBK aggregated JSON | DB schema extension (out of current API scope) |

---

## 9. Recommended Phase 5 work

Phase 5 in project docs targeted **PDF API completeness** (POS HTTP ingest, funnel, correlation window) — largely **done**. Remaining Phase 5-style work for **Brigade store end-to-end demo**:

### 5A — POS data path (offline → API)

1. Add `data/pos/` with Brigade CSV (or env `BRIGADE_POS_CSV_PATH`).
2. Migrate `pos_aggregation.py` → produce `data/generated/aggregated_transactions.json`.
3. Add `scripts/import_brigade_pos.py`:
   - Read aggregated JSON
   - Map `invoice_number` → `transaction_id`, `total_amount` → `basket_value_inr`, `ST1008` → `STORE_BLR_002`
   - Emit Purpple-format CSV or call `ingest_pos_transaction_dicts()` directly
4. Wire into `scripts/run_pipeline_demo.py` as optional post-step: events + POS → seed DB.

### 5B — Event ↔ POS validation (NOTEBK parity)

1. Port timestamp normalizer for pipeline demo JSONL (`cam*_events.jsonl` → wall-clock using `CAMERA_CLIP_START` from `pipeline/config.py`).
2. Port overlap analysis: confirm CAM5 event times intersect POS sale day before trusting conversion metrics.
3. Optional: port `purchase_matching.py` as **validation-only** script writing `logs/purchase_matching_report.txt` (does not replace `pos_correlation.py` API semantics).

### 5C — Pipeline integration

1. Flesh out `pipeline/pos_loader.py` to read aggregated transactions for CAM5 queue-abandon vs purchase attribution in offline reports.
2. Document full demo command sequence in README:

   ```text
   python scripts/run_pipeline_demo.py
   python scripts/aggregate_brigade_pos.py      # new
   python scripts/import_brigade_pos.py         # new
   python scripts/seed_from_sample.py --events ... --pos ...
   ```

### 5D — Analytics alignment

1. Compare `converted_visitor_ids()` (API) vs NOTEBK `purchase_matching.py` match counts on same day — document expected drift (session vs invoice granularity).
2. Add integration test with synthetic Brigade-shaped rows through aggregation → Purpple schema.

---

## 10. Architecture diagram (current vs target)

```
CURRENT (Purpple_Vision)
========================
CCTV pipeline → events JSONL → POST /events/ingest OR seed
Challenge pos_transactions.csv → seed OR POST /pos/ingest
                                      ↓
                              pos_correlation (runtime)
                                      ↓
                              metrics / funnel / anomalies API


TARGET (Phase 5 complete)
=========================
Brigade raw CSV → pos_aggregation → aggregated_transactions.json
                                         ↓
                              import_brigade_pos → SQLite / API
CCTV pipeline → normalize timestamps → events ingest
                                         ↓
                    ┌────────────────────┴────────────────────┐
                    ▼                                         ▼
           pos_correlation (API)              purchase_matching (validation report)
```

---

## 11. Conclusion

**Migrated from NOTEBK (conceptually):**

- POS persistence and HTTP ingest (upgraded beyond NOTEBK)
- 5-minute billing ↔ transaction correlation (`pos_correlation.py` ≈ simplified `purchase_matching.py` goal)
- Analytics consumption via REST API

**Still missing:**

- Brigade raw CSV and all NOTEBK POS/matching scripts
- Line-item aggregation pipeline
- Offline purchase matching with confidence scores and journey summaries
- Event timestamp batch normalization and overlap validation tooling
- `pipeline/pos_loader.py` implementation

Purpple_Vision is **API-ready for challenge-format POS data** but **not wired to Brigade store raw POS** without the aggregation and import bridge described in Phase 5A.
