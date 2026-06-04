# Demo Validation Report — store_2

**Purpose:** Synthetic ENTRY-based dataset to verify sessions, funnel, metrics, and analytics.

**Store key:** `store_2`  
**Store ID:** `STORE_BLR_003`  
**Metric date (UTC):** `2026-04-10`  

**Clean run:** YES

**Database actually used:**
`E:\Purpple_Vision\data\databases\store_2_validation.db`

**Events file:** `data\synthetic\store_2\synthetic_events_store_2.jsonl`  
**POS file:** `data\synthetic\store_2\synthetic_pos_store_2.csv`  

> Other store validation DBs are **not modified** by this run.

## 1. Ingestion

| Metric | Value |
|--------|-------|
| Events loaded | 1877 |
| Events ingested | 1877 |
| Event duplicates skipped | 0 |
| Events rejected | 0 |
| POS rows loaded | 100 |
| POS ingested | 100 |
| POS duplicates skipped | 0 |
| POS rejected | 0 |

## 2. Sessions

- Customer sessions: **194**
- Total sessions: **194**
- Unique visitors: **161**
- REENTRY events in fixture: **33**

## 3. Metrics

| Metric | Value |
|--------|-------|
| unique_visitors | 158 |
| total_sessions | 182 |
| conversion_rate | 0.6392 |
| billing_reach_rate | 0.6923 |
| queue_abandonment_rate | 0.2222 |

## 4. Funnel

| Stage | Count | Drop-off % |
|-------|-------|------------|
| unique_visitors | 158 | — |
| reached_any_zone | 158 | 0.0 |
| billing_queue | 118 | 25.3 |
| converted_visitors | 101 | 14.4 |

- Converted visitors: **101**
- Revenue (INR): **88,496.83**
- Anomalies: **3**

## 5. Dashboard verification

```powershell
$env:DATABASE_URL = "sqlite:///E:/Purpple_Vision/data/databases/store_2_validation.db"
$env:DEFAULT_METRIC_DATE = "2026-04-10"
uvicorn app.main:app --host 0.0.0.0 --port 8000
streamlit run dashboard/streamlit_app.py --server.port 8501
```

## Verdict

**PASS** — Per-store synthetic validation succeeded.
