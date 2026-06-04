"""Per-store synthetic fixture differentiation."""

from __future__ import annotations

from scripts.synthetic_paths import synthetic_store_spec
from scripts.synthetic_profiles import profile_for_store


def test_store_ids_differ() -> None:
    s1 = synthetic_store_spec("store_1")
    s2 = synthetic_store_spec("store_2")
    assert s1.store_id == "STORE_BLR_002"
    assert s2.store_id == "STORE_BLR_003"


def test_zone_profiles_differ() -> None:
    p1 = profile_for_store("store_1")
    p2 = profile_for_store("store_2")
    assert p1.traffic_high != p2.traffic_high
    assert "LAKME" in p1.traffic_high
    assert "MAMAEARTH" in p2.traffic_high
    assert p1.num_visitors < p2.num_visitors
    assert p1.queue_abandon_count < p2.queue_abandon_count
