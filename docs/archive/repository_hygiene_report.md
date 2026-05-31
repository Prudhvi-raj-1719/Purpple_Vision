# Repository Hygiene Report

**Date:** 2026-05-31  
**Scope:** Dependencies, scripts, pipeline, docs, root artifacts  
**Audit only — no files deleted or modified**

Goal: Clean hackathon submission repository for third-party reviewers.

---

## 1. Executive summary

| Category | Finding |
|----------|---------|
| **Critical hygiene issues** | Accidentally tracked SQLite WAL files; git push test file; large uncommitted work not yet in git |
| **Unused dependencies** | 4 packages in `requirements.txt` never imported |
| **Missing dependency pin** | `supervision` imported throughout pipeline but not listed |
| **Duplicate stubs** | Two identical bash skeleton scripts (`run_pipeline.sh`) |
| **One-time artifacts** | Screenshot script, meta cleanup report, generated `data/` outputs |
| **docs/archive/** | Correctly placed — keep as historical reference |

**Top actions before submit:** Remove `verification_push_test.txt` and tracked `*.db-wal`/`*.db-shm`; commit untracked pipeline/scripts/docs; trim unused requirements; pin `supervision`.

---

## 2. Dependency audit

### 2.1 `requirements.txt` — package-by-package

| Package | Imported / used? | Verdict |
|---------|------------------|---------|
| `fastapi` | `app/main.py`, tests | **KEEP** |
| `uvicorn[standard]` | Docker CMD, local run | **KEEP** |
| `pydantic` | `app/models.py`, everywhere | **KEEP** |
| `pydantic-settings` | **No imports** | **REMOVE** — never used; settings via `os.getenv` |
| `python-multipart` | **No `UploadFile` / forms** | **REMOVE** (optional) — not used; add back only if file upload added |
| `sqlalchemy` | `app/db.py` | **KEEP** |
| `httpx` | `dashboard/streamlit_app.py`, screenshot script | **KEEP** |
| `python-dotenv` | bridge, seed, streamlit env | **KEEP** |
| `structlog` | **No imports** — logging uses stdlib `logging` + `JsonLogFormatter` | **REMOVE** |
| `opencv-python-headless` | `pipeline/*` (`cv2`) | **KEEP** |
| `ultralytics` | `pipeline/detect.py`, `queue.py` | **KEEP** |
| `numpy` | pipeline + ultralytics | **KEEP** (explicit pin stabilizes 3.11) |
| `pillow` | ultralytics transitive | **KEEP** (explicit pin OK) |
| `lapx` | ByteTrack on Windows | **KEEP** |
| `pandas` | streamlit, pos_loader | **KEEP** |
| `streamlit` | dashboard | **KEEP** |
| `pytest` | test suite | **KEEP** in main *or* **MOVE** to dev (see §2.3) |
| `pytest-asyncio` | **No async tests**; `asyncio_mode=auto` unused | **REMOVE** or move to dev |
| `pytest-cov` | coverage runs | **MOVE** to `requirements-dev.txt` (optional) |

### 2.2 Used but not pinned (gap)

| Package | Used in | Recommendation |
|---------|---------|----------------|
| **`supervision`** | `dwell.py`, `entry_exit.py`, `queue.py`, `tracker.py`, `zones.py`, `detect.py` | **ADD** `supervision==0.28.0` (or compatible pin) |
| **`matplotlib`** | `scripts/capture_dashboard_screenshots.py` only | Do **not** add to runtime — archive script or move to dev |

### 2.3 Duplicate / overlap

| Issue | Detail | Recommendation |
|-------|--------|----------------|
| `numpy` + `pillow` | Also pulled by `ultralytics` | Explicit pins are **intentional** for 3.11 stability — not duplicates |
| `opencv-python` vs `opencv-python-headless` | Ultralytics may install `opencv-python` | **KEEP** headless pin; document force-reinstall (README already does) |
| Test tools in runtime requirements | pytest* in `requirements.txt` bloats Docker API image | **Optional split:** move pytest* to `requirements-dev.txt`; keep in main if evaluators run `pytest` without `-dev` |
| `requirements-dev.txt` | Only `ruff` beyond `-r requirements.txt` | **KEEP**; add `pytest-cov`, `matplotlib` if screenshot script kept in dev |

### 2.4 Dependency cleanup recommendations

```text
REMOVE from requirements.txt:
  - structlog
  - pydantic-settings
  - pytest-asyncio

CONSIDER REMOVING:
  - python-multipart (unused today)

ADD to requirements.txt:
  - supervision==0.28.0  (direct pipeline import)

OPTIONAL MOVE to requirements-dev.txt:
  - pytest, pytest-cov
  - matplotlib (if keeping screenshot script)
```

---

## 3. `requirements-dev.txt`

| Status | Recommendation |
|--------|----------------|
| `ruff==0.8.6` | **KEEP** — linter only |
| `-r requirements.txt` | **KEEP** pattern |

No duplicate packages beyond inheritance.

---

## 4. `pytest.ini`

| Setting | Assessment |
|---------|------------|
| `testpaths = tests` | **KEEP** |
| `asyncio_mode = auto` | **Obsolete** if `pytest-asyncio` removed — delete setting |
| `[coverage:run] source = app, pipeline` | Pipeline has **no tests** — `pipeline` in source inflates coverage denominator |
| `fail_under = 70` | OK for `app/` |

**Recommendation:** Remove `asyncio_mode` when dropping `pytest-asyncio`. Consider `source = app` only until `test_pipeline.py` exists.

---

## 5. Scripts audit

| Script | Purpose | Verdict | Rationale |
|--------|---------|---------|-----------|
| `scripts/run_pipeline_demo.py` | End-to-end CAM1/2/3/5 demo | **KEEP** | Primary pipeline orchestrator |
| `scripts/bridge_pipeline_to_product.py` | JSONL + POS → SQLite + validation report | **KEEP** | Core demo integration path |
| `scripts/seed_from_sample.py` | Challenge-format sample loader | **KEEP** | Documented evaluator path |
| `scripts/phase0_import_check.py` | Setup verification (`README`) | **KEEP** | Onboarding / CI smoke |
| `scripts/capture_dashboard_screenshots.py` | One-time PNG generator for validation | **ARCHIVE** → `docs/archive/scripts/` | Uses unpinned `matplotlib`; not part of product workflow |
| `scripts/run_pipeline.sh` | Phase 0 bash skeleton | **ARCHIVE** or **REMOVE** | Superseded by `run_pipeline_demo.py`; non-functional |

---

## 6. Pipeline audit

| File | Status | Verdict |
|------|--------|---------|
| `detect.py`, `tracker.py`, `zones.py` | Active CV core | **KEEP** |
| `dwell.py`, `entry_exit.py`, `queue.py` | Active processors | **KEEP** |
| `cam1_processor.py`, `cam2_processor.py` | Active | **KEEP** (currently **untracked in git**) |
| `config.py`, `event_adapter.py`, `emit.py` | Active | **KEEP** (untracked) |
| `pos_loader.py`, `purchase_matching.py` | Active offline tools | **KEEP** |
| `video_time.py`, `sink.py` | Active helpers | **KEEP** (untracked) |
| `staff.py` | Docstring stub | **KEEP** (placeholder; document as future) |
| `run.sh` | Duplicate Phase 0 skeleton | **ARCHIVE** or **REMOVE** | Same as `scripts/run_pipeline.sh` |
| `__init__.py` | Package marker | **KEEP** |

**Note:** Several pipeline files exist on disk but are **not yet committed** to git. Hygiene action is **commit**, not remove.

---

## 7. Dashboard audit

| File | Verdict | Rationale |
|------|---------|-----------|
| `dashboard/streamlit_app.py` | **KEEP** | Active UI |
| `dashboard/__init__.py` | **KEEP** | Package marker |
| `dashboard/terminal_dashboard.py` | **ARCHIVE** or **REMOVE** | Docstring-only stub; `rich` not in deps |
| `dashboard/web/__init__.py` | **ARCHIVE** or **REMOVE** | Empty React placeholder |

---

## 8. `docs/archive/` audit

All 14 phase/audit reports + `README.md` index — **KEEP in archive**.

| Verdict | Rationale |
|---------|-----------|
| **KEEP (archived)** | Historical value; already moved off root |
| Do not merge further | README/DESIGN/PROJECT_STATE are the live docs |

**Also recommend archiving:**

| File | Current location | Action |
|------|------------------|--------|
| `documentation_cleanup_report.md` | Root | **ARCHIVE** → `docs/archive/` (meta report; not reviewer entry) |
| `repository_hygiene_report.md` | Root (this file) | **ARCHIVE** after review, or keep one cycle at root |

**`docs/dashboard_screenshots/`** (if present): **KEEP** — useful for dashboard validation evidence; not clutter.

---

## 9. Root-level files

| File | Category | Verdict | Why |
|------|----------|---------|-----|
| `README.md` | Live doc | **KEEP** | Reviewer entry point |
| `DESIGN.md` | Live doc | **KEEP** | Architecture + decisions |
| `PROJECT_STATE.md` | Live doc | **KEEP** | Status snapshot |
| `CHOICES.md` | Redirect stub | **KEEP** | Points to DESIGN.md |
| `documentation_cleanup_report.md` | Meta / historical | **ARCHIVE** | One-time cleanup log |
| `repository_hygiene_report.md` | Meta / audit | **ARCHIVE** (after acceptance) | This audit |
| `requirements.txt` | Active | **KEEP** (trim unused) | |
| `requirements-dev.txt` | Dev | **KEEP** | |
| `pytest.ini` | Active | **KEEP** (tweak asyncio) | |
| `Dockerfile`, `docker-compose.yml` | Active | **KEEP** | |
| `.env.example` | Config template | **KEEP** (update stale keys) | References `yolov8n`, paths not matching `pipeline/config.py` |
| `.dockerignore` | Active | **KEEP** | |
| `.gitignore` | Active | **KEEP** (extend) | See §11 |
| `verification_push_test.txt` | **Accidental artifact** | **REMOVE** | Git push test string; no project value |
| `.coverage` | Local test artifact | **REMOVE** (disk) | Already gitignored; should not ship |
| `.env` | Local secrets | **KEEP** gitignored | Never commit |

---

## 10. Git-tracked artifacts that should not be

| Path | Verdict | Why |
|------|---------|-----|
| `data/docker_verify.db-shm` | **REMOVE from git** | SQLite WAL sidecar; runtime artifact |
| `data/docker_verify.db-wal` | **REMOVE from git** | Same |
| `PHASE_6A_REPORT.md`, `PHASE_6B_REPORT.md` | **Already deleted locally** | Moved to `docs/archive/` — commit deletion |

---

## 11. `data/` generated outputs (local, mostly untracked)

| Path | Verdict | Why |
|------|---------|-----|
| `data/generated/pipeline_demo/*.jsonl` | **Do not commit** | Regenerated by demo script |
| `data/generated/pos/*` | **Do not commit** | Regenerated by pos_loader |
| `data/generated/purchase_matches.json` | **Do not commit** | Offline validation output |
| `data/cctv/` | **Do not commit** | Large video files |
| `data/store_intelligence.db*` | **Do not commit** | Runtime DB |

**Recommendation:** Add to `.gitignore`:

```gitignore
data/generated/
data/cctv/
*.db-shm
*.db-wal
```

(Current `data/*.jsonl` only matches top-level `data/`, not `data/generated/`.)

---

## 12. Tests audit

| File | Verdict |
|------|---------|
| `tests/test_*.py` (10 files) | **KEEP** — active, 125 tests |
| `tests/conftest.py` | **KEEP** |
| `tests/assertions.py` | **KEEP** stub *or* **implement** — challenge placeholder; empty today |

Test files contain `# PROMPT:` / `# CHANGES MADE:` headers — **KEEP** if required by challenge submission format.

---

## 13. File-by-file recommendations (summary table)

| Path | Action | Category |
|------|--------|----------|
| `verification_push_test.txt` | **REMOVE** | Accidental |
| `data/docker_verify.db-shm` | **REMOVE** (git) | Accidental |
| `data/docker_verify.db-wal` | **REMOVE** (git) | Accidental |
| `.coverage` | **REMOVE** (local) | Dev artifact |
| `scripts/run_pipeline.sh` | **ARCHIVE** | Obsolete stub |
| `pipeline/run.sh` | **ARCHIVE** | Obsolete stub |
| `scripts/capture_dashboard_screenshots.py` | **ARCHIVE** | One-time validation |
| `dashboard/terminal_dashboard.py` | **ARCHIVE** | Stub |
| `dashboard/web/` | **ARCHIVE** | Stub |
| `documentation_cleanup_report.md` | **ARCHIVE** | Meta report |
| `structlog`, `pydantic-settings`, `pytest-asyncio` | **REMOVE** (deps) | Unused |
| `supervision` | **ADD** (deps) | Missing pin |
| `pipeline/cam*.py`, `config.py`, etc. | **COMMIT** | Active but untracked |
| `scripts/bridge*.py`, `run_pipeline_demo.py` | **COMMIT** | Active but untracked |
| `docs/archive/*` | **COMMIT** | Already organized |
| All `app/`, `examples/`, live docs | **KEEP** | Core product |

---

## 14. Proposed final folder structure

```text
Purpple_Vision/
├── README.md                    # Reviewer entry (5 min)
├── DESIGN.md                    # Architecture + decisions
├── PROJECT_STATE.md             # Status + gaps
├── CHOICES.md                   # Redirect → DESIGN.md
│
├── app/                         # FastAPI intelligence API
├── pipeline/                    # CV processors (no run.sh stub)
├── dashboard/
│   └── streamlit_app.py         # (drop terminal/web stubs or archive)
├── scripts/
│   ├── run_pipeline_demo.py
│   ├── bridge_pipeline_to_product.py
│   ├── seed_from_sample.py
│   └── phase0_import_check.py
├── tests/
├── examples/
│
├── docs/
│   ├── archive/
│   │   ├── README.md            # Index of historical reports
│   │   ├── scripts/             # (optional) archived one-time scripts
│   │   └── *.md                 # Phase/audit/migration reports
│   └── dashboard_screenshots/   # Validation PNGs (optional)
│
├── data/                        # gitignored runtime + generated
├── docker-compose.yml
├── Dockerfile
├── requirements.txt             # Trimmed runtime deps
├── requirements-dev.txt         # ruff, pytest-cov, optional matplotlib
└── pytest.ini
```

**Root markdown count after cleanup:** 3 live docs (+ optional hygiene report until archived).

---

## 15. Removal rationale (files marked REMOVE)

### `verification_push_test.txt`

Single line: "Git push verification test". Created to verify remote push; no runtime, test, or documentation purpose. Safe to delete.

### `data/docker_verify.db-shm` / `data/docker_verify.db-wal`

SQLite write-ahead log sidecars from local Docker verification. Should never be version-controlled; regenerated automatically when DB is open.

### `.coverage` (local only)

pytest-cov output on developer machine. Already in `.gitignore`; delete from disk before packaging.

### Unused pip packages (`structlog`, `pydantic-settings`, `pytest-asyncio`)

Installed but zero imports in application, pipeline, dashboard, or tests. Removing reduces install size and confusion. `structlog` was likely planned but `app/logging_config.py` uses stdlib JSON logging instead.

### Stub shell scripts (`run_pipeline.sh`, `pipeline/run.sh`) — ARCHIVE/REMOVE

Phase 0 placeholders with comment "no implementation yet". Superseded by `scripts/run_pipeline_demo.py`. Keeping them misleads reviewers into thinking bash entry point works.

---

## 16. Submission checklist (hygiene)

- [ ] Delete `verification_push_test.txt`
- [ ] `git rm` tracked `*.db-shm` / `*.db-wal`
- [ ] Commit untracked pipeline, scripts, `docs/archive/`
- [ ] Trim unused requirements; pin `supervision`
- [ ] Archive or remove duplicate bash stubs
- [ ] Archive `capture_dashboard_screenshots.py` and dashboard stubs
- [ ] Extend `.gitignore` for `data/generated/`, `data/cctv/`, WAL files
- [ ] Move `documentation_cleanup_report.md` to `docs/archive/`
- [ ] Sync `.env.example` with `pipeline/config.py` (optional polish)

---

## 17. Summary

The repository's **core code is sound** but **hygiene lag** comes from: (1) hackathon iteration artifacts at root, (2) unused dependencies from early scaffolding, (3) uncommitted Phase 6–8 work, (4) duplicate non-functional shell stubs, and (5) SQLite WAL files accidentally tracked.

**No application logic should be removed.** Focus cleanup on artifacts, stubs, unused deps, and gitignore/commit hygiene — not on `app/`, active pipeline modules, or archived reports in `docs/archive/`.
