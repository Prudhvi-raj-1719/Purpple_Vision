# Phase 5A + 5C — Brigade POS Migration Report

**Date:** 2026-05-30  
**Module:** `pipeline/pos_loader.py`  
**Validation run:** `e:\NOTEBK\project\data\Brigade_Bangalore_10_April_26.csv`

---

## 1. Summary

Purpple_Vision can now load the real Brigade POS export, aggregate line items to invoice level (NOTEBK-compatible), and produce Purpple-ingestible transaction rows.

| Deliverable | Status | Path |
|-------------|--------|------|
| Brigade CSV loader | Done | `pipeline/pos_loader.py` |
| Invoice aggregation | Done | `aggregate_invoices()` |
| NOTEBK JSON output | Done | `data/generated/pos/aggregated_transactions.json` |
| NOTEBK CSV output | Done | `data/generated/pos/aggregated_transactions.csv` |
| Purpple seed CSV | Done | `data/generated/pos/purpple_pos_transactions.csv` |
| Schema mapping doc | Done | `brigade_pos_schema_mapping.md` |
| Config paths | Done | `pipeline/config.py` |

Purchase matching (`purchase_matching.py`) was **not** implemented (out of scope).

---

## 2. Aggregation results

| Metric | Value |
|--------|-------|
| **Line items loaded** | 101 |
| **Invoice count** | **24** |
| **Total revenue (INR)** | **34,331.71** |
| **Average basket (INR)** | 1,430.49 |
| **Highest invoice (INR)** | 8,243.23 |
| **Datetime parse failures** | 0 |
| **Purpple-compatible rows** | **24 / 24** |

---

## 3. Aggregation validation

### 3.1 NOTEBK parity check

Compared `data/generated/pos/aggregated_transactions.json` against NOTEBK reference `NOTEBK/project/outputs/aggregated_transactions.json`:

| Check | Result |
|-------|--------|
| Invoice count | 24 = 24 |
| Total revenue | INR 34,331.71 = 34,331.71 |
| JSON schema keys | Identical 10 fields |
| Per-invoice field equality | **0 mismatches** |

Schema fields: `invoice_number`, `order_id`, `transaction_datetime`, `customer_number`, `salesperson_name`, `product_names`, `brand_names`, `categories`, `total_quantity`, `total_amount`.

### 3.2 Internal consistency

- Every line item assigned to exactly one invoice via `invoice_number` groupby.
- `total_amount` per invoice equals sum of line-item `total_amount` values.
- `total_quantity` per invoice equals sum of line-item `qty` values.
- `transaction_datetime` derived from `order_date` + `order_time` using `%d-%m-%Y %H:%M:%S`.

### 3.3 Purpple schema validation

All 24 aggregated records validated successfully against `app.models.PosTransaction`:

- `store_id`: `STORE_BLR_002`
- `transaction_id`: `TXN_{invoice_number}` (pattern `^TXN_[A-Z0-9_]+$`)
- `timestamp`: UTC ISO-8601
- `basket_value_inr`: non-negative float from `total_amount`

---

## 4. Compatibility with existing Purpple ingestion APIs

### 4.1 `POST /pos/ingest` (`app/pos_ingestion.py`)

**Compatible.** Batch payloads can be built with:

```python
from pipeline.pos_loader import load_aggregated_transactions, aggregated_records_to_purpple_dicts

records = load_aggregated_transactions()
payload = {"transactions": aggregated_records_to_purpple_dicts(records)}
# POST /pos/ingest with payload (batches of ≤500)
```

Idempotency by `transaction_id` — re-ingesting Brigade invoices skips duplicates.

### 4.2 `scripts/seed_from_sample.py`

**Compatible.** Generated file:

```
data/generated/pos/purpple_pos_transactions.csv
```

```bash
python scripts/seed_from_sample.py --pos data/generated/pos/purpple_pos_transactions.csv
```

### 4.3 `app/pos_correlation.py`

**Compatible.** After ingest/seed, conversion metrics use:

- `billing_activity_at` from CCTV sessions (CAM5 pipeline events)
- POS `timestamp` from Brigade-mapped rows
- 5-minute window: `txn.timestamp − 5min ≤ billing_activity_at ≤ txn.timestamp`

Brigade sale date **2026-04-10** aligns with `CAMERA_CLIP_START` anchors in `pipeline/config.py`.

### 4.4 Not yet wired

| Integration | Status |
|-------------|--------|
| `scripts/run_pipeline_demo.py` auto-POS step | Not added (manual run of `python -m pipeline.pos_loader`) |
| Copy Brigade CSV into repo `data/pos/` | Optional — use `BRIGADE_POS_CSV_PATH` env |
| Product/brand metadata in DB | Not in current `pos_transactions` schema |

---

## 5. How to run

```powershell
# Place CSV at data/pos/Brigade_Bangalore_10_April_26.csv, or set env:
$env:BRIGADE_POS_CSV_PATH = "E:\NOTEBK\project\data\Brigade_Bangalore_10_April_26.csv"

cd E:\Purpple_Vision
python -m pipeline.pos_loader

# Seed database
python scripts/seed_from_sample.py --pos data/generated/pos/purpple_pos_transactions.csv
```

---

## 6. Next steps (Phase 5B — not in this PR)

1. Port event timestamp normalizer for pipeline demo JSONL → wall-clock.
2. Wire POS aggregation into `run_pipeline_demo.py` post-step.
3. Implement `purchase_matching.py` validation script (optional).
4. Extend DB schema if product/brand attribution is required on POS rows.

---

## 7. Files changed

| File | Change |
|------|--------|
| `pipeline/pos_loader.py` | Full implementation (load, aggregate, export, Purpple map) |
| `pipeline/config.py` | Brigade POS paths and store code constants |
| `data/generated/pos/aggregated_transactions.json` | Generated output |
| `data/generated/pos/aggregated_transactions.csv` | Generated output |
| `data/generated/pos/purpple_pos_transactions.csv` | Generated output |
| `brigade_pos_schema_mapping.md` | Schema mapping reference |
| `phase5_pos_migration_report.md` | This report |
