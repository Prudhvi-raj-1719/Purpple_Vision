# Brigade POS Schema Mapping

**Source file:** `Brigade_Bangalore_10_April_26.csv` (Brigade Bangalore, 10-Apr-2026)  
**Aggregation module:** `pipeline/pos_loader.py`  
**Purpple store mapping:** `ST1008` (Brigade CSV) → `STORE_BLR_002` (Purpple API/DB)

---

## 1. Raw Brigade CSV columns (line-item level)

Each row is one product line on an invoice. Key columns used by the loader:

| Brigade CSV column | Type / example | Used in aggregation |
|--------------------|----------------|---------------------|
| `order_id` | int — `104363838` | First value per invoice → `order_id` |
| `invoice_number` | str — `ML0426KAP0001358` | Group key → `invoice_number` |
| `order_date` | str — `10-04-2026` | Combined with `order_time` |
| `order_time` | str — `16:55:36` | Combined with `order_date` |
| `store_id` | str — `ST1008` | Store code (mapped at Purpple layer) |
| `store_name` | str — `Brigade_Bangalore` | Not stored in aggregated output |
| `customer_number` | int — `9346413680` | First value per invoice |
| `salesperson_name` | str — `kasthuri v` | First value per invoice |
| `product_name` | str | Collected → `product_names[]` |
| `brand_name` | str — `DERMDOC` | Collected → `brand_names[]` |
| `dep_name` | str — `bath-and-body` | Collected → `categories[]` |
| `qty` | int | Summed → `total_quantity` |
| `total_amount` | float | Summed → `total_amount` |

Other CSV columns (`sku`, `GMV`, `NMV`, `coupon_code`, tax fields, etc.) are **not** carried into aggregated output (same as NOTEBK `pos_aggregation.py`).

---

## 2. Derived datetime

| Source | Transformation | Aggregated field |
|--------|----------------|------------------|
| `order_date` + `order_time` | `"%d-%m-%Y %H:%M:%S"` parse → format `"%Y-%m-%d %H:%M:%S"` | `transaction_datetime` |

Example: `10-04-2026` + `16:55:36` → `2026-04-10 16:55:36`

---

## 3. Aggregated JSON fields (`aggregated_transactions.json`)

NOTEBK-compatible structure written to `data/generated/pos/aggregated_transactions.json`:

| Aggregated field | Derivation | Example |
|------------------|------------|---------|
| `invoice_number` | `groupby(invoice_number)` key | `ML0426KAP0001358` |
| `order_id` | `first(order_id)` in group | `104363838` |
| `transaction_datetime` | `first(parsed datetime)` in group | `2026-04-10 16:55:36` |
| `customer_number` | `first(customer_number)` | `9346413680` |
| `salesperson_name` | `first(salesperson_name).strip()` | `kasthuri v` |
| `product_names` | unique sorted `product_name` | `["Alps Goodness …", "DERMDOC …"]` |
| `brand_names` | unique sorted `brand_name` | `["Alps Goodness", "DERMDOC"]` |
| `categories` | unique sorted `dep_name` | `["bath-and-body", "hair"]` |
| `total_quantity` | `sum(qty)` | `4` |
| `total_amount` | `round(sum(total_amount), 2)` | `729.79` |

---

## 4. Purpple DB / API fields (`pos_transactions` table)

Mapped via `aggregated_record_to_purpple_dict()` → `PosTransaction` → `PosTransactionRecord`:

| Aggregated field | Purpple field | Transformation |
|------------------|---------------|----------------|
| *(constant)* | `store_id` | `ST1008` → `STORE_BLR_002` (`DEFAULT_STORE_ID`) |
| `invoice_number` | `transaction_id` | `TXN_{sanitized_invoice}` e.g. `TXN_ML0426KAP0001358` |
| `transaction_datetime` | `timestamp` | Parse as naive local → UTC (`…Z` ISO) |
| `total_amount` | `basket_value_inr` | Direct float copy |

**Not persisted in Purpple DB today:** `product_names`, `brand_names`, `categories`, `customer_number`, `salesperson_name`, `order_id` — available in aggregated JSON for future analytics / purchase matching.

---

## 5. Purpple seed CSV (`purpple_pos_transactions.csv`)

Written to `data/generated/pos/purpple_pos_transactions.csv` for `scripts/seed_from_sample.py`:

```csv
store_id,transaction_id,timestamp,basket_value_inr
STORE_BLR_002,TXN_ML0426KAP0001321,2026-04-10T12:15:05Z,1247.98
```

Load into SQLite:

```bash
python scripts/seed_from_sample.py --pos data/generated/pos/purpple_pos_transactions.csv
```

Or ingest via API:

```bash
POST /pos/ingest
{ "transactions": [ { "store_id": "STORE_BLR_002", "transaction_id": "TXN_…", … } ] }
```

---

## 6. End-to-end flow

```
Brigade_Bangalore_10_April_26.csv
        │
        ▼  pipeline/pos_loader.py
        │  • load_brigade_pos_lines()
        │  • aggregate_invoices()
        │
        ├── aggregated_transactions.json   (NOTEBK schema)
        ├── aggregated_transactions.csv    (list cols JSON-encoded)
        └── purpple_pos_transactions.csv   (API/seed schema)
                │
                ├── scripts/seed_from_sample.py  → SQLite pos_transactions
                └── POST /pos/ingest             → SQLite pos_transactions
                        │
                        ▼
                app/pos_correlation.py (5-min billing window)
                app/metrics.py / funnel.py / anomalies.py
```

---

## 7. Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `BRIGADE_POS_CSV_PATH` | `data/pos/Brigade_Bangalore_10_April_26.csv` | Raw Brigade export |
| `STORE_ID` | `STORE_BLR_002` | Purpple store_id on mapped rows |
| `PIPELINE_OUTPUT_DIR` | `data/generated` | Parent of `pos/` outputs |

Run aggregation:

```bash
python -m pipeline.pos_loader
# or with explicit CSV:
set BRIGADE_POS_CSV_PATH=E:\NOTEBK\project\data\Brigade_Bangalore_10_April_26.csv
python -m pipeline.pos_loader
```
