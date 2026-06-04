#!/usr/bin/env python3
"""
Regenerate per-store synthetic validation fixtures (challenge Event schema).

Output:
  data/synthetic/store_1/synthetic_events_store_1.jsonl
  data/synthetic/store_1/synthetic_pos_store_1.csv
  data/synthetic/store_2/synthetic_events_store_2.jsonl
  data/synthetic/store_2/synthetic_pos_store_2.csv

Usage:
    python scripts/generate_synthetic_demo_data.py
    python scripts/generate_synthetic_demo_data.py --store store_1
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.synthetic_paths import (  # noqa: E402
    SUPPORTED_SYNTHETIC_STORES,
    SyntheticStoreSpec,
    all_synthetic_store_specs,
    synthetic_store_spec,
)
from scripts.synthetic_profiles import (  # noqa: E402
    StoreSyntheticProfile,
    profile_for_store,
)

NUM_STAFF_VISITORS = 3

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
    "high_dwell_shopper",
)

STAFF_VISITOR_IDS = ("VIS_staff001", "VIS_staff002", "VIS_staff003")


@dataclass
class VisitorPlan:
    visitor_id: str
    persona: str
    reaches_billing: bool
    purchases: bool
    abandons_queue: bool
    is_reentry: bool = False
    cam3_same_day_reentry: bool = False
    entry_at: datetime | None = None
    zones: list[str] = field(default_factory=list)
    session_entry_ats: list[datetime] | None = None
    session_zones: list[list[str]] | None = None


@dataclass
class StoreContext:
    spec: SyntheticStoreSpec
    profile: StoreSyntheticProfile
    rng: random.Random
    day_start: datetime
    day_end: datetime
    neglected: frozenset[str]


def seeded_uuid4(rng: random.Random) -> str:
    bits = rng.getrandbits(128)
    bits &= ~(0xF << 76)
    bits |= 4 << 76
    bits &= ~(0x3 << 62)
    bits |= 2 << 62
    return str(UUID(int=bits))


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def camera_for_zone(zone: str, profile: StoreSyntheticProfile) -> str:
    if zone == "BILLING":
        return "CAM_BILLING_01"
    if zone in profile.cam2_zones:
        return "CAM_SHELF_02"
    return "CAM_SHELF_01"


def zone_tier(zone: str, neglected: frozenset[str], profile: StoreSyntheticProfile) -> str:
    if zone in neglected:
        return "neglected"
    if zone in profile.traffic_high:
        return "high"
    if zone in profile.traffic_medium:
        return "medium"
    if zone in profile.traffic_low:
        return "low"
    return "medium"


def is_peak_minute(dt: datetime) -> bool:
    hour = dt.hour + dt.minute / 60.0
    return (12.0 <= hour < 14.0) or (18.0 <= hour < 20.0)


def queue_depth_for_time(
    rng: random.Random,
    at: datetime,
    profile: StoreSyntheticProfile,
) -> int:
    if is_peak_minute(at):
        return rng.randint(*profile.queue_peak_range)
    return rng.randint(*profile.queue_off_peak_range)


def dwell_ms_for_zone(
    rng: random.Random,
    zone: str,
    persona: str,
    neglected: frozenset[str],
    profile: StoreSyntheticProfile,
) -> int:
    tier = zone_tier(zone, neglected, profile)
    lo, hi = DWELL_MS_BY_TIER[tier]
    if tier == "high":
        lo, hi = DWELL_MS_DEFAULT
    if persona == "high_dwell_shopper":
        lo = lo + int((hi - lo) * 0.35)
    elif persona == "quick_buyer":
        hi = lo + int((hi - lo) * 0.4)
    elif persona == "window_shopper":
        hi = lo + int((hi - lo) * 0.55)
    return rng.randint(lo, hi)


def weighted_zone_pick(
    rng: random.Random,
    profile: StoreSyntheticProfile,
    neglected: frozenset[str],
    *,
    exclude: frozenset[str] | None = None,
) -> str:
    weights: list[float] = []
    zones: list[str] = []
    for zone in profile.product_zones:
        if exclude and zone in exclude:
            continue
        if zone in neglected:
            w = 0.12
        elif zone in profile.traffic_high:
            w = 3.0
        elif zone in profile.traffic_medium:
            w = 1.5
        elif zone in profile.traffic_low:
            w = 0.55
        else:
            w = 1.0
        zones.append(zone)
        weights.append(w)
    return rng.choices(zones, weights=weights, k=1)[0]


def build_zones_for_visitor(
    rng: random.Random,
    profile: StoreSyntheticProfile,
    persona: str,
    reaches_billing: bool,
    neglected: frozenset[str],
) -> list[str]:
    paths = profile.journey_paths
    if persona == "checkout_abandoner":
        path = list(rng.choice(paths["checkout_abandoner"]))
    elif persona in paths:
        path = list(rng.choice(paths[persona]))
    else:
        path = [weighted_zone_pick(rng, profile, neglected)]

    deduped: list[str] = []
    for zone in path:
        if zone == "BILLING":
            continue
        if not deduped or deduped[-1] != zone:
            deduped.append(zone)

    if reaches_billing and "BILLING" not in deduped:
        deduped.append("BILLING")
    elif not reaches_billing:
        deduped = [z for z in deduped if z != "BILLING"]

    if not deduped:
        deduped = [weighted_zone_pick(rng, profile, neglected)]
    return deduped


def basket_value_inr(
    rng: random.Random,
    profile: StoreSyntheticProfile,
    *,
    peak: bool,
) -> float:
    mu = profile.basket_mu_peak if peak else profile.basket_mu_off_peak
    raw = rng.lognormvariate(mu, 0.36)
    return round(max(299.0, min(3499.0, raw)), 2)


def entry_minute_weights(day_start: datetime, day_end: datetime) -> tuple[list[int], list[float]]:
    total_minutes = int((day_end - day_start).total_seconds() // 60)
    minutes = list(range(0, total_minutes, 5))
    weights: list[float] = []
    for m in minutes:
        hour = day_start.hour + m / 60.0
        w = 1.0
        if 12.0 <= hour < 14.0 or 18.0 <= hour < 20.0:
            w = 2.8
        elif hour >= 20.5:
            w = 0.55
        weights.append(w)
    return minutes, weights


def _event(
    ctx: StoreContext,
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
        "event_id": seeded_uuid4(ctx.rng),
        "store_id": ctx.spec.store_id,
        "camera_id": camera_id,
        "visitor_id": visitor_id,
        "event_type": event_type,
        "timestamp": iso_z(timestamp),
        "zone_id": zone_id,
        "dwell_ms": dwell_ms,
        "is_staff": False,
        "confidence": round(ctx.rng.uniform(0.84, 0.96), 2),
        "metadata": meta,
    }


def emit_shelf_zone_visit(
    ctx: StoreContext,
    events: list[dict],
    *,
    visitor_id: str,
    zone: str,
    at: datetime,
    persona: str,
    session_seq: int,
) -> tuple[datetime, int]:
    cam = camera_for_zone(zone, ctx.profile)
    enter_ts = at + timedelta(seconds=ctx.rng.randint(5, 20))
    events.append(
        _event(
            ctx,
            visitor_id=visitor_id,
            event_type="ZONE_ENTER",
            timestamp=enter_ts,
            camera_id=cam,
            zone_id=zone,
            session_seq=session_seq,
            sku_zone=zone,
        )
    )
    session_seq += 1
    dwell = dwell_ms_for_zone(ctx.rng, zone, persona, ctx.neglected, ctx.profile)
    dwell_ts = enter_ts + timedelta(seconds=ctx.rng.randint(10, 40))
    events.append(
        _event(
            ctx,
            visitor_id=visitor_id,
            event_type="ZONE_DWELL",
            timestamp=dwell_ts,
            camera_id=cam,
            zone_id=zone,
            dwell_ms=dwell,
            session_seq=session_seq,
            sku_zone=zone,
        )
    )
    session_seq += 1
    exit_ts = dwell_ts + timedelta(seconds=max(30, dwell // 1000))
    events.append(
        _event(
            ctx,
            visitor_id=visitor_id,
            event_type="ZONE_EXIT",
            timestamp=exit_ts,
            camera_id=cam,
            zone_id=zone,
            session_seq=session_seq,
            sku_zone=zone,
        )
    )
    gap = ctx.rng.randint(25, 120)
    return exit_ts + timedelta(seconds=gap), session_seq + 1


def emit_billing_queue(
    ctx: StoreContext,
    events: list[dict],
    *,
    plan: VisitorPlan,
    at: datetime,
    session_seq: int,
) -> tuple[datetime, int, datetime | None]:
    depth = queue_depth_for_time(ctx.rng, at, ctx.profile)
    join_ts = at
    events.append(
        _event(
            ctx,
            visitor_id=plan.visitor_id,
            event_type="BILLING_QUEUE_JOIN",
            timestamp=join_ts,
            camera_id="CAM_BILLING_01",
            zone_id="BILLING",
            session_seq=session_seq,
            queue_depth=depth,
        )
    )
    session_seq += 1
    if plan.purchases and not plan.abandons_queue:
        # POS correlation uses billing_activity_at from JOIN; txn must fall within 5 minutes.
        wait_seconds = ctx.rng.randint(45, 150)
    else:
        wait_seconds = ctx.rng.randint(45, 420 if depth >= 4 else 240)
    t = join_ts + timedelta(seconds=wait_seconds)

    if plan.abandons_queue:
        events.append(
            _event(
                ctx,
                visitor_id=plan.visitor_id,
                event_type="BILLING_QUEUE_ABANDON",
                timestamp=t,
                camera_id="CAM_BILLING_01",
                zone_id="BILLING",
                session_seq=session_seq,
            )
        )
        return t + timedelta(seconds=ctx.rng.randint(20, 60)), session_seq + 1, None

    return t, session_seq, join_ts + timedelta(seconds=wait_seconds)


def build_session_events(
    ctx: StoreContext,
    plan: VisitorPlan,
    *,
    entry_at: datetime,
    use_reentry: bool,
    zones_override: list[str] | None = None,
) -> tuple[list[dict], dict | None]:
    events: list[dict] = []
    session_seq = 1
    t = entry_at

    events.append(
        _event(
            ctx,
            visitor_id=plan.visitor_id,
            event_type="REENTRY" if use_reentry else "ENTRY",
            timestamp=t,
            camera_id="CAM_ENTRY_01",
            session_seq=session_seq,
        )
    )
    session_seq += 1
    t += timedelta(seconds=ctx.rng.randint(20, 90))

    queue_completed_at: datetime | None = None
    zones = zones_override if zones_override is not None else plan.zones
    for zone in zones:
        if zone == "BILLING":
            t, session_seq, queue_completed_at = emit_billing_queue(
                ctx, events, plan=plan, at=t, session_seq=session_seq
            )
            break

        t, session_seq = emit_shelf_zone_visit(
            ctx,
            events,
            visitor_id=plan.visitor_id,
            zone=zone,
            at=t,
            persona=plan.persona,
            session_seq=session_seq,
        )

    pos_row: dict | None = None
    if plan.purchases and queue_completed_at is not None and not plan.abandons_queue:
        txn_at = queue_completed_at + timedelta(
            seconds=ctx.rng.randint(30, 120)
        )
        suffix = plan.visitor_id.removeprefix("VIS_")
        pos_row = {
            "store_id": ctx.spec.store_id,
            "transaction_id": f"TXN_{suffix.upper()}",
            "timestamp": iso_z(txn_at),
            "basket_value_inr": basket_value_inr(
                ctx.rng, ctx.profile, peak=is_peak_minute(queue_completed_at)
            ),
        }
        t = max(t, txn_at) + timedelta(seconds=ctx.rng.randint(30, 90))

    t = min(t + timedelta(minutes=ctx.rng.randint(1, 8)), ctx.day_end - timedelta(minutes=2))
    events.append(
        _event(
            ctx,
            visitor_id=plan.visitor_id,
            event_type="EXIT",
            timestamp=t,
            camera_id="CAM_ENTRY_01",
            session_seq=session_seq,
        )
    )
    return events, pos_row


def build_cam3_same_day_reentry(
    ctx: StoreContext,
    plan: VisitorPlan,
) -> tuple[list[dict], list[dict]]:
    """ENTRY → shop → EXIT → REENTRY → shop → EXIT on one visitor_id."""
    events: list[dict] = []
    pos_rows: list[dict] = []
    entry_at = plan.entry_at or ctx.day_start + timedelta(hours=2)

    first_events, pos1 = build_session_events(
        ctx, plan, entry_at=entry_at, use_reentry=False, zones_override=plan.zones[:2]
    )
    events.extend(first_events)
    if pos1:
        pos_rows.append(pos1)

    reentry_at = entry_at + timedelta(hours=ctx.rng.randint(1, 3))
    second_events, pos2 = build_session_events(
        ctx,
        plan,
        entry_at=reentry_at,
        use_reentry=True,
        zones_override=plan.zones,
    )
    events.extend(second_events)
    if pos2:
        pos2["transaction_id"] = f"{pos2['transaction_id']}_R2"
        pos_rows.append(pos2)

    return events, pos_rows


def build_staff_plans(ctx: StoreContext) -> list[VisitorPlan]:
    base = ctx.day_start
    zone_sets = list(ctx.profile.staff_zone_sets)
    plans: list[VisitorPlan] = []
    for idx, visitor_id in enumerate(STAFF_VISITOR_IDS):
        entry_offsets = [
            base + timedelta(minutes=30 + idx * 15),
            base + timedelta(hours=2 + idx),
            base + timedelta(hours=5 + idx),
            base + timedelta(hours=8 + idx),
        ]
        plans.append(
            VisitorPlan(
                visitor_id=visitor_id,
                persona="high_dwell_shopper",
                reaches_billing=False,
                purchases=False,
                abandons_queue=False,
                session_entry_ats=entry_offsets,
                session_zones=zone_sets,
                zones=zone_sets[0],
                entry_at=entry_offsets[0],
            )
        )
    return plans


def build_visitor_plans(ctx: StoreContext) -> list[VisitorPlan]:
    rng = ctx.rng
    neglected = ctx.neglected
    profile = ctx.profile
    num_visitors = profile.num_visitors

    base_counts = {
        "quick_buyer": 12,
        "explorer": 18,
        "brand_loyal": 12,
        "window_shopper": 16,
        "impulse_buyer": 10,
        "checkout_abandoner": 10,
        "multi_brand_comparison": 12,
        "high_dwell_shopper": 10,
    }
    persona_slots: list[str] = []
    for name, count in base_counts.items():
        persona_slots.extend([name] * count)
    while len(persona_slots) < num_visitors:
        persona_slots.append(rng.choice(PERSONAS))
    persona_slots = persona_slots[:num_visitors]
    rng.shuffle(persona_slots)

    billing_flags = [True] * profile.billing_visitors + [False] * (
        num_visitors - profile.billing_visitors
    )
    rng.shuffle(billing_flags)

    purchase_flags = [False] * num_visitors
    billing_indices = [i for i, flag in enumerate(billing_flags) if flag]
    rng.shuffle(billing_indices)

    abandon_indices: set[int] = set()
    abandon_pool = [i for i in billing_indices if persona_slots[i] == "checkout_abandoner"]
    abandon_indices.update(
        abandon_pool[: min(len(abandon_pool), profile.queue_abandon_count)]
    )
    remaining = profile.queue_abandon_count - len(abandon_indices)
    if remaining > 0:
        others = [i for i in billing_indices if i not in abandon_indices]
        rng.shuffle(others)
        abandon_indices.update(others[:remaining])

    purchase_pool = [
        i
        for i in billing_indices
        if i not in abandon_indices and persona_slots[i] != "checkout_abandoner"
    ]
    rng.shuffle(purchase_pool)
    for idx in purchase_pool[: profile.purchase_billing_count]:
        purchase_flags[idx] = True

    minutes, weights = entry_minute_weights(ctx.day_start, ctx.day_end)
    entry_offsets = sorted(rng.choices(minutes, weights=weights, k=num_visitors))

    plans: list[VisitorPlan] = []
    for i, persona in enumerate(persona_slots):
        plans.append(
            VisitorPlan(
                visitor_id=f"VIS_{i + 1:04d}",
                persona=persona,
                reaches_billing=billing_flags[i],
                purchases=purchase_flags[i],
                abandons_queue=i in abandon_indices,
                zones=build_zones_for_visitor(
                    rng, profile, persona, billing_flags[i], neglected
                ),
                entry_at=ctx.day_start + timedelta(minutes=entry_offsets[i]),
            )
        )

    for j in range(profile.num_cam3_reentry_visitors):
        plan = plans[j]
        plan.cam3_same_day_reentry = True

    plans.extend(build_staff_plans(ctx))
    return plans


def add_ambiguous_pos_rows(
    ctx: StoreContext,
    pos_rows: list[dict],
    events: list[dict],
) -> None:
    """Non-matching and ambiguous POS rows for purchase-matching edge cases."""
    rng = ctx.rng
    join_times = [
        datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))
        for e in events
        if e["event_type"] == "BILLING_QUEUE_JOIN"
    ]
    if not join_times:
        return
    cluster = sorted(join_times)[len(join_times) // 2]
    pos_rows.append(
        {
            "store_id": ctx.spec.store_id,
            "transaction_id": f"TXN_AMBIG_{ctx.spec.store_key.upper()}",
            "timestamp": iso_z(cluster + timedelta(seconds=90)),
            "basket_value_inr": 999.0,
        }
    )
    pos_rows.append(
        {
            "store_id": ctx.spec.store_id,
            "transaction_id": f"TXN_NOMATCH_{ctx.spec.store_key.upper()}",
            "timestamp": iso_z(ctx.day_end - timedelta(minutes=30)),
            "basket_value_inr": 450.0,
        }
    )


def build_dataset(spec: SyntheticStoreSpec) -> tuple[list[dict], list[dict], dict]:
    day_start = datetime(
        spec.metric_date.year,
        spec.metric_date.month,
        spec.metric_date.day,
        10,
        0,
        0,
        tzinfo=timezone.utc,
    )
    day_end = day_start + timedelta(hours=11)
    profile = profile_for_store(spec.store_key)
    rng = random.Random(spec.seed)
    pool = list(profile.neglected_pool)
    neglected = frozenset(
        rng.sample(pool, k=min(profile.neglected_count, len(pool)))
    )
    ctx = StoreContext(
        spec=spec,
        profile=profile,
        rng=rng,
        day_start=day_start,
        day_end=day_end,
        neglected=neglected,
    )

    plans = build_visitor_plans(ctx)
    all_events: list[dict] = []
    pos_rows: list[dict] = []
    session_count = 0
    queue_joins = 0
    queue_abandons = 0
    reentry_events = 0

    for plan in plans:
        if plan.cam3_same_day_reentry:
            events, purchase_rows = build_cam3_same_day_reentry(ctx, plan)
            all_events.extend(events)
            session_count += 2
            pos_rows.extend(purchase_rows)
            reentry_events += sum(1 for e in events if e["event_type"] == "REENTRY")
            queue_joins += sum(1 for e in events if e["event_type"] == "BILLING_QUEUE_JOIN")
            queue_abandons += sum(
                1 for e in events if e["event_type"] == "BILLING_QUEUE_ABANDON"
            )
            continue

        if plan.session_entry_ats and plan.session_zones:
            entry_ats = list(plan.session_entry_ats)
            zone_sets = list(plan.session_zones)
        else:
            entry_ats = [plan.entry_at or ctx.day_start]
            zone_sets = [plan.zones]
            if plan.is_reentry and plan.entry_at:
                entry_ats.append(
                    min(plan.entry_at + timedelta(hours=rng.randint(2, 5)), ctx.day_end - timedelta(minutes=50))
                )
                zone_sets.append(plan.zones)

        for j, (entry_at, zones) in enumerate(zip(entry_ats, zone_sets, strict=True)):
            events, pos = build_session_events(
                ctx,
                plan,
                entry_at=entry_at,
                use_reentry=(j > 0),
                zones_override=zones,
            )
            all_events.extend(events)
            session_count += 1
            reentry_events += sum(1 for e in events if e["event_type"] == "REENTRY")
            queue_joins += sum(1 for e in events if e["event_type"] == "BILLING_QUEUE_JOIN")
            queue_abandons += sum(
                1 for e in events if e["event_type"] == "BILLING_QUEUE_ABANDON"
            )
            if pos:
                if j > 0:
                    pos["transaction_id"] = f"{pos['transaction_id']}_R{j + 1}"
                pos_rows.append(pos)

    all_events.sort(key=lambda e: e["timestamp"])
    add_ambiguous_pos_rows(ctx, pos_rows, all_events)

    shoppers = profile.num_visitors
    matched_purchases = sum(
        1
        for r in pos_rows
        if r["transaction_id"].startswith("TXN_")
        and not r["transaction_id"].startswith(("TXN_AMBIG_", "TXN_NOMATCH_"))
    )
    stats = {
        "store_key": spec.store_key,
        "store_id": spec.store_id,
        "visitors": shoppers,
        "sessions": session_count,
        "events": len(all_events),
        "purchases": len(pos_rows),
        "matched_purchases": matched_purchases,
        "reentry_events": reentry_events,
        "conversion_rate": matched_purchases / shoppers,
        "queue_abandonment_rate": queue_abandons / queue_joins if queue_joins else 0.0,
        "revenue": sum(r["basket_value_inr"] for r in pos_rows),
    }
    return all_events, pos_rows, stats


def write_outputs(spec: SyntheticStoreSpec, events: list[dict], pos_rows: list[dict]) -> None:
    spec.events_path.parent.mkdir(parents=True, exist_ok=True)
    with spec.events_path.open("w", encoding="utf-8") as fh:
        for row in events:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    with spec.pos_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["store_id", "transaction_id", "timestamp", "basket_value_inr"],
        )
        writer.writeheader()
        writer.writerows(pos_rows)


def print_summary(stats: dict) -> None:
    print(f"Store: {stats['store_key']} ({stats.get('store_id', '')})")
    print(f"Visitors: {stats['visitors']}")
    print(f"Sessions: {stats['sessions']}")
    print(f"Events: {stats['events']}")
    print(f"REENTRY events: {stats['reentry_events']}")
    print(f"POS Transactions: {stats['purchases']}")
    print(f"Revenue: {stats['revenue']:.2f}")
    print(f"Conversion Rate: {stats['conversion_rate']:.1%}")
    print(f"Queue Abandonment Rate: {stats['queue_abandonment_rate']:.1%}")


def generate_for_store(store_key: str) -> dict:
    spec = synthetic_store_spec(store_key)
    events, pos_rows, stats = build_dataset(spec)
    write_outputs(spec, events, pos_rows)
    print(f"Wrote {spec.events_path}")
    print(f"Wrote {spec.pos_path}")
    print_summary(stats)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate per-store synthetic validation data")
    parser.add_argument(
        "--store",
        choices=[*SUPPORTED_SYNTHETIC_STORES, "all"],
        default="all",
        help="Which store fixture to regenerate (default: all)",
    )
    args = parser.parse_args()
    keys = all_synthetic_store_specs() if args.store == "all" else (synthetic_store_spec(args.store),)
    for spec in keys:
        generate_for_store(spec.store_key)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
