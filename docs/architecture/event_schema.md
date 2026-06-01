# Event Schema Reference

Behavioural events emitted by the detection pipeline and accepted by `POST /events/ingest`.

**Source of truth:** `app/models.py` (`Event`, `EventType`)

---

## Core fields

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | UUID v4 | Globally unique; idempotency key |
| `store_id` | string | e.g. `STORE_BLR_002` |
| `camera_id` | string | e.g. `CAM_ENTRY_01`, `CAM_SHELF_01` |
| `visitor_id` | string | Per-session token e.g. `VIS_a1b2c3` |
| `event_type` | enum | See below |
| `timestamp` | ISO-8601 UTC | Business time of event |
| `zone_id` | string \| null | Product zone or BILLING |
| `dwell_ms` | int | Zone dwell milliseconds (0 for instant events) |
| `is_staff` | bool | Exclude from customer metrics when true |
| `confidence` | float | Detection confidence (retained, not dropped) |
| `metadata` | object | Optional queue_depth, sku_zone, session_seq |

---

## Event types

### Threshold events (zone_id must be null)

| Type | When | Session impact |
|------|------|----------------|
| **ENTRY** | Cross entry line inbound | **Opens session** |
| **EXIT** | Cross entry line outbound | **Closes session** |
| **REENTRY** | Visitor returns after EXIT | **Opens new session** |

### Zone events (zone_id required)

| Type | When |
|------|------|
| **ZONE_ENTER** | Enter product zone polygon |
| **ZONE_EXIT** | Leave product zone |
| **ZONE_DWELL** | Continued presence (pipeline emits on dwell completion) |

### Billing events

| Type | When | Notes |
|------|------|-------|
| **BILLING_QUEUE_JOIN** | Enter billing queue | `metadata.queue_depth` > 0 |
| **BILLING_QUEUE_ABANDON** | Leave queue without POS match | Sets abandonment flags |

---

## Zone rules

- ENTRY, EXIT, REENTRY → `zone_id` must be **null**
- ZONE_*, BILLING_* → `zone_id` must be **present**
- Low-confidence events are **stored**, not filtered

---

## NOTEBK → Purpple mapping

Handled by `pipeline/event_adapter.py`:

| NOTEBK | Purpple |
|--------|---------|
| QUEUE_ENTER | BILLING_QUEUE_JOIN |
| DWELL_COMPLETED | ZONE_DWELL |
| PAYMENT_ENTER | (zone billing activity) |

Clip timestamps anchored via `pipeline/config.py` `CAMERA_CLIP_START`.

---

## Example event (ENTRY)

```json
{
  "event_id": "a1000001-0001-4001-8001-000000000101",
  "store_id": "STORE_BLR_002",
  "camera_id": "CAM_ENTRY_01",
  "visitor_id": "VIS_101",
  "event_type": "ENTRY",
  "timestamp": "2026-06-01T10:00:00Z",
  "zone_id": null,
  "dwell_ms": 0,
  "is_staff": false,
  "confidence": 0.92,
  "metadata": {}
}
```

---

## Ingest contract

- **Endpoint:** `POST /events/ingest`
- **Batch size:** 1–500 events
- **Idempotency:** duplicate `event_id` skipped
- **Response:** counts for ingested, duplicates, rejected

See [api_reference.md](api_reference.md) for HTTP details.

---

## Related

- [pipeline_flow.md](pipeline_flow.md)
- [../DESIGN.md](../DESIGN.md) — session construction
