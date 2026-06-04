#!/usr/bin/env python3
"""
Regenerate data/synthetic/demo_events.jsonl and demo_pos.csv for demo validation.

Deterministic seed; same schemas and paths as the existing synthetic fixtures.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = REPO_ROOT / "data" / "synthetic" / "demo_events.jsonl"
POS_PATH = REPO_ROOT / "data" / "synthetic" / "demo_pos.csv"

STORE_ID = "STORE_BLR_002"
DAY_START = datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
DAY_END = datetime(2026, 6, 1, 21, 0, 0, tzinfo=timezone.utc)
SEED = 20260601

# Scale targets (deterministic cohort sizes).
NUM_VISITORS = 128
NUM_REENTRY_SESSIONS = 30
BILLING_VISITORS = 96  # ~75% billing reach
QUEUE_ABANDON_COUNT = 14  # ~15% of billing visitors
PURCHASE_BILLING_COUNT = 68  # ~71% of billing visitors; ~53% store conversion

# Canonical product zones (matches pipeline/event_adapter.py ZONE_ID_MAP).
PRODUCT_ZONES: tuple[str, ...] = (
    "FARMSTAY",
    "THEFACESHOP",
    "GOODVIBES",
    "DERMACO",
    "MINIMALIST",
    "MINIMALIST_TOP",
    "AQUOLOGICA",
    "PILGRIM",
    "D_AND_K",
    "MAYBELLINE",
    "FACESCANADA",
    "LAKME",
    "SWISS_BEAUTY",
    "MARS",
    "ALPS",
    "LOREAL",
    "EASTIND",
)

TRAFFIC_HIGH = frozenset({"GOODVIBES", "PILGRIM", "LAKME"})
TRAFFIC_MEDIUM = frozenset(
    {"DERMACO", "MAYBELLINE", "FACESCANADA", "MINIMALIST", "AQUOLOGICA"}
)
TRAFFIC_LOW = frozenset({"FARMSTAY", "D_AND_K", "ALPS", "EASTIND", "MARS"})

CAM2_ZONES = frozenset(
    {"MAYBELLINE", "FACESCANADA", "LAKME", "SWISS_BEAUTY", "MARS", "ALPS", "LOREAL", "EASTIND"}
)

# ZONE_DWELL schema minimum is 30_000 ms (30 s); ranges approximate 15–180 s intent.
DWELL_MS_DEFAULT = (30_000, 180_000)
DWELL_MS_BY_TIER = {
    "high": (45_000, 180_000),
    "medium": (30_000, 120_000),
    "low": (30_000, 75_000),
    "neglected": (30_000, 45_000),
}

PERSONAS: tuple[str, ...] = (
    "quick_buyer",
    "explorer",
    "brand_loyal",
    "window_shopper",
    "impulse_buyer",
    "checkout_abandoner",
    "multi_brand_comparison",
)

# Pre-built journey paths (product zones only; BILLING appended when needed).
JOURNEY_PATHS: dict[str, list[list[str]]] = {
    "quick_buyer": [
        ["GOODVIBES", "BILLING"],
        ["PILGRIM", "BILLING"],
        ["LAKME", "BILLING"],
    ],
    "explorer": [
        ["GOODVIBES", "PILGRIM", "LAKME", "DERMACO"],
        ["MINIMALIST", "AQUOLOGICA", "THEFACESHOP", "GOODVIBES"],
        ["MAYBELLINE", "FACESCANADA", "SWISS_BEAUTY", "LOREAL"],
        ["FARMSTAY", "GOODVIBES", "PILGRIM", "AQUOLOGICA"],
    ],
    "brand_loyal": [
        ["LAKME", "LAKME"],
        ["GOODVIBES", "GOODVIBES", "PILGRIM"],
        ["PILGRIM", "DERMACO"],
    ],
    "window_shopper": [
        ["MAYBELLINE", "FACESCANADA"],
        ["MINIMALIST", "DERMACO", "AQUOLOGICA"],
        ["FARMSTAY"],
        ["MARS", "ALPS"],
        ["THEFACESHOP", "SWISS_BEAUTY"],
    ],
    "impulse_buyer": [
        ["GOODVIBES", "BILLING"],
        ["LAKME", "BILLING"],
        ["MAYBELLINE", "BILLING"],
    ],
    "checkout_abandoner": [
        ["GOODVIBES", "BILLING"],
        ["PILGRIM", "LAKME", "BILLING"],
        ["DERMACO", "BILLING"],
    ],
    "multi_brand_comparison": [
        ["MAYBELLINE", "FACESCANADA", "LAKME"],
        ["GOODVIBES", "PILGRIM", "MINIMALIST", "LAKME"],
        ["AQUOLOGICA", "DERMACO", "THEFACESHOP"],
    ],
}


@dataclass
class VisitorPlan:
    visitor_id: str
    persona: str
    reaches_billing: bool
    purchases: bool
    abandons_queue: bool
    is_reentry: bool = False
    entry_at: datetime | None = None
    billing_at: datetime | None = None
    queue_depth: int = 1
    zones: list[str] = field(default_factory=list)
    # Optional: explicit multi-session journeys (used for synthetic staff visitors).
    session_entry_ats: list[datetime] | None = None
    session_zones: list[list[str]] | None = None


def seeded_uuid4(rng: random.Random) -> str:
    bits = rng.getrandbits(128)
    bits &= ~(0xF << 76)
    bits |= 4 << 76
    bits &= ~(0x3 << 62)
    bits |= 2 << 62
    return str(UUID(int=bits))


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def camera_for_zone(zone: str) -> str:
    if zone == "BILLING":
        return "CAM_BILLING_01"
    if zone in CAM2_ZONES:
        return "CAM_SHELF_02"
    return "CAM_SHELF_01"


def zone_tier(zone: str, neglected: frozenset[str]) -> str:
    if zone in neglected:
        return "neglected"
    if zone in TRAFFIC_HIGH:
        return "high"
    if zone in TRAFFIC_MEDIUM:
        return "medium"
    if zone in TRAFFIC_LOW:
        return "low"
    return "medium"


def is_peak_minute(dt: datetime) -> bool:
    hour = dt.hour + dt.minute / 60.0
    return (12.0 <= hour < 14.0) or (18.0 <= hour < 20.0)


def queue_depth_for_time(rng: random.Random, at: datetime) -> int:
    if is_peak_minute(at):
        return rng.randint(4, 8)
    return rng.randint(1, 3)


def dwell_ms_for_zone(
    rng: random.Random,
    zone: str,
    persona: str,
    neglected: frozenset[str],
) -> int:
    tier = zone_tier(zone, neglected)
    lo, hi = DWELL_MS_BY_TIER[tier]
    if tier == "high":
        lo, hi = DWELL_MS_DEFAULT
    if persona == "quick_buyer":
        hi = lo + int((hi - lo) * 0.4)
    elif persona == "explorer":
        lo = lo + int((hi - lo) * 0.25)
    elif persona == "window_shopper":
        hi = lo + int((hi - lo) * 0.55)
    elif persona == "impulse_buyer":
        hi = lo + int((hi - lo) * 0.35)
    elif persona == "brand_loyal" and zone in {"LAKME", "GOODVIBES", "PILGRIM"}:
        lo = lo + int((hi - lo) * 0.3)
    return rng.randint(lo, hi)


def weighted_zone_pick(
    rng: random.Random,
    neglected: frozenset[str],
    *,
    exclude: frozenset[str] | None = None,
) -> str:
    weights: list[float] = []
    zones: list[str] = []
    for zone in PRODUCT_ZONES:
        if exclude and zone in exclude:
            continue
        if zone in neglected:
            w = 0.12
        elif zone in TRAFFIC_HIGH:
            w = 3.0
        elif zone in TRAFFIC_MEDIUM:
            w = 1.5
        elif zone in TRAFFIC_LOW:
            w = 0.55
        else:
            w = 1.0
        zones.append(zone)
        weights.append(w)
    return rng.choices(zones, weights=weights, k=1)[0]


def build_zones_for_visitor(
    rng: random.Random,
    persona: str,
    reaches_billing: bool,
    neglected: frozenset[str],
) -> list[str]:
    if persona == "checkout_abandoner":
        path = rng.choice(JOURNEY_PATHS["checkout_abandoner"])
    elif persona in JOURNEY_PATHS:
        path = list(rng.choice(JOURNEY_PATHS[persona]))
    else:
        path = [weighted_zone_pick(rng, neglected)]

    # De-duplicate consecutive zones while preserving order.
    deduped: list[str] = []
    for zone in path:
        if zone == "BILLING":
            continue
        if not deduped or deduped[-1] != zone:
            deduped.append(zone)

    if persona == "explorer" and len(deduped) < 4:
        while len(deduped) < 4:
            extra = weighted_zone_pick(rng, neglected, exclude=frozenset(deduped))
            if not deduped or deduped[-1] != extra:
                deduped.append(extra)

    if persona == "window_shopper" and len(deduped) > 3:
        deduped = deduped[:3]

    if reaches_billing:
        if "BILLING" not in deduped:
            deduped.append("BILLING")
    else:
        deduped = [z for z in deduped if z != "BILLING"]

    if not deduped and not reaches_billing:
        deduped = [weighted_zone_pick(rng, neglected)]

    return deduped


def basket_value_inr(rng: random.Random, *, peak: bool) -> float:
    mu = 7.15 if peak else 7.0
    raw = rng.lognormvariate(mu, 0.36)
    return round(max(299.0, min(3499.0, raw)), 2)


def entry_minute_weights() -> tuple[list[int], list[float]]:
    minutes = list(range(0, 660, 5))
    weights: list[float] = []
    for m in minutes:
        hour = 10 + m / 60.0
        w = 1.0
        if 12.0 <= hour < 14.0 or 18.0 <= hour < 20.0:
            w = 2.8
        elif 11.0 <= hour < 12.0 or 14.0 <= hour < 17.0:
            w = 1.4
        elif hour >= 20.5:
            w = 0.55
        weights.append(w)
    return minutes, weights


def build_visitor_plans(rng: random.Random) -> tuple[list[VisitorPlan], frozenset[str]]:
    neglected = frozenset(rng.sample(list(TRAFFIC_LOW | {"MARS", "EASTIND"}), k=2))

    persona_slots: list[str] = []
    counts = {
        "quick_buyer": 16,
        "explorer": 28,
        "brand_loyal": 18,
        "window_shopper": 22,
        "impulse_buyer": 14,
        "checkout_abandoner": 14,
        "multi_brand_comparison": 16,
    }
    for name, count in counts.items():
        persona_slots.extend([name] * count)
    persona_slots = persona_slots[:NUM_VISITORS]
    rng.shuffle(persona_slots)

    billing_flags = [True] * BILLING_VISITORS + [False] * (NUM_VISITORS - BILLING_VISITORS)
    rng.shuffle(billing_flags)

    purchase_flags = [False] * NUM_VISITORS
    billing_indices = [i for i, flag in enumerate(billing_flags) if flag]
    rng.shuffle(billing_indices)

    abandon_indices = set()
    abandon_pool = [i for i in billing_indices if persona_slots[i] == "checkout_abandoner"]
    abandon_indices.update(abandon_pool[: min(len(abandon_pool), QUEUE_ABANDON_COUNT)])
    remaining_abandon = QUEUE_ABANDON_COUNT - len(abandon_indices)
    if remaining_abandon > 0:
        others = [i for i in billing_indices if i not in abandon_indices]
        rng.shuffle(others)
        abandon_indices.update(others[:remaining_abandon])

    purchase_pool = [
        i
        for i in billing_indices
        if i not in abandon_indices and persona_slots[i] != "checkout_abandoner"
    ]
    rng.shuffle(purchase_pool)
    for idx in purchase_pool[:PURCHASE_BILLING_COUNT]:
        purchase_flags[idx] = True

    minutes, weights = entry_minute_weights()
    entry_offsets = sorted(rng.choices(minutes, weights=weights, k=NUM_VISITORS))

    plans: list[VisitorPlan] = []
    for i, persona in enumerate(persona_slots):
        reaches_billing = billing_flags[i]
        plans.append(
            VisitorPlan(
                visitor_id=f"VIS_{i + 1:04d}",
                persona=persona,
                reaches_billing=reaches_billing,
                purchases=purchase_flags[i],
                abandons_queue=i in abandon_indices,
                zones=build_zones_for_visitor(rng, persona, reaches_billing, neglected),
                entry_at=DAY_START + timedelta(minutes=entry_offsets[i]),
            )
        )

    # Demo staff visitors (do NOT flag events as staff; must satisfy heuristic criteria naturally).
    # Target: 4 sessions (=> 3 re-entries), 8–12 unique zones, 30–60 min total store time.
    plans.extend(
        [
            VisitorPlan(
                visitor_id="VIS_staff001",
                persona="explorer",
                reaches_billing=False,
                purchases=False,
                abandons_queue=False,
                entry_at=DAY_START + timedelta(minutes=22),
                session_entry_ats=[
                    DAY_START + timedelta(minutes=22),
                    DAY_START + timedelta(hours=2, minutes=15),
                    DAY_START + timedelta(hours=5, minutes=5),
                    DAY_START + timedelta(hours=8, minutes=10),
                ],
                session_zones=[
                    ["GOODVIBES", "PILGRIM", "LAKME"],
                    ["DERMACO", "MINIMALIST", "AQUOLOGICA"],
                    ["MAYBELLINE", "FACESCANADA", "SWISS_BEAUTY"],
                    ["LOREAL", "EASTIND", "FARMSTAY"],
                ],
                zones=["GOODVIBES", "PILGRIM", "LAKME"],
            ),
            VisitorPlan(
                visitor_id="VIS_staff002",
                persona="multi_brand_comparison",
                reaches_billing=False,
                purchases=False,
                abandons_queue=False,
                entry_at=DAY_START + timedelta(minutes=40),
                session_entry_ats=[
                    DAY_START + timedelta(minutes=40),
                    DAY_START + timedelta(hours=3, minutes=0),
                    DAY_START + timedelta(hours=5, minutes=55),
                    DAY_START + timedelta(hours=9, minutes=0),
                ],
                session_zones=[
                    ["MINIMALIST", "MINIMALIST_TOP", "DERMACO"],
                    ["THEFACESHOP", "GOODVIBES", "PILGRIM"],
                    ["D_AND_K", "MARS", "ALPS"],
                    ["LAKME", "MAYBELLINE", "FACESCANADA"],
                ],
                zones=["MINIMALIST", "MINIMALIST_TOP", "DERMACO"],
            ),
        ]
    )

    reentry_candidates = [
        p
        for p in plans
        if not p.purchases and p.persona in ("explorer", "window_shopper", "multi_brand_comparison")
    ]
    rng.shuffle(reentry_candidates)
    for plan in reentry_candidates[:NUM_REENTRY_SESSIONS]:
        plan.is_reentry = True

    plans = ensure_zone_coverage(rng, plans, neglected)
    return plans, neglected


def ensure_zone_coverage(
    rng: random.Random,
    plans: list[VisitorPlan],
    neglected: frozenset[str],
) -> list[VisitorPlan]:
    """Guarantee every product zone appears; keep neglected zones at very low traffic."""
    min_visits = {z: (2 if z in neglected else 5) for z in PRODUCT_ZONES}
    counts: dict[str, int] = {z: 0 for z in PRODUCT_ZONES}
    for plan in plans:
        for zone in plan.zones:
            if zone != "BILLING":
                counts[zone] = counts.get(zone, 0) + 1

    for zone in PRODUCT_ZONES:
        while counts[zone] < min_visits[zone]:
            candidate = rng.choice(plans)
            if zone in candidate.zones:
                counts[zone] += 1
                continue
            insert_at = len(candidate.zones)
            if candidate.zones and candidate.zones[-1] == "BILLING":
                insert_at = len(candidate.zones) - 1
            candidate.zones.insert(insert_at, zone)
            counts[zone] += 1

    return plans


def _event(
    rng: random.Random,
    *,
    visitor_id: str,
    event_type: str,
    timestamp: datetime,
    camera_id: str,
    zone_id: str | None = None,
    dwell_ms: int = 0,
    session_seq: int | None = None,
    sku_zone: str | None = None,
    queue_depth: int | None = None,
) -> dict:
    meta: dict = {}
    if sku_zone:
        meta["sku_zone"] = sku_zone
    if session_seq is not None:
        meta["session_seq"] = session_seq
    if queue_depth is not None:
        meta["queue_depth"] = queue_depth

    return {
        "event_id": seeded_uuid4(rng),
        "store_id": STORE_ID,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": iso_z(timestamp),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": False,
        "confidence": round(rng.uniform(0.84, 0.96), 2),
        "metadata": meta,
    }


def emit_zone_dwell(
    rng: random.Random,
    events: list[dict],
    *,
    visitor_id: str,
    zone: str,
    at: datetime,
    persona: str,
    neglected: frozenset[str],
    session_seq: int,
) -> tuple[datetime, int]:
    dwell = dwell_ms_for_zone(rng, zone, persona, neglected)
    dwell_ts = at + timedelta(seconds=rng.randint(8, 35))
    events.append(
        _event(
            rng,
            visitor_id=visitor_id,
            event_type="ZONE_DWELL",
            timestamp=dwell_ts,
            camera_id=camera_for_zone(zone),
            zone_id=zone,
            dwell_ms=dwell,
            session_seq=session_seq,
            sku_zone=zone,
        )
    )
    gap = rng.randint(25, 120)
    if zone in TRAFFIC_HIGH:
        gap = rng.randint(40, 150)
    return dwell_ts + timedelta(seconds=gap), session_seq + 1


def build_session_events(
    rng: random.Random,
    plan: VisitorPlan,
    *,
    entry_at: datetime,
    use_reentry: bool,
    neglected: frozenset[str],
    zones_override: list[str] | None = None,
) -> tuple[list[dict], dict | None]:
    events: list[dict] = []
    session_seq = 1
    t = entry_at

    events.append(
        _event(
            rng,
            visitor_id=plan.visitor_id,
            event_type="REENTRY" if use_reentry else "ENTRY",
            timestamp=t,
            camera_id="CAM_ENTRY_01",
            session_seq=session_seq,
        )
    )
    session_seq += 1
    t += timedelta(seconds=rng.randint(20, 90))

    billing_at: datetime | None = None
    zones = zones_override if zones_override is not None else plan.zones
    for zone in zones:
        if zone == "BILLING":
            depth = queue_depth_for_time(rng, t)
            events.append(
                _event(
                    rng,
                    visitor_id=plan.visitor_id,
                    event_type="BILLING_QUEUE_JOIN",
                    timestamp=t,
                    camera_id=camera_for_zone("BILLING"),
                    zone_id="BILLING",
                    session_seq=session_seq,
                    queue_depth=depth,
                )
            )
            session_seq += 1
            t += timedelta(seconds=rng.randint(35, 150))
            billing_at = t

            if plan.abandons_queue:
                events.append(
                    _event(
                        rng,
                        visitor_id=plan.visitor_id,
                        event_type="BILLING_QUEUE_ABANDON",
                        timestamp=t,
                        camera_id=camera_for_zone("BILLING"),
                        zone_id="BILLING",
                        session_seq=session_seq,
                    )
                )
                session_seq += 1
                t += timedelta(seconds=rng.randint(20, 60))
            break

        t, session_seq = emit_zone_dwell(
            rng,
            events,
            visitor_id=plan.visitor_id,
            zone=zone,
            at=t,
            persona=plan.persona,
            neglected=neglected,
            session_seq=session_seq,
        )

    pos_row: dict | None = None
    if plan.purchases and billing_at is not None and not plan.abandons_queue:
        txn_at = billing_at + timedelta(seconds=rng.randint(75, 210))
        suffix = plan.visitor_id.split("_", 1)[1].upper()
        pos_row = {
            "store_id": STORE_ID,
            "transaction_id": f"TXN_{suffix}",
            "timestamp": iso_z(txn_at),
            "basket_value_inr": basket_value_inr(rng, peak=is_peak_minute(billing_at)),
        }
        t = max(t, txn_at) + timedelta(seconds=rng.randint(30, 90))

    t = min(t + timedelta(minutes=rng.randint(1, 8)), DAY_END - timedelta(minutes=2))
    events.append(
        _event(
            rng,
            visitor_id=plan.visitor_id,
            event_type="EXIT",
            timestamp=t,
            camera_id="CAM_ENTRY_01",
            session_seq=session_seq,
        )
    )
    return events, pos_row


def _visitor_id_from_txn(transaction_id: str) -> str | None:
    if not transaction_id.startswith("TXN_"):
        return None
    suffix = transaction_id.removeprefix("TXN_").split("_")[0]
    if suffix.isdigit():
        return f"VIS_{suffix}"
    return None


def align_pos_to_queue_joins(events: list[dict], pos_rows: list[dict]) -> None:
    join_at: dict[str, datetime] = {}
    for event in events:
        if event["event_type"] != "BILLING_QUEUE_JOIN":
            continue
        join_at[event["visitor_id"]] = datetime.fromisoformat(
            event["timestamp"].replace("Z", "+00:00")
        )

    for row in sorted(pos_rows, key=lambda r: r["transaction_id"]):
        visitor_id = _visitor_id_from_txn(row["transaction_id"])
        if visitor_id is None:
            continue
        joined = join_at.get(visitor_id)
        if joined is None:
            continue
        txn_at = joined + timedelta(seconds=120)
        row["timestamp"] = iso_z(txn_at)


def product_engagement_scores(events: list[dict]) -> dict[str, float]:
    visits: dict[str, int] = {z: 0 for z in PRODUCT_ZONES}
    dwell: dict[str, int] = {z: 0 for z in PRODUCT_ZONES}
    for event in events:
        if event["event_type"] != "ZONE_DWELL":
            continue
        zone = event.get("zone_id")
        if not zone or zone == "BILLING":
            continue
        visits[zone] = visits.get(zone, 0) + 1
        dwell[zone] = dwell.get(zone, 0) + int(event.get("dwell_ms", 0))
    return {
        z: visits.get(z, 0) + dwell.get(z, 0) / 1000.0
        for z in PRODUCT_ZONES
        if visits.get(z, 0) > 0 or dwell.get(z, 0) > 0
    }


def build_dataset() -> tuple[list[dict], list[dict], dict]:
    rng = random.Random(SEED)
    plans, neglected = build_visitor_plans(rng)

    all_events: list[dict] = []
    pos_rows: list[dict] = []
    session_count = 0
    queue_joins = 0
    queue_abandons = 0

    for plan in plans:
        # Default behavior: 1 session, optionally 1 re-entry session.
        if plan.session_entry_ats and plan.session_zones:
            entry_ats = list(plan.session_entry_ats)
            zone_sets = list(plan.session_zones)
        else:
            entry_ats = [plan.entry_at or DAY_START]
            zone_sets = [plan.zones]
            if plan.is_reentry and plan.entry_at:
                reentry_at = min(
                    plan.entry_at + timedelta(hours=rng.randint(2, 5)),
                    DAY_END - timedelta(minutes=50),
                )
                entry_ats.append(reentry_at)
                zone_sets.append(plan.zones)

        for j, (entry_at, zones) in enumerate(zip(entry_ats, zone_sets, strict=False)):
            events, pos = build_session_events(
                rng,
                plan,
                entry_at=entry_at,
                use_reentry=(j > 0),
                neglected=neglected,
                zones_override=zones,
            )
            all_events.extend(events)
            session_count += 1
            queue_joins += sum(
                1 for e in events if e["event_type"] == "BILLING_QUEUE_JOIN"
            )
            queue_abandons += sum(
                1 for e in events if e["event_type"] == "BILLING_QUEUE_ABANDON"
            )
            if pos:
                if j > 0:
                    pos["transaction_id"] = f"{pos['transaction_id']}_R{j+1}"
                pos_rows.append(pos)

    all_events.sort(key=lambda e: e["timestamp"])
    align_pos_to_queue_joins(all_events, pos_rows)

    engagement = product_engagement_scores(all_events)
    active = {z: s for z, s in engagement.items() if s > 0}
    top_zone = max(active, key=active.get) if active else "—"
    weak_zone = min(active, key=active.get) if active else "—"

    billing_reach = sum(1 for p in plans if p.reaches_billing) / NUM_VISITORS
    abandon_rate = queue_abandons / queue_joins if queue_joins else 0.0
    revenue = sum(r["basket_value_inr"] for r in pos_rows)

    stats = {
        "visitors": NUM_VISITORS,
        "sessions": session_count,
        "events": len(all_events),
        "purchases": len(pos_rows),
        "revenue": revenue,
        "conversion_rate": len(pos_rows) / NUM_VISITORS,
        "top_zone": top_zone,
        "weak_zone": weak_zone,
        "billing_reach": billing_reach,
        "queue_abandonment_rate": abandon_rate,
        "neglected_zones": sorted(neglected),
        "queue_joins": queue_joins,
    }
    return all_events, pos_rows, stats


def write_outputs(events: list[dict], pos_rows: list[dict]) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("w", encoding="utf-8") as fh:
        for row in events:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    with POS_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "store_id",
                "transaction_id",
                "timestamp",
                "basket_value_inr",
            ],
        )
        writer.writeheader()
        writer.writerows(pos_rows)


def print_summary(stats: dict) -> None:
    print(f"Visitors: {stats['visitors']}")
    print(f"Sessions: {stats['sessions']}")
    print(f"Events: {stats['events']}")
    print(f"POS Transactions: {stats['purchases']}")
    print(f"Revenue: {stats['revenue']:.2f}")
    print(f"Conversion Rate: {stats['conversion_rate']:.1%}")
    print(f"Top Product Zone: {stats['top_zone']}")
    print(f"Weakest Product Zone: {stats['weak_zone']}")
    print(f"Checkout Reach: {stats['billing_reach']:.1%}")
    print(f"Queue Abandonment Rate: {stats['queue_abandonment_rate']:.1%}")
    neglected = stats.get("neglected_zones", [])
    if neglected:
        print(f"Neglected zones (low traffic): {', '.join(neglected)}")


def main() -> int:
    events, pos_rows, stats = build_dataset()

    targets = (
        (100, 150, stats["visitors"], "visitors"),
        (100, 160, stats["sessions"], "sessions"),
        (600, 1000, stats["events"], "events"),
        (50, 80, stats["purchases"], "POS transactions"),
    )
    for lo, hi, value, label in targets:
        if not (lo <= value <= hi):
            print(
                f"Warning: {label} {value} outside target {lo}–{hi}",
                file=sys.stderr,
            )

    write_outputs(events, pos_rows)
    print_summary(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
