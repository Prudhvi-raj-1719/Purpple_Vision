"""
Re-ID tuning from ``stores/*/cam3.json`` → ``reid`` block only.

``activate_reid_settings()`` syncs module-level names used by ``reid_manager`` /
``osnet_reid`` when those modules are constructed without explicit overrides.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.store_config import ReidConfig

# Used only when ``cam3.json`` omits ``osnet_market1501_url`` (ReID disabled stores).
_FALLBACK_OSNET_URL = (
    "https://drive.google.com/uc?id=1vduhq5DpN2q1g4fYEZfPI17MJeh9qyrA"
)

# Module-level mirrors (set by ``activate_reid_settings``; not defaults from env).
REID_DEBUG: bool = False
REID_MODEL_NAME: str = "osnet_x1_0"
REID_DEVICE: str = "cpu"
REID_COSINE_THRESHOLD: float = 0.0
REID_EXIT_CACHE_SECONDS: float = 0.0
REID_MIN_DWELL_AFTER_EXIT_SECONDS: float = 0.0
REID_MIN_CROP_AREA: int = 0
REID_TRACK_EMBED_HISTORY: int = 0
REID_SESSION_MATCH_ENABLED: bool = False
REID_SESSION_MATCH_THRESHOLD: float = 0.0
REID_SESSION_MARGIN_THRESHOLD: float = 0.0
REID_AREA_RATIO_MIN: float = 0.0
REID_AREA_RATIO_MAX: float = 0.0
REID_SESSION_MAX_AGE_SECONDS: float = 0.0
REID_NEAR_DOORWAY_Y_TOLERANCE: float = 0.0
REID_FRAGMENT_MATCH_THRESHOLD: float = 0.0
REID_FRAGMENT_MARGIN_THRESHOLD: float = 0.0
OSNET_X1_0_MARKET1501_URL: str = _FALLBACK_OSNET_URL


@dataclass(frozen=True)
class ReidSettings:
    """Hydrated Re-ID block from active store ``cam3.json``."""

    enabled: bool
    heuristic_fallback: bool
    debug: bool
    model_name: str
    device: str
    cosine_threshold: float
    exit_cache_seconds: float
    min_dwell_after_exit_seconds: float
    min_crop_area: int
    track_embed_history: int
    session_match_enabled: bool
    session_match_threshold: float
    session_margin_threshold: float
    area_ratio_min: float
    area_ratio_max: float
    session_max_age_seconds: float
    near_doorway_y_tolerance: float
    fragment_match_threshold: float
    fragment_margin_threshold: float
    osnet_market1501_url: str


_active: ReidSettings | None = None


def reid_settings_from_config(reid: ReidConfig) -> ReidSettings:
    """Build settings from ``store.cam3.reid`` (no env overrides)."""
    url = reid.osnet_market1501_url
    if reid.enabled and not url:
        raise ValueError(
            "cam3.json reid.enabled is true but osnet_market1501_url is missing"
        )
    return ReidSettings(
        enabled=reid.enabled,
        heuristic_fallback=reid.heuristic_fallback,
        debug=reid.debug,
        model_name=reid.model_name,
        device=reid.device,
        cosine_threshold=reid.cosine_threshold,
        exit_cache_seconds=reid.exit_cache_seconds,
        min_dwell_after_exit_seconds=reid.min_dwell_after_exit_seconds,
        min_crop_area=reid.min_crop_area,
        track_embed_history=reid.track_embed_history,
        session_match_enabled=reid.session_match_enabled,
        session_match_threshold=reid.session_match_threshold,
        session_margin_threshold=reid.session_margin_threshold,
        area_ratio_min=reid.area_ratio_min,
        area_ratio_max=reid.area_ratio_max,
        session_max_age_seconds=reid.session_max_age_seconds,
        near_doorway_y_tolerance=reid.near_doorway_y_tolerance,
        fragment_match_threshold=reid.fragment_match_threshold,
        fragment_margin_threshold=reid.fragment_margin_threshold,
        osnet_market1501_url=url or _FALLBACK_OSNET_URL,
    )


def activate_reid_settings(settings: ReidSettings) -> None:
    """Publish active store Re-ID values for ``reid_manager`` / ``osnet_reid``."""
    global _active
    global REID_DEBUG, REID_MODEL_NAME, REID_DEVICE
    global REID_COSINE_THRESHOLD, REID_EXIT_CACHE_SECONDS
    global REID_MIN_DWELL_AFTER_EXIT_SECONDS, REID_MIN_CROP_AREA
    global REID_TRACK_EMBED_HISTORY, REID_SESSION_MATCH_ENABLED
    global REID_SESSION_MATCH_THRESHOLD, REID_SESSION_MARGIN_THRESHOLD
    global REID_AREA_RATIO_MIN, REID_AREA_RATIO_MAX, REID_SESSION_MAX_AGE_SECONDS
    global REID_NEAR_DOORWAY_Y_TOLERANCE, REID_FRAGMENT_MATCH_THRESHOLD
    global REID_FRAGMENT_MARGIN_THRESHOLD, OSNET_X1_0_MARKET1501_URL

    _active = settings
    REID_DEBUG = settings.debug
    REID_MODEL_NAME = settings.model_name
    REID_DEVICE = settings.device
    REID_COSINE_THRESHOLD = settings.cosine_threshold
    REID_EXIT_CACHE_SECONDS = settings.exit_cache_seconds
    REID_MIN_DWELL_AFTER_EXIT_SECONDS = settings.min_dwell_after_exit_seconds
    REID_MIN_CROP_AREA = settings.min_crop_area
    REID_TRACK_EMBED_HISTORY = settings.track_embed_history
    REID_SESSION_MATCH_ENABLED = settings.session_match_enabled
    REID_SESSION_MATCH_THRESHOLD = settings.session_match_threshold
    REID_SESSION_MARGIN_THRESHOLD = settings.session_margin_threshold
    REID_AREA_RATIO_MIN = settings.area_ratio_min
    REID_AREA_RATIO_MAX = settings.area_ratio_max
    REID_SESSION_MAX_AGE_SECONDS = settings.session_max_age_seconds
    REID_NEAR_DOORWAY_Y_TOLERANCE = settings.near_doorway_y_tolerance
    REID_FRAGMENT_MATCH_THRESHOLD = settings.fragment_match_threshold
    REID_FRAGMENT_MARGIN_THRESHOLD = settings.fragment_margin_threshold
    OSNET_X1_0_MARKET1501_URL = settings.osnet_market1501_url


def get_active_reid_settings() -> ReidSettings:
    if _active is None:
        raise RuntimeError(
            "Re-ID settings not activated; call activate_reid_settings(store.cam3.reid) first"
        )
    return _active
