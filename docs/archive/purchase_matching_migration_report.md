# Purchase Matching Migration Report — Phase 5D

**Date:** 2026-05-30  
**Module:** `pipeline/purchase_matching.py` (offline analytics)  
**Output:** `data/generated/purchase_matches.json`

---

## 1. Migration summary

NOTEBK `matching/purchase_matching.py` has been ported to Purpple_Vision as an **offline** module. No API routes were modified.

| Item | NOTEBK | Purpple_Vision |
|------|--------|----------------|
| Engine | `project/matching/purchase_matching.py` | `pipeline/purchase_matching.py` |
| POS input | `outputs/aggregated_transactions.json` | `data/generated/pos/aggregated_transactions.json` |
| Event input | `cam{1,2,5}_events_normalized.jsonl` | `data/generated/pipeline_demo/cam*_events.notbk.jsonl` |
| Timestamp handling | Pre-normalized `event_datetime` | Normalized at load via `resolve_utc_timestamp()` + clip anchors |
| Output | `outputs/purchase_matches.json` | `data/generated/purchase_matches.json` |
| API impact | N/A | **None** — offline only |

**Run:**
```bash
python -m pipeline.purchase_matching
```

---

## 2. Approach comparison

### NOTEBK / `pipeline/purchase_matching.py` (invoice-centric)

| Aspect | Behaviour |
|--------|-----------|
| Unit of analysis | **POS invoice** |
| Window | `transaction_datetime ± 5 minutes` |
| Event sources | CAM1, CAM2, CAM5 normalized JSONL |
| Output | Per-invoice match record with full event journey |
| Scoring | **Confidence score** 0.0–1.0 (payment + queue + zone interactions + temporal proximity) |
| Journey | `candidate_customer_journey`, `journey_summary` (zones, queue, payment flags) |
| Visitor identity | Not required — spatial/temporal evidence only |

### Purpple API / `app/pos_correlation.py` (session-centric)

| Aspect | Behaviour |
|--------|-----------|
| Unit of analysis | **Visitor session** |
| Window | `billing_activity_at` within **5 minutes before** POS `timestamp` (one-sided) |
| Event sources | Ingested Purpple events → `VisitorSession` |
| Output | Boolean conversion per session; funnel `converted_visitors` count |
| Scoring | None — binary converted / not converted |
| Journey | Not reconstructed |
| Visitor identity | **Required** — track must reach billing with known `visitor_id` |
| Staff | Staff sessions excluded |

### Key differences

1. **Granularity:** Invoice match vs session conversion flag.
2. **Window shape:** Symmetric ±5 min around txn vs asymmetric 5 min before txn only.
3. **CAM5 dependency:** Purchase matching weights queue/payment events heavily; API correlation only needs `billing_activity_at` on session.
4. **Confidence:** Offline module scores match quality; API has no confidence metric.
5. **Deployment:** Offline JSON report vs runtime SQLite + REST metrics.

Both can coexist: purchase matching validates CCTV↔POS alignment; `pos_correlation` drives production funnel metrics.

---

## 3. Run results (current pipeline demo data)

| Metric | Value |
|--------|-------|
| **Invoices processed** | **24** |
| **Matched invoices** | **0** |
| **Unmatched invoices** | **24** |
| Match rate | 0% |
| Average confidence (matched) | N/A |
| Min / max confidence | N/A |

### Event files loaded

| File | Events | Normalized time range |
|------|--------|------------------------|
| `cam1_events.notbk.jsonl` | 24 | 2026-04-10 20:10:36 → 20:12:46 |
| `cam2_events.notbk.jsonl` | 42 | 2026-04-10 20:10:09 → 20:12:07 |
| `cam5_events.notbk.jsonl` | *(missing)* | — |

### POS time range

| Metric | Value |
|--------|-------|
| First transaction | 2026-04-10 12:15:05 |
| Last transaction | 2026-04-10 21:39:55 |
| Total revenue | INR 34,331.71 |

### Why zero matches (expected with partial demo)

1. **Short CCTV clips:** Demo pipeline processed ~2–3 minutes per camera; normalized events span only ~20:10–20:13.
2. **Daytime POS:** 21 of 24 invoices occur before 20:10 (outside clip window entirely).
3. **Evening POS gap:** Three invoices at 20:25, 21:16, 21:39 fall after the available event span; ±5 min windows around them contain no events.
4. **Missing CAM5:** No billing queue/payment events loaded — confidence scoring cannot use queue/payment signals even when times overlap.

This matches NOTEBK `video_pos_overlap_report.txt` findings before full clip processing.

---

## 4. Confidence score model (unchanged from NOTEBK)

Base score **0.15**, capped at **1.0**:

| Signal | Weight |
|--------|--------|
| Payment activity (CAM5 `PAYMENT_*` or `PaymentArea`) | +0.25 |
| Queue activity (`QUEUE_*` or `BillingQueue`) | +0.20 |
| Zone interactions ≥ 3 | +0.20 |
| Zone interactions ≥ 1 | +0.10 |
| Temporal proximity to txn | up to +0.35 |

---

## 5. Output schema (`purchase_matches.json`)

Each invoice produces one object:

```json
{
  "invoice_number": "ML0426KAP0001321",
  "transaction_datetime": "2026-04-10 12:15:05",
  "brands_purchased": ["Faces Canada"],
  "total_amount": 1247.98,
  "match_window_minutes": 5,
  "search_window": { "from": "...", "to": "..." },
  "candidate_customer_journey": {
    "cam1_events": [],
    "cam2_events": [],
    "cam5_events": []
  },
  "match_found": false,
  "reason": "No CCTV events in time window",
  "matching_events": [],
  "confidence_score": 0.0,
  "journey_summary": {
    "zones_visited": [],
    "queue_activity": false,
    "payment_activity": false
  }
}
```

---

## 6. Compatibility checklist

- [x] Loads `aggregated_transactions.json` from Phase 5A
- [x] Loads pipeline demo NOTEBK JSONL events
- [x] Normalizes video-offset timestamps via `CAMERA_CLIP_START`
- [x] NOTEBK-equivalent confidence + journey summary
- [x] Writes `data/generated/purchase_matches.json`
- [x] No changes to `app/pos_correlation.py` or API routes
- [ ] Full match rate validation — requires complete CAM1/CAM2/CAM5 demo runs + verified clip anchors

---

## 7. Recommended next steps

1. Run full pipeline demo including **CAM5** (`scripts/run_pipeline_demo.py`).
2. Re-run `python -m pipeline.purchase_matching` after complete event JSONL exists.
3. Verify `CAMERA_CLIP_START` anchors against overlay timestamps if match rate stays low.
4. Optionally add `scripts/run_purchase_matching.py` wrapper and hook into demo orchestrator (still offline).
5. Keep `app/pos_correlation.py` as the authoritative conversion rule for API metrics unless product explicitly aligns window semantics.

---

## 8. Files added / updated

| File | Change |
|------|--------|
| `pipeline/purchase_matching.py` | **New** — offline invoice matching engine |
| `pipeline/config.py` | Added `PIPELINE_DEMO_DIR`, `PURCHASE_MATCHES_JSON` |
| `data/generated/purchase_matches.json` | **Generated** — 24 invoice records |
| `purchase_matching_migration_report.md` | This report |
