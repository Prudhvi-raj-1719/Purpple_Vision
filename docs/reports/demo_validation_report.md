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
| Events loaded | 843 |
| Events ingested | 843 |
| Event duplicates skipped | 0 |
| Events rejected | 0 |
| POS rows loaded | 68 |
| POS ingested | 68 |
| POS duplicates skipped | 0 |
| POS rejected | 0 |

## 2. Sessions

- Sessions created: **161** (customer sessions)
- Total sessions (incl. logic): **161**
- Unique visitors: **130**

### Visitor journeys

| Visitor | Journey | Converted |
|---------|---------|-----------|
| VIS_101 | ENTRY → LAKME → dwell → billing queue → EXIT | Yes (TXN_DEMO_101) |
| VIS_102 | ENTRY → PILGRIM → dwell → EXIT | No |
| VIS_103 | ENTRY → GOODVIBES → dwell → billing queue → EXIT | Yes (TXN_DEMO_103) |

## 3. Metrics

| Metric | Value |
|--------|-------|
| unique_visitors | 128 |
| total_sessions | 153 |
| conversion_rate | 0.6719 |
| billing_reach_rate | 0.6797 |
| queue_abandonment_rate | 0.1442 |
| current_queue_depth | 1 |

## 4. Funnel

| Stage | Count | Drop-off % |
|-------|-------|------------|
| unique_visitors | 128 | — |
| reached_any_zone | 128 | 0.0 |
| billing_queue | 96 | 25.0 |
| converted_visitors | 86 | 10.4 |

- Converted visitors: **86**

## 5. Conversions & revenue

| Metric | Value |
|--------|-------|
| Converted visitors (POS correlation) | 86 |
| Total POS revenue (INR) | 78,272.99 |

POS transactions:

| transaction_id | visitor | amount (INR) |
|----------------|---------|--------------|
| TXN_DEMO_101 | VIS_101 | 849.50 |
| TXN_DEMO_103 | VIS_103 | 1,299.00 |

## 6. Heatmap & anomalies

- Heatmap zones reported: **17**
- Anomalies detected: **9**

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
