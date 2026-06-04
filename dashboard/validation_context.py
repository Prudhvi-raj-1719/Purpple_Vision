"""Per-store dashboard database binding and date discovery for the Streamlit app."""

from __future__ import annotations

import importlib
import os
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(REPO_ROOT))

from scripts.demo_cleanup import force_database_url, intelligence_database_path  # noqa: E402
from scripts.synthetic_paths import synthetic_store_spec  # noqa: E402

_ACTIVE_STORE_KEY: str | None = None

STORE1_REAL_KEY = "store1_real"


@dataclass(frozen=True)
class DashboardStoreOption:
    """One dashboard store selector entry (synthetic validation or CCTV intelligence)."""

    label: str
    store_key: str
    store_id: str
    database_path: Path
    default_metric_date: date
    is_intelligence_db: bool = False

    @property
    def validation_db(self) -> Path:
        """Backward-compatible alias for ``database_path``."""
        return self.database_path


def dashboard_store_options() -> tuple[DashboardStoreOption, ...]:
    """Store 1 / Store 2 validation fixtures plus store_1 CCTV intelligence DB."""
    options: list[DashboardStoreOption] = []
    for store_key in ("store_1", "store_2"):
        spec = synthetic_store_spec(store_key)
        options.append(
            DashboardStoreOption(
                label="Store 1" if store_key == "store_1" else "Store 2",
                store_key=store_key,
                store_id=spec.store_id,
                database_path=spec.validation_db,
                default_metric_date=spec.metric_date,
            )
        )

    from pipeline.store_config import get_store_config

    cfg = get_store_config("store_1")
    options.append(
        DashboardStoreOption(
            label="store1_real",
            store_key=STORE1_REAL_KEY,
            store_id=cfg.store_id,
            database_path=intelligence_database_path(cfg),
            default_metric_date=date.fromisoformat(cfg.pos_sale_date),
            is_intelligence_db=True,
        )
    )
    return tuple(options)


def option_for_key(store_key: str) -> DashboardStoreOption:
    for option in dashboard_store_options():
        if option.store_key == store_key:
            return option
    raise ValueError(f"Unknown dashboard store key: {store_key!r}")


def missing_database_hint(option: DashboardStoreOption) -> str:
    if option.is_intelligence_db:
        return (
            "Run: $env:PURPPLE_STORE = \"store_1\"; python scripts/demo_runner.py"
        )
    return f"python scripts/demo_validation_run.py --store {option.store_key}"


def list_event_dates_from_db(db_path: Path, store_id: str) -> list[date]:
    """
    Distinct UTC calendar days present in the events table for a store.

    Read-only SQLite access (no API / ingestion changes).
    """
    if not db_path.is_file():
        return []

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT date(timestamp) AS day
            FROM events
            WHERE store_id = ?
            ORDER BY day
            """,
            (store_id,),
        ).fetchall()
    finally:
        conn.close()

    dates: list[date] = []
    for (day_str,) in rows:
        if day_str:
            dates.append(date.fromisoformat(str(day_str)))
    return dates


def bind_dashboard_database(store_key: str) -> DashboardStoreOption:
    """
    Point the application ORM at the selected dashboard SQLite file.

    Rebinds only when the store key changes (same pattern as demo_validation_run).
    """
    global _ACTIVE_STORE_KEY

    option = option_for_key(store_key)
    if _ACTIVE_STORE_KEY == store_key and option.database_path.is_file():
        return option

    if not option.database_path.is_file():
        raise FileNotFoundError(
            f"Database not found for {option.label}: {option.database_path}. "
            f"Run: {missing_database_hint(option)}"
        )

    force_database_url(option.database_path)
    import app.db as db_module

    importlib.reload(db_module)
    _ACTIVE_STORE_KEY = store_key
    return option


def bind_validation_database(store_key: str) -> DashboardStoreOption:
    """Alias for :func:`bind_dashboard_database`."""
    return bind_dashboard_database(store_key)


def use_api_client() -> bool:
    """When true, dashboard loads analytics via HTTP; otherwise uses bound validation DB."""
    return os.getenv("DASHBOARD_USE_API", "").strip().lower() in {"1", "true", "yes"}


def api_base_url_for_store(store_key: str) -> str:
    """
    Optional per-store API base URL (e.g. two uvicorn instances on different ports).

    Falls back to API_BASE_URL when STORE_{N}_API_BASE_URL is unset.
    """
    if store_key == STORE1_REAL_KEY:
        return os.getenv(
            "STORE_1_API_BASE_URL",
            os.getenv("API_BASE_URL", "http://localhost:8000"),
        ).rstrip("/")
    env_key = f"STORE_{store_key[-1]}_API_BASE_URL"
    return os.getenv(env_key, os.getenv("API_BASE_URL", "http://localhost:8000")).rstrip("/")


def load_analytics_from_validation_db(
    store_key: str,
    store_id: str,
    metric_date: date,
) -> dict[str, Any]:
    """
    Load the same payloads the REST API returns, using the bound dashboard database.

    Does not modify analytics logic — calls existing compute_* functions.
    """
    bind_dashboard_database(store_key)

    from app.anomalies import compute_store_anomalies
    from app.business_insights import compute_store_business_insights
    from app.db import (
        fetch_store_events,
        fetch_store_pos_transactions,
        get_session,
        is_database_available,
    )
    from app.funnel import compute_store_funnel
    from app.health import compute_health_response
    from app.heatmap import compute_store_heatmap
    from app.metrics import compute_store_metrics
    from app.staff_analysis import get_staff_analysis

    if not is_database_available():
        raise RuntimeError("Dashboard database is not available")

    with get_session() as session:
        events = fetch_store_events(session, store_id, day=metric_date)
        transactions = fetch_store_pos_transactions(
            session, store_id, day=metric_date
        )
        health = compute_health_response(session)
        metrics = compute_store_metrics(store_id, metric_date, events, transactions)
        funnel = compute_store_funnel(store_id, metric_date, events, transactions)
        heatmap = compute_store_heatmap(store_id, metric_date, events)
        anomalies = compute_store_anomalies(
            store_id, metric_date, events, transactions
        )
        business_insights = compute_store_business_insights(
            store_id,
            metric_date,
            events,
            transactions,
            health=health,
            db=session,
        )
        staff_analysis = get_staff_analysis(
            store_id=store_id,
            date_param=metric_date.isoformat(),
            db=session,
        )

    return {
        "health": health.model_dump(mode="json"),
        "metrics": metrics.model_dump(mode="json"),
        "funnel": funnel.model_dump(mode="json"),
        "heatmap": heatmap.model_dump(mode="json"),
        "anomalies": anomalies.model_dump(mode="json"),
        "business_insights": business_insights.model_dump(mode="json"),
        "staff_analysis": staff_analysis.model_dump(mode="json"),
    }
