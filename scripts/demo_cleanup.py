"""
Shared cleanup and SQLite isolation helpers for demo workflows.

Used by scripts/demo_runner.py and scripts/demo_validation_run.py only.
Does not delete or modify store_intelligence.db.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url

if TYPE_CHECKING:
    from pipeline.store_config import StoreConfig

REPO_ROOT = Path(__file__).resolve().parents[1]

# Legacy shared demo DB (rollback only; demo_runner uses per-store intelligence DBs).
DEMO_PRODUCT_DB = REPO_ROOT / "data" / "databases" / "demo_product.db"
DEMO_VALIDATION_DB = REPO_ROOT / "data" / "databases" / "demo_validation.db"
STORE_1_VALIDATION_DB = REPO_ROOT / "data" / "databases" / "store_1_validation.db"
STORE_2_VALIDATION_DB = REPO_ROOT / "data" / "databases" / "store_2_validation.db"
STORE_INTELLIGENCE_DB = REPO_ROOT / "data" / "databases" / "store_intelligence.db"

DEMO_RUN_REPORT_PATHS = (
    REPO_ROOT / "demo_run_report.md",
    REPO_ROOT / "docs" / "reports" / "demo_run_report.md",
)
DEMO_VALIDATION_REPORT_PATHS = (
    REPO_ROOT / "demo_validation_report_store_1.md",
    REPO_ROOT / "docs" / "reports" / "demo_validation_report_store_1.md",
    REPO_ROOT / "demo_validation_report_store_2.md",
    REPO_ROOT / "docs" / "reports" / "demo_validation_report_store_2.md",
)

AGGREGATED_POS_DIR = REPO_ROOT / "data" / "outputs" / "pos"
AGGREGATED_TRANSACTIONS_JSON = AGGREGATED_POS_DIR / "aggregated_transactions.json"
AGGREGATED_TRANSACTIONS_CSV = AGGREGATED_POS_DIR / "aggregated_transactions.csv"
PURPPLE_POS_CSV = AGGREGATED_POS_DIR / "purpple_pos_transactions.csv"
PURCHASE_MATCHES_JSON = (
    REPO_ROOT / "data" / "outputs" / "purchase_matching" / "purchase_matches.json"
)
PIPELINE_DEMO_DIR = REPO_ROOT / "data" / "outputs" / "pipeline" / "pipeline_demo"


def sqlite_sidecar_paths(db_path: Path) -> tuple[Path, ...]:
    """Main SQLite file plus -wal / -shm sidecars."""
    return (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm"))


def force_database_url(db_path: Path) -> str:
    """Set DATABASE_URL to an absolute SQLite file path (overrides shell/.env)."""
    url = f"sqlite:///{db_path.resolve().as_posix()}"
    os.environ["DATABASE_URL"] = url
    return url


def intelligence_database_path(cfg: StoreConfig) -> Path:
    """Resolve per-store CCTV intelligence SQLite path from ``store.json``."""
    if cfg.database_path is None:
        raise ValueError(
            f"{cfg.store_key}: database_path is missing in stores/{cfg.store_key}/store.json"
        )
    return cfg.database_path.resolve()


def assert_deletable_for_cctv_run(db_path: Path, *, active_store_key: str) -> None:
    """
    CCTV demo runs may reset only the active store's intelligence DB.

    Refuses production, validation DBs, the other store's intelligence file, and
    any path that does not match the active store configuration.
    """
    from pipeline.store_config import get_store_config

    resolved = db_path.resolve()
    if resolved == STORE_INTELLIGENCE_DB.resolve():
        raise RuntimeError(
            "Refusing to delete production database store_intelligence.db"
        )
    if resolved in (
        STORE_1_VALIDATION_DB.resolve(),
        STORE_2_VALIDATION_DB.resolve(),
        DEMO_VALIDATION_DB.resolve(),
    ):
        raise RuntimeError(
            "Refusing to delete validation database during CCTV demo run"
        )

    expected = intelligence_database_path(
        get_store_config(active_store_key)
    ).resolve()
    if resolved != expected:
        raise RuntimeError(
            f"Refusing to delete {resolved}; CCTV demo for {active_store_key!r} "
            f"may only reset {expected}"
        )


def delete_sqlite_database(db_path: Path) -> bool:
    """
    Remove a SQLite database file and WAL/SHM sidecars if present.

    Never touches store_intelligence.db. Synthetic validation uses this for
    validation DB resets; use ``delete_sqlite_database_for_cctv_run`` for CCTV demos.
    """
    resolved = db_path.resolve()
    if resolved == STORE_INTELLIGENCE_DB.resolve():
        raise RuntimeError(
            "Refusing to delete production database store_intelligence.db"
        )

    removed = False
    for path in sqlite_sidecar_paths(resolved):
        if path.is_file():
            path.unlink()
            removed = True
    return removed


def delete_sqlite_database_for_cctv_run(db_path: Path, *, active_store_key: str) -> bool:
    """Delete SQLite files for a CCTV demo after ``assert_deletable_for_cctv_run``."""
    assert_deletable_for_cctv_run(db_path, active_store_key=active_store_key)
    return delete_sqlite_database(db_path)


def resolve_engine_database_path(engine: Engine) -> Path:
    """Filesystem path for a file-based SQLite engine URL."""
    url = make_url(str(engine.url))
    if url.drivername != "sqlite" or not url.database:
        raise ValueError(f"Not a file-based SQLite engine: {engine.url}")

    db_path = Path(url.database)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    return db_path.resolve()


def assert_demo_database_path(
    engine: Engine,
    *,
    expected: Path,
    label: str,
) -> Path:
    """
    Ensure the active engine points at the intended demo DB, not store_intelligence.
    """
    actual = resolve_engine_database_path(engine)
    expected_resolved = expected.resolve()

    if actual == STORE_INTELLIGENCE_DB.resolve():
        raise RuntimeError(
            f"{label}: engine is bound to store_intelligence.db; "
            "refusing to run demo workflow against production data."
        )
    if actual != expected_resolved:
        raise RuntimeError(
            f"{label}: engine path {actual} != expected {expected_resolved}"
        )
    return actual


def clean_notbk_mirror_files(directory: Path) -> int:
    """Remove legacy *.notbk.jsonl mirror files from a pipeline output directory."""
    if not directory.is_dir():
        return 0
    removed = 0
    for path in directory.glob("*.notbk.jsonl"):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def clean_directory_files(directory: Path) -> bool:
    """Delete all files in a directory (not subdirectories). Returns True if any removed."""
    if not directory.is_dir():
        return False
    removed = False
    for path in directory.iterdir():
        if path.is_file():
            path.unlink()
            removed = True
    return removed


def delete_file_if_exists(path: Path) -> bool:
    if path.is_file():
        path.unlink()
        return True
    return False


def clean_report_files(paths: tuple[Path, ...]) -> None:
    """Remove prior report copies so the next write is a full overwrite."""
    for path in paths:
        delete_file_if_exists(path)
