"""Per-store synthetic fixture profiles (zones, scale, checkout behaviour)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StoreSyntheticProfile:
    """Tuning for ``generate_synthetic_demo_data.build_dataset``."""

    product_zones: tuple[str, ...]
    traffic_high: frozenset[str]
    traffic_medium: frozenset[str]
    traffic_low: frozenset[str]
    cam2_zones: frozenset[str]
    journey_paths: dict[str, list[list[str]]]
    staff_zone_sets: tuple[list[str], ...]
    num_visitors: int
    num_cam3_reentry_visitors: int
    billing_visitors: int
    purchase_billing_count: int
    queue_abandon_count: int
    neglected_pool: frozenset[str]
    neglected_count: int
    basket_mu_peak: float
    basket_mu_off_peak: float
    queue_peak_range: tuple[int, int]
    queue_off_peak_range: tuple[int, int]


# Brigade Bangalore — beauty megastore layout (store_1).
STORE_1_PROFILE = StoreSyntheticProfile(
    product_zones=(
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
    ),
    traffic_high=frozenset({"LAKME", "PILGRIM", "GOODVIBES"}),
    traffic_medium=frozenset(
        {"DERMACO", "MAYBELLINE", "FACESCANADA", "MINIMALIST", "AQUOLOGICA", "SWISS_BEAUTY"}
    ),
    traffic_low=frozenset({"FARMSTAY", "D_AND_K", "ALPS", "EASTIND", "MARS", "THEFACESHOP"}),
    cam2_zones=frozenset(
        {
            "MAYBELLINE",
            "FACESCANADA",
            "LAKME",
            "SWISS_BEAUTY",
            "MARS",
            "ALPS",
            "LOREAL",
            "EASTIND",
        }
    ),
    journey_paths={
        "quick_buyer": [["LAKME", "BILLING"], ["PILGRIM", "BILLING"], ["GOODVIBES", "BILLING"]],
        "explorer": [
            ["GOODVIBES", "PILGRIM", "LAKME", "DERMACO"],
            ["MINIMALIST", "AQUOLOGICA", "THEFACESHOP", "FACESCANADA"],
            ["MAYBELLINE", "SWISS_BEAUTY", "LOREAL", "LAKME"],
        ],
        "brand_loyal": [["LAKME", "LAKME"], ["PILGRIM", "PILGRIM", "GOODVIBES"]],
        "window_shopper": [["MAYBELLINE", "FACESCANADA"], ["FARMSTAY"], ["MARS", "ALPS"]],
        "impulse_buyer": [["GOODVIBES", "BILLING"], ["LAKME", "BILLING"]],
        "checkout_abandoner": [["LAKME", "PILGRIM", "BILLING"], ["GOODVIBES", "BILLING"]],
        "multi_brand_comparison": [
            ["MAYBELLINE", "FACESCANADA", "LAKME"],
            ["GOODVIBES", "PILGRIM", "MINIMALIST", "LAKME"],
        ],
        "high_dwell_shopper": [
            ["DERMACO", "MINIMALIST", "AQUOLOGICA", "LAKME"],
            ["PILGRIM", "GOODVIBES", "FACESCANADA", "SWISS_BEAUTY"],
        ],
    },
    staff_zone_sets=(
        ["LAKME", "PILGRIM", "GOODVIBES", "DERMACO", "MINIMALIST"],
        ["MAYBELLINE", "FACESCANADA", "SWISS_BEAUTY", "LOREAL", "EASTIND"],
        ["FARMSTAY", "THEFACESHOP", "AQUOLOGICA", "D_AND_K", "MARS"],
        ["MINIMALIST_TOP", "THEFACESHOP", "SWISS_BEAUTY", "MAYBELLINE", "DERMACO"],
    ),
    num_visitors=92,
    num_cam3_reentry_visitors=18,
    billing_visitors=72,
    purchase_billing_count=64,
    queue_abandon_count=9,
    neglected_pool=frozenset({"FARMSTAY", "MARS", "ALPS", "EASTIND", "D_AND_K"}),
    neglected_count=2,
    basket_mu_peak=7.25,
    basket_mu_off_peak=7.05,
    queue_peak_range=(3, 7),
    queue_off_peak_range=(1, 3),
)

# Footage2 competition store — different shelf brands (store_2 / STORE_BLR_003).
STORE_2_PROFILE = StoreSyntheticProfile(
    product_zones=(
        "MAMAEARTH",
        "CETAPHIL",
        "NEUTROGENA",
        "PILGRIM",
        "GOODVIBES",
        "D_AND_K",
        "DERMACOMP",
    ),
    traffic_high=frozenset({"MAMAEARTH", "CETAPHIL", "NEUTROGENA"}),
    traffic_medium=frozenset({"PILGRIM", "GOODVIBES"}),
    traffic_low=frozenset({"D_AND_K", "DERMACOMP"}),
    cam2_zones=frozenset({"MAMAEARTH", "CETAPHIL", "NEUTROGENA", "PILGRIM", "GOODVIBES"}),
    journey_paths={
        "quick_buyer": [["MAMAEARTH", "BILLING"], ["CETAPHIL", "BILLING"]],
        "explorer": [
            ["MAMAEARTH", "CETAPHIL", "NEUTROGENA", "PILGRIM"],
            ["GOODVIBES", "PILGRIM", "MAMAEARTH", "CETAPHIL"],
        ],
        "brand_loyal": [["MAMAEARTH", "MAMAEARTH"], ["CETAPHIL", "CETAPHIL", "NEUTROGENA"]],
        "window_shopper": [["D_AND_K", "DERMACOMP"], ["PILGRIM"]],
        "impulse_buyer": [["NEUTROGENA", "BILLING"], ["MAMAEARTH", "BILLING"]],
        "checkout_abandoner": [["MAMAEARTH", "CETAPHIL", "BILLING"], ["GOODVIBES", "BILLING"]],
        "multi_brand_comparison": [
            ["MAMAEARTH", "CETAPHIL", "NEUTROGENA"],
            ["PILGRIM", "GOODVIBES", "CETAPHIL"],
        ],
        "high_dwell_shopper": [
            ["MAMAEARTH", "CETAPHIL", "NEUTROGENA", "PILGRIM"],
            ["GOODVIBES", "NEUTROGENA", "CETAPHIL"],
        ],
    },
    staff_zone_sets=(
        ["MAMAEARTH", "CETAPHIL", "NEUTROGENA", "PILGRIM"],
        ["GOODVIBES", "PILGRIM", "MAMAEARTH", "CETAPHIL"],
        ["D_AND_K", "DERMACOMP", "PILGRIM", "GOODVIBES"],
        ["NEUTROGENA", "MAMAEARTH", "CETAPHIL", "PILGRIM", "GOODVIBES"],
    ),
    num_visitors=158,
    num_cam3_reentry_visitors=24,
    billing_visitors=118,
    purchase_billing_count=96,
    queue_abandon_count=28,
    neglected_pool=frozenset({"D_AND_K", "DERMACOMP"}),
    neglected_count=2,
    basket_mu_peak=6.85,
    basket_mu_off_peak=6.55,
    queue_peak_range=(6, 12),
    queue_off_peak_range=(2, 5),
)


SYNTHETIC_PROFILE_BY_STORE_KEY: dict[str, StoreSyntheticProfile] = {
    "store_1": STORE_1_PROFILE,
    "store_2": STORE_2_PROFILE,
}


def profile_for_store(store_key: str) -> StoreSyntheticProfile:
    try:
        return SYNTHETIC_PROFILE_BY_STORE_KEY[store_key]
    except KeyError as exc:
        raise ValueError(f"No synthetic profile for {store_key!r}") from exc
