# Phase 03 — Session Builder

**Status:** Complete  
**Implementation:** `app/sessions.py`

---

## What we built

A **session engine** that turns a stream of behavioural events into customer visits. Sessions are built in memory when analytics run — they are not stored as a separate database table.

---

## How a session works

| Step | Event | Result |
|------|-------|--------|
| Customer enters | ENTRY or REENTRY | Session **opens** |
| Browsing | ZONE_ENTER, ZONE_DWELL, ZONE_EXIT | Zones and dwell time recorded |
| Checkout | BILLING_QUEUE_JOIN (and optional ABANDON) | Billing activity timestamp set |
| Purchase | POS row correlated in time window | Visitor marked **converted** |
| Customer leaves | EXIT | Session **closes** |

**Rules in plain language:**

- Without an **ENTRY** (or REENTRY) first, zone and queue events are **ignored**.
- **REENTRY** starts a new session but does not double-count the visitor in funnel metrics.
- **Staff** events can be flagged with `is_staff` and are excluded from customer KPIs.

---

## Session data used by analytics

Each session tracks:

- `zones_visited` — product areas entered  
- `joined_queue` / `abandoned_queue` — billing behaviour  
- `total_dwell_ms_by_zone` — time per zone  
- `reached_billing` / `billing_activity_at` — used for POS correlation (5-minute window before transaction)

---

## POS correlation

A visitor counts as **converted** when billing activity happened within **5 minutes before** a POS transaction time (`app/pos_correlation.py`). This drives conversion rate, funnel “Purchased”, and revenue KPIs.

---

## How to verify

```powershell
python scripts/demo_validation_run.py
```

Expected: **3 sessions**, **3 visitors**, **66.7% conversion** (synthetic dataset with ENTRY events).

---

## Related

- [Phase 02 — Detection pipeline](phase_02_detection_pipeline.md) — must emit ENTRY for real footage  
- [Phase 04 — POS integration](phase_04_pos_integration.md)  
- Diagram: [session_lifecycle.md](../../architecture/session_lifecycle.md)  
- Deep dive: zone-only Brigade CCTV data produces no ENTRY events, so `build_sessions()` returns zero sessions until CAM3 runs.
