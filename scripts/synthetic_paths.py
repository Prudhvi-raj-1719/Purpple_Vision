"""Paths and constants for per-store synthetic validation fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_ROOT = REPO_ROOT / "data" / "synthetic"
DATABASES_DIR = REPO_ROOT / "data" / "databases"

SUPPORTED_SYNTHETIC_STORES = ("store_1", "store_2")


@dataclass(frozen=True)
class SyntheticStoreSpec:
    store_key: str
    store_id: str
    metric_date: date
    seed: int
    events_path: Path
    pos_path: Path
    validation_db: Path
    report_paths: tuple[Path, ...]

    @property
    def events_filename(self) -> str:
        return self.events_path.name

    @property
    def pos_filename(self) -> str:
        return self.pos_path.name


def synthetic_store_spec(store_key: str) -> SyntheticStoreSpec:
    if store_key not in SUPPORTED_SYNTHETIC_STORES:
        supported = ", ".join(SUPPORTED_SYNTHETIC_STORES)
        raise ValueError(f"Unsupported synthetic store {store_key!r}; use: {supported}")

    from pipeline.store_config import get_store_config

    cfg = get_store_config(store_key)
    store_dir = SYNTHETIC_ROOT / store_key
    report_name = f"demo_validation_report_{store_key}.md"
    return SyntheticStoreSpec(
        store_key=store_key,
        store_id=cfg.store_id,
        metric_date=date(2026, 6, 1) if store_key == "store_1" else date(2026, 4, 10),
        seed=20260601 if store_key == "store_1" else 20260410,
        events_path=store_dir / f"synthetic_events_{store_key}.jsonl",
        pos_path=store_dir / f"synthetic_pos_{store_key}.csv",
        validation_db=DATABASES_DIR / f"{store_key}_validation.db",
        report_paths=(
            REPO_ROOT / report_name,
            REPO_ROOT / "docs" / "reports" / report_name,
        ),
    )


def all_synthetic_store_specs() -> tuple[SyntheticStoreSpec, ...]:
    return tuple(synthetic_store_spec(key) for key in SUPPORTED_SYNTHETIC_STORES)
