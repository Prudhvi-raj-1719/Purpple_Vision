# Demo Validation Report — store_1

**Purpose:** Synthetic ENTRY-based dataset to verify sessions, funnel, metrics, and analytics.

**Store key:** `store_1`  
**Store ID:** `STORE_BLR_002`  
**Metric date (UTC):** `2026-06-01`  

**Clean run:** YES

**Database actually used:**
`E:\Purpple_Vision\data\databases\store_1_validation.db`

**Events file:** `data\synthetic\store_1\synthetic_events_store_1.jsonl`  
**POS file:** `data\synthetic\store_1\synthetic_pos_store_1.csv`  

> Other store validation DBs are **not modified** by this run.

## 1. Ingestion

| Metric | Value |
|--------|-------|
| Events loaded | 1210 |
| Events ingested | 1210 |
| Event duplicates skipped | 0 |
| Events rejected | 0 |
| POS rows loaded | 71 |
| POS ingested | 71 |
| POS duplicates skipped | 0 |
| POS rejected | 0 |

## 2. Sessions

- Customer sessions: **122**
- Total sessions: **122**
- Unique visitors: **95**
- REENTRY events in fixture: **27**

## 3. Metrics

| Metric | Value |
|--------|-------|
| unique_visitors | 92 |
| total_sessions | 110 |
| conversion_rate | 0.7174 |
| billing_reach_rate | 0.7091 |
| queue_abandonment_rate | 0.1154 |

## 4. Funnel

| Stage | Count | Drop-off % |
|-------|-------|------------|
| unique_visitors | 92 | — |
| reached_any_zone | 92 | 0.0 |
| billing_queue | 72 | 21.7 |
| converted_visitors | 66 | 8.3 |

- Converted visitors: **66**
- Revenue (INR): **92,800.68**
- Anomalies: **10**

## 5. Dashboard verification

```powershell
$env:DATABASE_URL = "sqlite:///E:/Purpple_Vision/data/databases/store_1_validation.db"
$env:DEFAULT_METRIC_DATE = "2026-06-01"
uvicorn app.main:app --host 0.0.0.0 --port 8000
streamlit run dashboard/streamlit_app.py --server.port 8501
```

## Verdict

**FAIL** — See counts/errors above.
