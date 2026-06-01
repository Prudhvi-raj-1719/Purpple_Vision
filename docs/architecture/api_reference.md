# API Reference

Store Intelligence FastAPI endpoints. All store analytics accept optional `?date=YYYY-MM-DD` (UTC day; defaults to today UTC).

**Interactive docs:** http://localhost:8000/docs

**Example payloads:** `examples/*.json` in repository root.

---

## POST /events/ingest

Ingest behavioural events from the detection pipeline.

### Request

```json
{
  "events": [
    {
      "event_id": "550e8400-e29b-41d4-a716-446655440000",
      "store_id": "STORE_BLR_002",
      "camera_id": "CAM_ENTRY_01",
      "visitor_id": "VIS_a1b2c3",
      "event_type": "ENTRY",
      "timestamp": "2026-03-03T10:00:00Z",
      "zone_id": null,
      "dwell_ms": 0,
      "is_staff": false,
      "confidence": 0.9,
      "metadata": {}
    }
  ]
}
```

### Response

```json
{
  "status": "success",
  "total_received": 1,
  "events_ingested": 1,
  "duplicates_skipped": 0,
  "rejected": 0,
  "errors": []
}
```

### Business meaning

Persists immutable events. Duplicate `event_id` values are skipped (safe to retry). Events feed session builder and all analytics.

---

## POST /pos/ingest

Ingest POS transactions for conversion correlation.

### Request

See `examples/pos_ingest_endpoint.json`:

```json
{
  "transactions": [
    {
      "store_id": "STORE_BLR_002",
      "transaction_id": "TXN_00441",
      "timestamp": "2026-03-03T14:12:00Z",
      "basket_value_inr": 1240.0
    }
  ]
}
```

### Response

```json
{
  "status": "success",
  "total_received": 1,
  "transactions_ingested": 1,
  "duplicates_skipped": 0,
  "rejected": 0,
  "errors": []
}
```

### Business meaning

Links sales to visitor sessions when billing activity occurred within 5 minutes before transaction time.

---

## GET /stores/{store_id}/metrics

North Star KPIs and operational metrics.

### Request

```
GET /stores/STORE_BLR_002/metrics?date=2026-03-03
```

### Response

See `examples/metrics_endpoint.json`:

```json
{
  "store_id": "STORE_BLR_002",
  "date": "2026-03-03",
  "unique_visitors": 2,
  "conversion_rate": 0.5,
  "total_sessions": 2,
  "total_revenue_inr": 1240.0,
  "average_dwell_time_ms": 15000.0,
  "average_dwell_by_zone": [
    { "zone_id": "SKINCARE", "average_dwell_ms": 15000.0 }
  ],
  "current_queue_depth": 2,
  "queue_abandonment_rate": 0.0,
  "billing_reach_rate": 0.5
}
```

### Business meaning

| Field | Meaning |
|-------|---------|
| `unique_visitors` | Distinct non-staff visitors (ENTRY/REENTRY) |
| `conversion_rate` | **North Star** — converted visitors ÷ unique visitors |
| `total_revenue_inr` | Sum of POS `basket_value_inr` for the day |
| `current_queue_depth` | Latest queue depth from BILLING_QUEUE_JOIN |
| `queue_abandonment_rate` | Queue joins that left without purchase |

---

## GET /stores/{store_id}/funnel

Session funnel with drop-off percentages.

### Request

```
GET /stores/STORE_BLR_002/funnel?date=2026-03-03
```

### Response

See `examples/funnel_endpoint.json`:

```json
{
  "store_id": "STORE_BLR_002",
  "date": "2026-03-03",
  "stages": [
    { "stage": "unique_visitors", "count": 3, "drop_off_pct": null },
    { "stage": "reached_any_zone", "count": 2, "drop_off_pct": 33.3 },
    { "stage": "billing_queue", "count": 1, "drop_off_pct": 50.0 },
    { "stage": "converted_visitors", "count": 1, "drop_off_pct": 0.0 }
  ],
  "overall_conversion_rate": 0.333
}
```

### Business meaning

Shows where customers leave the journey: entry → zone engagement → billing → purchase. Visitor-level counts prevent REENTRY double-counting.

---

## GET /stores/{store_id}/heatmap

Zone engagement heatmap.

### Request

```
GET /stores/STORE_BLR_002/heatmap?date=2026-03-03
```

### Response

See `examples/heatmap_endpoint.json`:

```json
{
  "store_id": "STORE_BLR_002",
  "date": "2026-03-03",
  "data_confidence": false,
  "zones": [
    {
      "zone_id": "SKINCARE",
      "visit_count": 2,
      "unique_visitors": 2,
      "total_dwell_time_ms": 45000,
      "average_dwell_time_ms": 22500.0,
      "normalized_score": 72.5
    }
  ]
}
```

### Business meaning

Identifies high-traffic zones vs underperforming areas. `data_confidence: false` when fewer than 20 customer sessions (scores may be unreliable).

---

## GET /stores/{store_id}/anomalies

Active store alerts.

### Request

```
GET /stores/STORE_BLR_002/anomalies?date=2026-03-03
```

### Response

See `examples/anomalies_endpoint.json` — includes `QUEUE_SPIKE`, `CONVERSION_DROP`, `DEAD_ZONE` with severity and `suggested_action`.

### Business meaning

Operational alerts for store managers: staffing queues, investigating checkout friction, fixing dead zones.

---

## GET /health

Service and feed health.

### Request

```
GET /health
```

### Response (illustrative)

```json
{
  "status": "ok",
  "database_available": true,
  "timestamp": "2026-06-01T10:00:00Z",
  "stores": [
    {
      "store_id": "STORE_BLR_002",
      "last_event_at": "2026-04-10T20:15:00Z",
      "stale": false
    }
  ],
  "warnings": []
}
```

### Business meaning

| Field | Meaning |
|-------|---------|
| `status` | `ok` or `degraded` |
| `database_available` | SQLite reachable |
| `stores[].stale` | No ingest within threshold (default 10 min) |
| `warnings` | Includes `STALE_FEED: {store_id}` when stale |

---

## Error responses

Structured `ErrorResponse` with HTTP 503 on database failures:

```json
{
  "error": "database_unavailable",
  "detail": "A database error occurred",
  "trace_id": "uuid"
}
```

---

## Related

- [event_schema.md](event_schema.md)
- [pipeline_flow.md](pipeline_flow.md)
- [../../examples/](../../examples/) — committed sample payloads
