# Business Metrics Reference

Every metric on the Store Intelligence dashboard exists to answer a **store manager question**. This document explains what each number means in business terms — not how it is coded.

**North Star:** Conversion rate — the share of visitors who completed a purchase.

---

## 1. Unique Visitors

| | |
|---|---|
| **Definition** | Distinct customers who entered the store during the selected UTC day |
| **Formula** | Count of unique non-staff `visitor_id` values with at least one ENTRY or REENTRY event |
| **Business question** | How many customers came in today? |
| **Why it matters** | Foot traffic is the denominator for conversion, revenue per visitor, and staffing ratios |
| **Dashboard location** | Key metrics → **Visitors** |
| **Data source** | `GET /stores/{id}/metrics` → `unique_visitors` |

---

## 2. Sessions

| | |
|---|---|
| **Definition** | Individual store visits — one session opens on ENTRY/REENTRY and closes on EXIT |
| **Formula** | Count of non-staff customer sessions opened on the UTC day |
| **Business question** | How many separate visits occurred? |
| **Why it matters** | Distinguishes repeat visits (REENTRY) from unique visitors; supports dwell and queue analysis per visit |
| **Dashboard location** | Key metrics → **Sessions** |
| **Data source** | `GET /stores/{id}/metrics` → `total_sessions` |

---

## 3. Conversion Rate

| | |
|---|---|
| **Definition** | Share of unique visitors who completed a purchase |
| **Formula** | Converted visitors ÷ unique visitors (visitor counts once even after REENTRY) |
| **Business question** | How many visitors became buyers? |
| **Why it matters** | Primary KPI for store performance — links CCTV foot traffic to POS outcomes |
| **Dashboard location** | Key metrics → **Conversion rate** |
| **Data source** | `GET /stores/{id}/metrics` → `conversion_rate` |

A visitor converts when billing activity occurred within **5 minutes before** a POS transaction timestamp.

---

## 4. Revenue (INR)

| | |
|---|---|
| **Definition** | Total sales value recorded by POS for the day |
| **Formula** | Sum of `basket_value_inr` across all POS transactions on the UTC day |
| **Business question** | What sales were generated? |
| **Why it matters** | Connects store traffic intelligence to financial outcome; validates conversion quality |
| **Dashboard location** | Key metrics → **Revenue (INR)** |
| **Data source** | `GET /stores/{id}/metrics` → `total_revenue_inr` |

---

## 5. Average Session Dwell

| | |
|---|---|
| **Definition** | Typical time a customer spends in product zones during one visit |
| **Formula** | Mean total in-zone dwell (milliseconds) per customer session |
| **Business question** | Are customers browsing or rushing through? |
| **Why it matters** | Low dwell may signal poor product placement; high dwell without conversion may signal friction at checkout |
| **Dashboard location** | Key metrics → **Avg session dwell** |
| **Data source** | `GET /stores/{id}/metrics` → `average_dwell_time_ms` |

---

## 6. Average Dwell by Zone

| | |
|---|---|
| **Definition** | Mean time spent in each named product zone per session visit |
| **Formula** | Per zone: total dwell ÷ number of session visits to that zone |
| **Business question** | Where do customers spend the most time? |
| **Why it matters** | Reveals which categories attract attention — useful for planogram and promotional placement |
| **Dashboard location** | **Average dwell by zone** table (below Key metrics) |
| **Data source** | `GET /stores/{id}/metrics` → `average_dwell_by_zone` |

---

## 7. Queue Depth

| | |
|---|---|
| **Definition** | Current number of customers waiting at billing |
| **Formula** | Latest `queue_depth` from a BILLING_QUEUE_JOIN event on the UTC day |
| **Business question** | Is billing causing friction right now? |
| **Why it matters** | Long queues increase abandonment and reduce conversion; signals need for extra cashiers |
| **Dashboard location** | Key metrics → **Queue depth** |
| **Data source** | `GET /stores/{id}/metrics` → `current_queue_depth` |

---

## 8. Queue Abandonment Rate

| | |
|---|---|
| **Definition** | Share of customers who joined the billing queue but left without purchasing |
| **Formula** | Sessions that abandoned queue ÷ sessions that joined queue |
| **Business question** | Are customers giving up at checkout? |
| **Why it matters** | High abandonment indicates wait-time pain — lost revenue that foot traffic alone cannot explain |
| **Dashboard location** | Key metrics → **Queue abandonment** |
| **Data source** | `GET /stores/{id}/metrics` → `queue_abandonment_rate` |

---

## 9. Billing Reach Rate

| | |
|---|---|
| **Definition** | Share of customer sessions that reached the billing area |
| **Formula** | Sessions with billing activity ÷ total customer sessions |
| **Business question** | How many visitors make it to checkout? |
| **Why it matters** | Separates "browsed but never tried to buy" from "reached billing but did not convert" |
| **Dashboard location** | Available via API (`GET /metrics` → `billing_reach_rate`); not shown as a separate KPI card |
| **Data source** | `GET /stores/{id}/metrics` → `billing_reach_rate` |

---

## 10. Funnel Drop-off

