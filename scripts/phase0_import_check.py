"""Phase 0 import verification script — not application code."""

import sys

CHECKS = [
    ("fastapi", "fastapi"),
    ("sqlalchemy", "sqlalchemy"),
    ("pydantic", "pydantic"),
    ("httpx", "httpx"),
    ("opencv", "cv2"),
    ("ultralytics", "ultralytics"),
    ("supervision", "supervision"),
    ("numpy", "numpy"),
    ("pandas", "pandas"),
    ("streamlit", "streamlit"),
    ("pytest", "pytest"),
]

print(f"Python: {sys.version}\n")
print(f"{'Package':<14} {'Status':<8} Version")
print("-" * 50)

results = []
for name, module in CHECKS:
    try:
        mod = __import__(module)
        version = getattr(mod, "__version__", "unknown")
        results.append((name, "PASS", version))
        print(f"{name:<14} {'PASS':<8} {version}")
    except Exception as exc:
        results.append((name, "FAIL", str(exc)))
        print(f"{name:<14} {'FAIL':<8} {exc}")

failed = [r for r in results if r[1] == "FAIL"]
print()
print("Overall:", "ALL PASS" if not failed else f"{len(failed)} FAILED")
sys.exit(1 if failed else 0)
