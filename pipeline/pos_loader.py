"""Load Brigade raw POS CSV, aggregate to invoice level, export NOTEBK-compatible JSON."""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.config import (
    AGGREGATED_TRANSACTIONS_CSV,
    AGGREGATED_TRANSACTIONS_JSON,
    AGGREGATED_POS_DIR,
    BRIGADE_POS_CSV_PATH,
    BRIGADE_POS_STORE_CODE,
    DEFAULT_STORE_ID,
    PURPPLE_POS_CSV,
)

logger = logging.getLogger(__name__)

REQUIRED_BRIGADE_COLUMNS = (
    "order_id",
    "invoice_number",
    "order_date",
    "order_time",
    "customer_number",
    "salesperson_name",
    "product_name",
    "brand_name",
    "dep_name",
    "qty",
    "total_amount",
)


@dataclass
class AggregationSummary:
    """Validation metrics from a Brigade POS aggregation run."""

    source_csv: Path
    line_items: int = 0
    invoices: int = 0
    total_revenue_inr: float = 0.0
    average_basket_inr: float = 0.0
    highest_invoice_inr: float = 0.0
    datetime_parse_failures: int = 0
    output_json: Path | None = None
    output_csv: Path | None = None
    purpple_csv: Path | None = None
    purpple_compatible_rows: int = 0
    purpple_validation_errors: list[str] = field(default_factory=list)


