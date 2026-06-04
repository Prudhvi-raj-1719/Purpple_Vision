"""Per-store intelligence DB resolution and CCTV delete guards."""

from __future__ import annotations

import pytest

from pipeline.store_config import get_store_config
from scripts.demo_cleanup import (
    STORE_1_VALIDATION_DB,
    STORE_2_VALIDATION_DB,
    STORE_INTELLIGENCE_DB,
    assert_deletable_for_cctv_run,
    intelligence_database_path,
)


def test_intelligence_path_from_store_json() -> None:
    cfg1 = get_store_config("store_1")
    cfg2 = get_store_config("store_2")
    assert intelligence_database_path(cfg1).name == "store_1_intelligence.db"
    assert intelligence_database_path(cfg2).name == "store_2_intelligence.db"


def test_cctv_run_allows_active_store_intelligence_only() -> None:
    active = intelligence_database_path(get_store_config("store_1"))
    assert_deletable_for_cctv_run(active, active_store_key="store_1")


def test_cctv_run_refuses_validation_db() -> None:
    with pytest.raises(RuntimeError, match="validation"):
        assert_deletable_for_cctv_run(
            STORE_1_VALIDATION_DB,
            active_store_key="store_1",
        )


def test_cctv_run_refuses_other_store_intelligence() -> None:
    other = intelligence_database_path(get_store_config("store_2"))
    with pytest.raises(RuntimeError, match="may only reset"):
        assert_deletable_for_cctv_run(other, active_store_key="store_1")


def test_cctv_run_refuses_production_db() -> None:
    with pytest.raises(RuntimeError, match="store_intelligence"):
        assert_deletable_for_cctv_run(
            STORE_INTELLIGENCE_DB,
            active_store_key="store_1",
        )


def test_cctv_run_refuses_demo_product_legacy() -> None:
    from scripts.demo_cleanup import DEMO_PRODUCT_DB

    with pytest.raises(RuntimeError):
        assert_deletable_for_cctv_run(DEMO_PRODUCT_DB, active_store_key="store_1")
