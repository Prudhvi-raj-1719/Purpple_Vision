# Project state (submission snapshot)

**Last updated:** 2026-06-04

## Status

| Area | State |
|------|--------|
| Detection pipeline (CAM1–5, per-store) | Done |
| Intelligence API + SQLite analytics | Done |
| Streamlit dashboard | Done |
| Per-store validation DBs | Done (`store_*_validation.db`) |
| CCTV intelligence dashboards | Done (`store1_real`, `store2_real`) |
| Cloud / Render deploy | **Not used** (local + video demo) |

## Run for submission (short)

```powershell
pip install -r requirements.txt
streamlit run dashboard/streamlit_app.py
```

Pick **store1_real** or **store2_real**, date **2026-04-10**. Install **FFmpeg** for shelf video playback.

Full commands: **[docs/SUBMISSION.md](docs/SUBMISSION.md)** · Checklist: **[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)**

## Regenerate data

```powershell
$env:PURPPLE_STORE = "store_1"   # or store_2
python scripts/demo_runner.py
```
