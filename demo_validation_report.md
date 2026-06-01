# Demo Validation Report

**Purpose:** Synthetic ENTRY-based dataset to verify sessions, funnel, metrics, and analytics.

**Store:** `STORE_BLR_002`  
**Metric date (UTC):** `2026-06-01`  

**Clean run:**
YES

**Database actually used:**
`E:\Purpple_Vision\data\databases\demo_validation.db`

**Events file:** `data\synthetic\demo_events.jsonl`  
**POS file:** `data\synthetic\demo_pos.csv`  

> Production database (`data/databases/store_intelligence.db`) is **not modified**.

## 1. Ingestion

| Metric | Value |
|--------|-------|
| Events loaded | 14 |
| Events ingested | 14 |
| Event duplicates skipped | 0 |
| Events rejected | 0 |
| POS rows loaded | 2 |
| POS ingested | 2 |
| POS duplicates skipped | 0 |
| POS rejected | 0 |

## 2. Sessions

- Sessions created: **3** (customer sessions)
- Total sessions (incl. logic): **3**
- Unique visitors: **3**

### Visitor journeys

| Visitor | Journey | Converted |
|---------|---------|-----------|
| VIS_101 | ENTRY → LAKME → dwell → billing queue → EXIT | Yes (TXN_DEMO_101) |
| VIS_102 | ENTRY → PILGRIM → dwell → EXIT | No |
| VIS_103 | ENTRY → GOODVIBES → dwell → billing queue → EXIT | Yes (TXN_DEMO_103) |

## 3. Metrics

| Metric | Value |
|--------|-------|
| unique_visitors | 3 |
| total_sessions | 3 |
| conversion_rate | 0.6667 |
| billing_reach_rate | 0.6667 |
| queue_abandonment_rate | 0.0000 |
| current_queue_depth | 1 |

## 4. Funnel

| Stage | Count | Drop-off % |
|-------|-------|------------|
| unique_visitors | 3 | — |
| reached_any_zone | 3 | 0.0 |
| billing_queue | 2 | 33.3 |
| converted_visitors | 2 | 0.0 |

- Converted visitors: **2**

## 5. Conversions & revenue

| Metric | Value |
|--------|-------|
| Converted visitors (POS correlation) | 2 |
| Total POS revenue (INR) | 2,148.50 |

POS transactions:

| transaction_id | visitor | amount (INR) |
|----------------|---------|--------------|
| TXN_DEMO_101 | VIS_101 | 849.50 |
| TXN_DEMO_103 | VIS_103 | 1,299.00 |

## 6. Heatmap & anomalies

- Heatmap zones reported: **4**
- Anomalies detected: **1**

## 7. Dashboard verification

To view non-zero analytics in Streamlit against the validation DB:

```powershell
$env:DATABASE_URL = "sqlite:///E:/Purpple_Vision/data/databases/demo_validation.db"
uvicorn app.main:app --host 0.0.0.0 --port 8000
# second terminal:
$env:API_BASE_URL = "http://localhost:8000"
$env:DEFAULT_METRIC_DATE = "2026-06-01"
streamlit run dashboard/streamlit_app.py --server.port 8501
```

## Verdict

**PASS** — Sessions and funnel populated from synthetic ENTRY events.
