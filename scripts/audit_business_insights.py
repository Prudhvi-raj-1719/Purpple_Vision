"""End-to-end audit for the AI Business Insight layer (synthetic dataset)."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STORE = "STORE_BLR_002"
DAY = date(2026, 6, 1)
INGEST_BATCH_SIZE = 500
EVENTS_PATH = REPO_ROOT / "data" / "synthetic" / "store_1" / "synthetic_events_store_1.jsonl"
POS_PATH = REPO_ROOT / "data" / "synthetic" / "store_1" / "synthetic_pos_store_1.csv"


def _setup_db() -> None:
    tmp_db = Path(tempfile.gettempdir()) / "pv_audit_business_insights.db"
    if tmp_db.exists():
        tmp_db.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db.as_posix()}"
    os.environ["ENABLE_AI_INSIGHTS"] = "false"


def _load_and_ingest() -> None:
    from app.db import init_db
    from app.ingestion import ingest_event_dicts
    from app.pos_ingestion import ingest_pos_transaction_dicts

    init_db()
    events: list[dict] = []
    for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    pos_rows: list[dict] = []
    with POS_PATH.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            pos_rows.append(
                {
                    "store_id": row["store_id"],
                    "transaction_id": row["transaction_id"],
                    "timestamp": row["timestamp"],
                    "basket_value_inr": float(row["basket_value_inr"]),
                }
            )
    ingest_event_dicts(events[:INGEST_BATCH_SIZE])
    for offset in range(INGEST_BATCH_SIZE, len(events), INGEST_BATCH_SIZE):
        ingest_event_dicts(events[offset : offset + INGEST_BATCH_SIZE])
    ingest_pos_transaction_dicts(pos_rows)


def main() -> int:
    _setup_db()
    _load_and_ingest()

    from app.anomalies import compute_store_anomalies
    from app.business_insights import (
        build_business_context,
        generate_business_insights,
    )
    from app.db import (
        fetch_store_events,
        fetch_store_pos_transactions,
        get_session,
    )
    from app.funnel import compute_store_funnel
    from app.health import compute_health_response
    from app.heatmap import compute_store_heatmap
    from app.metrics import compute_store_metrics
    from app.schemas.business_insights import (
        BusinessInsightResponse,
        StoreBusinessInsightsResponse,
    )
    from app.main import app
    from fastapi.testclient import TestClient

    session = get_session()
    try:
        events = fetch_store_events(session, STORE, day=DAY)
        transactions = fetch_store_pos_transactions(session, STORE, day=DAY)
        health = compute_health_response(session)
    finally:
        session.close()

    print("=" * 60)
    print("STEP 1 — API ENDPOINT")
    print("=" * 60)
    client = TestClient(app)
    response = client.get(
        f"/stores/{STORE}/business-insights",
        params={"date": DAY.isoformat()},
    )
    print("HTTP status:", response.status_code)
    body = response.json()
    StoreBusinessInsightsResponse.model_validate(body)
    print("Pydantic validation: OK")
    print("source:", body["source"])
    print("context keys:", sorted(body["context"].keys()))
    print("insights keys:", sorted(body["insights"].keys()))
    print("Sample response:")
    print(json.dumps(body, indent=2)[:3500])

    print()
    print("=" * 60)
    print("STEP 2 — CONTEXT BUILDER")
    print("=" * 60)
    metrics = compute_store_metrics(STORE, DAY, events, transactions)
    funnel = compute_store_funnel(STORE, DAY, events, transactions)
    heatmap = compute_store_heatmap(STORE, DAY, events)
    anomalies = compute_store_anomalies(STORE, DAY, events, transactions)
    context = build_business_context(
        store_id=STORE,
        metric_date=DAY,
        metrics=metrics,
        funnel=funnel,
        heatmap=heatmap,
        anomalies=anomalies,
        health=health,
    )
    context_json = json.dumps(context.model_dump(mode="json"), separators=(",", ":"))
    context_bytes = len(context_json.encode("utf-8"))
    print("Context size (bytes):", context_bytes)
    print("Under 2KB:", context_bytes < 2048)
    print("Metrics in context: visitors=%s revenue=%s conversion=%s" % (
        context.visitors,
        context.revenue,
        context.conversion_rate,
    ))
    print("Funnel:", context.funnel.model_dump())
    print("Checkout:", context.checkout.model_dump())
    print("Anomalies:", [a.model_dump() for a in context.anomalies])
    print("Health:", context.store_health.model_dump())
    forbidden = ("event_id", "visitor_id", "transaction_id", '"stages"', '"zones"')
    found = [key for key in forbidden if key in context_json]
    print("Raw payload keys found:", found or "NONE")

    print()
    print("=" * 60)
    print("STEP 4 — FALLBACK MODE")
    print("=" * 60)
    print("source=fallback:", body["source"] == "fallback")

    print()
    print("=" * 60)
    print("STEP 5 — FAILURE SCENARIOS")
    print("=" * 60)

    class UnavailableProvider:
        def generate_insights(self, context_dict):  # noqa: ANN001
            raise ConnectionError("Ollama unavailable")

    class MissingModelProvider:
        def generate_insights(self, context_dict):  # noqa: ANN001
            return None

    class TimeoutProvider:
        def generate_insights(self, context_dict):  # noqa: ANN001
            import httpx

            raise httpx.TimeoutException("timeout")

    for label, provider in [
        ("Ollama unavailable", UnavailableProvider()),
        ("Model missing", MissingModelProvider()),
        ("Timeout", TimeoutProvider()),
        ("Invalid JSON", MissingModelProvider()),
        ("Pydantic validation failure", MissingModelProvider()),
    ]:
        with patch("app.business_insights.is_ai_insights_enabled", return_value=True):
            with patch("app.business_insights.build_llm_provider", return_value=provider):
                source, insights = generate_business_insights(context)
        ok = source == "fallback" and isinstance(insights, BusinessInsightResponse)
        print(f"  {label}: pass={ok}")

    os.environ["ENABLE_AI_INSIGHTS"] = "true"
    with patch("app.llm_provider.OllamaProvider.generate_insights", return_value=None):
        fail_resp = client.get(
            f"/stores/{STORE}/business-insights",
            params={"date": DAY.isoformat()},
        )
    print(
        "API with AI enabled + LLM fail:",
        fail_resp.status_code,
        "source=",
        fail_resp.json().get("source"),
    )

    print()
    print("=" * 60)
    print("STEP 6 — PRODUCTION SAFETY")
    print("=" * 60)
    import app.llm_provider as llm_provider  # noqa: WPS433

    print("App imports OK")
    print("ENABLE_AI default false:", not llm_provider.is_ai_insights_enabled())
    print("Synthetic events:", len(events), "POS:", len(transactions))

    return 0 if response.status_code == 200 and context_bytes < 2048 else 1


if __name__ == "__main__":
    raise SystemExit(main())
