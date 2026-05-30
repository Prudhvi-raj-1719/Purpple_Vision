# Store Intelligence

> **Phase 0 — Project Scaffold**
> Development environment and folder structure only. No application logic yet.

## Overview

End-to-end Store Intelligence system for the Apex Retail 48-hour engineering challenge.
Converts CCTV footage into structured behavioral events and exposes real-time analytics via REST API.

## Prerequisites

- **Python 3.11.x** (required — see troubleshooting if you have 3.12 or 3.13)
- **Git**

Optional:

- Docker & Docker Compose (for containerized deployment)

## Quick Setup on a New Machine

### 1. Clone repository

```powershell
git clone https://github.com/Prudhvi-raj-1719/Purpple_Vision.git
cd Purpple_Vision
```

### 2. Create virtual environment (Python 3.11)

Use Python 3.11 explicitly — do not use the system default if it is 3.12 or 3.13.

```powershell
# Windows (recommended)
py -3.11 -m venv .venv

# macOS / Linux (if python3.11 is installed)
python3.11 -m venv .venv
```

### 3. Activate virtual environment

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Windows CMD
.\.venv\Scripts\activate.bat

# macOS / Linux
source .venv/bin/activate
```

### 4. Upgrade pip

```powershell
python -m pip install --upgrade pip
```

### 5. Install requirements

```powershell
pip install -r requirements.txt
```

> First install may take 5–15 minutes because `ultralytics` pulls in `torch` (~700 MB+).

### 6. Create `.env` from `.env.example`

```powershell
# Windows
copy .env.example .env

# macOS / Linux
cp .env.example .env
```

### 7. Verify installation

```powershell
python --version
pip check
python scripts/phase0_import_check.py
```

Expected: `Python 3.11.x`, `No broken requirements found`, and `Overall: ALL PASS`.

Quick one-liner check:

```powershell
python -c "import fastapi, sqlalchemy, cv2, ultralytics, pandas, streamlit, pytest; print('All core packages OK')"
```

## Troubleshooting

### Python 3.13 is not supported

**Symptom:** `pip install -r requirements.txt` fails while building `numpy` from source, with errors about missing C compilers (`cl`, `gcc`, Meson build failure).

**Cause:** Dependencies are pinned for **Python 3.11.x**. NumPy 1.26.4 has pre-built wheels for 3.11 but not for 3.13, so pip tries to compile from source.

**Fix:**

```powershell
# Check your version
python --version

# Recreate the venv with Python 3.11
deactivate
Remove-Item -Recurse -Force .venv   # Windows
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Torch installation is slow

**Symptom:** `pip install` appears stuck on `torch` or `torchvision` for several minutes.

**Cause:** Normal behavior. `ultralytics` depends on PyTorch, which is a large download (~700 MB+ on CPU builds).

**Fix:** Wait for the install to finish. Do not interrupt unless it fails with an error. Verify after install:

```powershell
python -c "import torch; print(torch.__version__)"
```

### OpenCV installation issues

**Symptom:** `import cv2` fails, or pip reports conflicts between `opencv-python` and `opencv-python-headless`.

**Cause:** This project pins `opencv-python-headless`. `ultralytics` may also install `opencv-python` as a transitive dependency.

**Fix:**

```powershell
pip install --force-reinstall opencv-python-headless==4.10.0.84
python -c "import cv2; print(cv2.__version__)"
```

If import still fails on Linux, install system libraries:

```bash
sudo apt-get install -y libgl1 libglib2.0-0
```

On Windows, reinstalling the headless wheel is usually sufficient.

## Project Structure

```
├── app/              # FastAPI intelligence API
├── pipeline/         # CV detection & event emission pipeline
├── dashboard/        # Streamlit live dashboard (bonus)
├── tests/            # pytest test suite
├── scripts/          # Utility scripts
├── data/             # Dataset (gitignored — place challenge ZIP contents here)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── DESIGN.md
└── CHOICES.md
```

## Docker (Phase 1+)

SQLite is file-based — no database container required.

```powershell
# API only
docker compose up --build api

# API + Streamlit dashboard
docker compose --profile dashboard up --build
```

## Documentation

- [DESIGN.md](./DESIGN.md) — Architecture overview
- [CHOICES.md](./CHOICES.md) — Technical decision log

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Scaffold & environment | In progress |
| 1 | API core | Not started |
| 2 | Detection pipeline MVP | Not started |
| 3 | Pipeline completeness | Not started |
| 4 | Production polish | Not started |
| 5 | Live dashboard | Not started |
