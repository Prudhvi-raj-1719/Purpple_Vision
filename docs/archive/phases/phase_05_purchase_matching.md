# Phase 05 — Purchase Matching (Offline Validation)

**Status:** Complete (offline tool)  
**Implementation:** `pipeline/purchase_matching.py`

---

## What we built

An **offline validator** that checks whether POS invoice times align with CCTV-derived activity in a time window. It helps answer: “Did this sale show up on camera near billing?”

| Input | Source |
|-------|--------|
| POS invoices | `data/outputs/pos/aggregated_transactions.json` |
| CCTV events | `data/outputs/pipeline/pipeline_demo/cam*_events.notbk.jsonl` |

| Output | Location |
|--------|----------|
| Match results | `data/outputs/purchase_matching/purchase_matches.json` |

---

## Role in the product

Purchase matching is **not** part of the live API or dashboard. It does not write to SQLite. Results are for engineering validation and demo reports only.

The **official conversion KPI** comes from session + POS correlation inside the API (`app/pos_correlation.py`), not from this JSON file.

---

## How to run

```powershell
python -m pipeline.purchase_matching
```

Runs as step 6 in `python scripts/demo_runner.py` (after cameras and POS loader).

---

## What reviewers should know

- On Brigade demo footage, match counts may be **low or zero** when CAM5 queue events and POS times do not overlap (evening CCTV vs daytime sales).
- Use **demo_validation** ([demo_validation_report.md](../../reports/demo_validation_report.md)) for guaranteed non-zero conversion proof on the API and dashboard.

---

## Related

- [Phase 02 — Detection pipeline](phase_02_detection_pipeline.md)  
- [Phase 04 — POS integration](phase_04_pos_integration.md)  
- [Phase 06 — Product integration](phase_06_product_integration.md)
