# Phase 04 — POS Integration

**Status:** Complete  
**Implementation:** `pipeline/pos_loader.py`

---

## What we built

A **POS loader** that reads Brigade Bangalore line-item CSV exports and produces invoice-level data the Intelligence API can ingest.

| Output | Location | Use |
|--------|----------|-----|
| Aggregated invoices (JSON) | `data/outputs/pos/aggregated_transactions.json` | Offline purchase matching |
| Purpple POS CSV | `data/outputs/pos/purpple_pos_transactions.csv` | Bridge script or `POST /pos/ingest` |

**Store mapping:** Brigade store code `ST1008` → Purpple `STORE_BLR_002`.

Each row includes `transaction_id`, UTC `timestamp`, and `basket_value_inr` for the day’s sales.

---

## How it connects to KPIs

| Metric | POS role |
|--------|----------|
| **Conversion rate** | Match transactions to visitors who had billing activity in session |
| **Revenue (INR)** | Sum of `basket_value_inr` for the UTC day (`total_revenue_inr` on `/metrics`) |
| **Funnel “Purchased”** | Visitors with a correlated POS transaction |

---

## How to run

```powershell
python -m pipeline.pos_loader
```

Included automatically in `python scripts/demo_runner.py` and `python scripts/run_pipeline_demo.py`.

---

## Brigade demo data

The bundled Brigade CSV (`data/pos/`) aggregates to **24 invoices** for the demo store date. Timestamps must align with billing events in sessions for non-zero conversion on bridged CCTV data.

---

## Related

- [Phase 03 — Session builder](phase_03_session_builder.md)  
- [Phase 06 — Product integration](phase_06_product_integration.md)