| | |
|---|---|
| **Definition** | Percentage of visitors lost between consecutive journey stages |
| **Formula** | (Previous stage count − current stage count) ÷ previous stage count × 100 |
| **Business question** | Where are customers dropping off? |
| **Why it matters** | Pinpoints the weakest link: entry → zone engagement → billing queue → purchase |
| **Dashboard location** | **Conversion funnel** — drop-off % per stage |
| **Data source** | `GET /stores/{id}/funnel` → `stages[].drop_off_pct` |

**Funnel stages:** Visitors (entry) → Engaged (zone visit) → Billing queue → Purchased (POS).

---

## 11. Zone Engagement Score

| | |
|---|---|
| **Definition** | Relative attractiveness of each product zone compared to the busiest zone |
| **Formula** | Raw score = visit count + (total dwell ÷ 1000); highest zone normalized to **100**, others proportional |
| **Business question** | Which zones generate the most customer attention? |
| **Why it matters** | Highlights hero categories vs underperforming areas for layout and merchandising decisions |
| **Dashboard location** | **Zone heatmap** — bar chart and zone table |
| **Data source** | `GET /stores/{id}/heatmap` → `zones[].normalized_score` |

---

## 12. Heatmap Confidence

| | |
|---|---|
| **Definition** | Reliability flag for comparing zone scores |
| **Formula** | HIGH when ≥ 20 customer sessions on the day; LOW otherwise |
| **Business question** | Can I trust these zone comparisons today? |
| **Why it matters** | Prevents over-reacting to heatmap rankings based on too few visits |
| **Dashboard location** | **Zone heatmap** → **Data confidence: HIGH / LOW** badge |
| **Data source** | `GET /stores/{id}/heatmap` → `data_confidence` |

---

## 13. Dead Zone Alert

| | |
|---|---|
| **Definition** | A product zone with unusually low customer engagement |
| **Formula** | Triggered when a zone's normalized engagement score falls below threshold (WARN &lt; 20, CRITICAL &lt; 10) |
| **Business question** | Which areas need layout or product intervention? |
| **Why it matters** | Dead zones waste floor space and may indicate poor signage, stock gaps, or wrong category mix |
| **Dashboard location** | **Anomalies** → Unusual traffic alerts |
| **Data source** | `GET /stores/{id}/anomalies` → `DEAD_ZONE` |

Each alert includes a **suggested action** for store staff (e.g. review planogram, check stock visibility).

---

## 14. Queue Spike Alert

| | |
|---|---|
| **Definition** | Unusually high billing queue activity for the day |
| **Formula** | Triggered when BILLING_QUEUE_JOIN count exceeds threshold (WARN ≥ 10, CRITICAL ≥ 20) |
| **Business question** | Does billing need immediate staffing attention? |
| **Why it matters** | Queue spikes correlate with abandonment and lost sales — actionable in real time |
| **Dashboard location** | **Anomalies** → Queue alerts |
| **Data source** | `GET /stores/{id}/anomalies` → `QUEUE_SPIKE` |

---

## 15. Feed Health Status

| | |
|---|---|
| **Definition** | Whether CCTV event data is arriving reliably for analytics |
| **Formula** | STALE when no event ingested within configured lag (default 10 minutes); otherwise Live |
| **Business question** | Is the CCTV feed healthy? |
| **Why it matters** | Stale feeds mean KPIs reflect outdated activity — managers should not act on stale numbers |
| **Dashboard location** | **System health** → Service status, Database, Last event, **Feed status** |
| **Data source** | `GET /health` → `status`, `stores[].stale`, `warnings` (includes `STALE_FEED`) |

---

## Summary table

| Metric | Business Question |
|--------|-------------------|
| Conversion Rate | How many visitors became buyers? |
| Heatmap | Which zones attract attention? |
| Funnel | Where are customers dropping off? |
| Queue Depth | Is billing causing friction? |
| Revenue | What sales were generated? |
| Anomalies | What requires staff action? |
| Unique Visitors | How many customers entered? |
| Sessions | How many separate visits occurred? |
| Avg Session Dwell | Are customers browsing meaningfully? |
| Dwell by Zone | Where do customers spend time? |
| Queue Abandonment | Are customers leaving without buying at checkout? |
| Feed Health | Can I trust that data is current? |

---

## How metrics support the challenge goals

The Apex Retail challenge asks teams to turn disconnected CCTV and POS data into **actionable store intelligence**. These metrics close that gap:

**Customer experience** — Queue depth, abandonment rate, and funnel drop-off reveal friction before customers complain. Managers can shorten waits or redeploy staff during spikes.

**Store layout decisions** — Heatmap engagement scores and dwell-by-zone tables show which categories earn attention vs which are ignored. Dead zone alerts flag areas needing planogram or signage fixes.

**Staffing decisions** — Queue spike alerts and billing reach rate indicate when checkout capacity is insufficient. Feed health confirms whether live monitoring is trustworthy.

**Sales conversion** — Conversion rate (North Star), funnel stages, and revenue tie foot traffic to purchases. Drop-off between zone visit and billing queue highlights fixable leakage.

**Operational monitoring** — System health and STALE_FEED warnings ensure analytics reflect current store activity, not yesterday's pipeline run.

---

## Related

- [business_question_mapping.md](business_question_mapping.md) — problem statement → dashboard mapping
- [api_reference.md](api_reference.md) — HTTP field reference
- [../DESIGN.md](../DESIGN.md) — technical architecture