def load_brigade_pos_lines(path: Path | None = None) -> pd.DataFrame:
    """Load the Brigade raw line-item POS export."""
    csv_path = path or BRIGADE_POS_CSV_PATH
    if not csv_path.is_file():
        raise FileNotFoundError(f"Brigade POS CSV not found: {csv_path}")

    df = pd.read_csv(csv_path, low_memory=False)
    missing = [col for col in REQUIRED_BRIGADE_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Brigade POS CSV missing columns: {missing}")
    return df


def build_transaction_datetime(df: pd.DataFrame) -> pd.Series:
    """Combine order_date + order_time into a parsed datetime series."""
    combined = (
        df["order_date"].astype(str).str.strip()
        + " "
        + df["order_time"].astype(str).str.strip()
    )
    return pd.to_datetime(combined, format="%d-%m-%Y %H:%M:%S", errors="coerce")


def unique_sorted(values: pd.Series) -> list[str]:
    """Return deduplicated, sorted string values from a series."""
    cleaned = (
        values.dropna()
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    return sorted(cleaned)


def aggregate_invoices(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate line items to one row per invoice_number (NOTEBK semantics)."""
    work = df.copy()
    work["transaction_datetime"] = build_transaction_datetime(work)

    rows: list[dict[str, Any]] = []
    for invoice_number, group in work.groupby("invoice_number", sort=True):
        rows.append(
            {
                "invoice_number": invoice_number,
                "order_id": int(group["order_id"].iloc[0]),
                "transaction_datetime": group["transaction_datetime"].iloc[0],
                "customer_number": int(group["customer_number"].iloc[0]),
                "salesperson_name": str(group["salesperson_name"].iloc[0]).strip(),
                "product_names": unique_sorted(group["product_name"]),
                "brand_names": unique_sorted(group["brand_name"]),
                "categories": unique_sorted(group["dep_name"]),
                "total_quantity": int(group["qty"].sum()),
                "total_amount": round(float(group["total_amount"].sum()), 2),
            }
        )

    aggregated = pd.DataFrame(rows)
    aggregated["transaction_datetime"] = pd.to_datetime(aggregated["transaction_datetime"])
    aggregated = aggregated.sort_values("transaction_datetime").reset_index(drop=True)
    return aggregated


def aggregated_to_json_records(aggregated: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert aggregated DataFrame to NOTEBK-compatible JSON-serializable records."""
    records: list[dict[str, Any]] = []
    for row in aggregated.to_dict(orient="records"):
        ts = row["transaction_datetime"]
        row["transaction_datetime"] = (
            ts.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
        )
        records.append(row)
    return records


def aggregated_to_csv_export(aggregated: pd.DataFrame) -> pd.DataFrame:
    """Prepare aggregated data for CSV export (list columns JSON-encoded)."""
    export = aggregated.copy()
    export["transaction_datetime"] = export["transaction_datetime"].dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    for col in ("product_names", "brand_names", "categories"):
        export[col] = export[col].apply(
            lambda values: json.dumps(values, ensure_ascii=False)
        )
    return export


def brigade_invoice_to_transaction_id(invoice_number: str) -> str:
    """Map Brigade invoice_number to Purpple transaction_id (TXN_* pattern)."""
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", str(invoice_number).strip())
    return f"TXN_{sanitized}"


def aggregated_record_to_purpple_dict(
    record: dict[str, Any],
    *,
    store_id: str = DEFAULT_STORE_ID,
) -> dict[str, Any]:
    """Map one aggregated invoice record to a Purpple PosTransaction-compatible dict."""
    raw_dt = record["transaction_datetime"]
    if isinstance(raw_dt, str):
        parsed = datetime.strptime(raw_dt.strip(), "%Y-%m-%d %H:%M:%S")
    else:
        parsed = pd.Timestamp(raw_dt).to_pydatetime()
    timestamp = parsed.replace(tzinfo=timezone.utc)

    return {
        "store_id": store_id,
        "transaction_id": brigade_invoice_to_transaction_id(record["invoice_number"]),
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "basket_value_inr": float(record["total_amount"]),
    }


def aggregated_records_to_purpple_dicts(
    records: list[dict[str, Any]],
    *,
    store_id: str = DEFAULT_STORE_ID,
) -> list[dict[str, Any]]:
    """Convert aggregated invoice records to Purpple ingest/seed payloads."""
    return [
        aggregated_record_to_purpple_dict(record, store_id=store_id)
        for record in records
    ]


def write_purpple_pos_csv(
    records: list[dict[str, Any]],
    output_path: Path | None = None,
) -> Path:
    """Write Purpple-schema CSV for scripts/seed_from_sample.py."""
    out = output_path or PURPPLE_POS_CSV
    out.parent.mkdir(parents=True, exist_ok=True)
    purpple_rows = aggregated_records_to_purpple_dicts(records)

    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["store_id", "transaction_id", "timestamp", "basket_value_inr"],
        )
        writer.writeheader()
        for row in purpple_rows:
            writer.writerow(row)
    return out


def save_aggregated_outputs(
    aggregated: pd.DataFrame,
    *,
    json_path: Path | None = None,
    csv_path: Path | None = None,
) -> tuple[Path, Path, list[dict[str, Any]]]:
    """Write aggregated_transactions.json and .csv; return paths and JSON records."""
    AGGREGATED_POS_DIR.mkdir(parents=True, exist_ok=True)
    json_out = json_path or AGGREGATED_TRANSACTIONS_JSON
    csv_out = csv_path or AGGREGATED_TRANSACTIONS_CSV

    json_records = aggregated_to_json_records(aggregated)
    json_out.write_text(
        json.dumps(json_records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    csv_export = aggregated_to_csv_export(aggregated)
    csv_export.to_csv(csv_out, index=False)

    return json_out, csv_out, json_records


def validate_purpple_compatibility(
    records: list[dict[str, Any]],
    *,
    store_id: str = DEFAULT_STORE_ID,
) -> tuple[int, list[str]]:
    """Validate aggregated records map to PosTransaction without import cycles."""
    from app.models import PosTransaction

    errors: list[str] = []
    valid = 0
    for record in records:
        try:
            payload = aggregated_record_to_purpple_dict(record, store_id=store_id)
            PosTransaction.model_validate(payload)
            valid += 1
        except Exception as exc:
            invoice = record.get("invoice_number", "?")
            errors.append(f"{invoice}: {exc}")
    return valid, errors


def load_and_aggregate_brigade_pos(
    source_csv: Path | None = None,
    *,
    write_outputs: bool = True,
    write_purpple_csv: bool = True,
) -> tuple[list[dict[str, Any]], AggregationSummary]:
    """
    Load Brigade CSV, aggregate to invoices, optionally write outputs.

    Returns (json_records, summary).
    """
    csv_path = source_csv or BRIGADE_POS_CSV_PATH
    line_items = load_brigade_pos_lines(csv_path)
    aggregated = aggregate_invoices(line_items)

    datetime_failures = int(aggregated["transaction_datetime"].isna().sum())
    json_records: list[dict[str, Any]] = aggregated_to_json_records(aggregated)

    summary = AggregationSummary(
        source_csv=csv_path,
        line_items=len(line_items),
        invoices=len(aggregated),
        total_revenue_inr=round(float(aggregated["total_amount"].sum()), 2),
        average_basket_inr=round(float(aggregated["total_amount"].mean()), 2),
        highest_invoice_inr=round(float(aggregated["total_amount"].max()), 2),
        datetime_parse_failures=datetime_failures,
    )

    if write_outputs:
        json_path, csv_path_out, json_records = save_aggregated_outputs(aggregated)
        summary.output_json = json_path
        summary.output_csv = csv_path_out

    if write_purpple_csv:
        summary.purpple_csv = write_purpple_pos_csv(json_records)

    valid, errors = validate_purpple_compatibility(json_records)
    summary.purpple_compatible_rows = valid
    summary.purpple_validation_errors = errors

    logger.info(
        "Brigade POS aggregated: %s line items -> %s invoices, revenue INR %s",
        summary.line_items,
        summary.invoices,
        summary.total_revenue_inr,
    )
    return json_records, summary


def load_aggregated_transactions(path: Path | None = None) -> list[dict[str, Any]]:
    """Load previously generated aggregated_transactions.json."""
    json_path = path or AGGREGATED_TRANSACTIONS_JSON
    if not json_path.is_file():
        raise FileNotFoundError(f"Aggregated transactions not found: {json_path}")
    with json_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array in {json_path}")
    return data


def run_cli(source_csv: Path | None = None) -> AggregationSummary:
    """CLI entry: aggregate Brigade POS and write outputs."""
    _, summary = load_and_aggregate_brigade_pos(source_csv, write_outputs=True)
    print(f"Source CSV       : {summary.source_csv}")
    print(f"Line items       : {summary.line_items}")
    print(f"Invoices         : {summary.invoices}")
    print(f"Total revenue    : INR {summary.total_revenue_inr:,.2f}")
    print(f"Avg basket       : INR {summary.average_basket_inr:,.2f}")
    print(f"Highest invoice  : INR {summary.highest_invoice_inr:,.2f}")
    if summary.output_json:
        print(f"JSON output      : {summary.output_json}")
    if summary.output_csv:
        print(f"CSV output       : {summary.output_csv}")
    if summary.purpple_csv:
        print(f"Purpple CSV      : {summary.purpple_csv}")
    print(
        f"Purpple-compatible: {summary.purpple_compatible_rows}/{summary.invoices} "
        f"(store={DEFAULT_STORE_ID}, brigade_store={BRIGADE_POS_STORE_CODE})"
    )
    if summary.purpple_validation_errors:
        print("Validation errors:")
        for err in summary.purpple_validation_errors[:10]:
            print(f"  - {err}")
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run_cli()
