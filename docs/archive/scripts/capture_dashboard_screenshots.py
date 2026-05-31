"""Generate dashboard validation screenshots from live API data."""

from __future__ import annotations

from pathlib import Path

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "docs" / "dashboard_screenshots"
BASE = "http://127.0.0.1:8000"
STORE = "STORE_BLR_002"
DATE = "2026-04-10"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    params = {"date": DATE}

    with httpx.Client(timeout=15) as client:
        metrics = client.get(f"{BASE}/stores/{STORE}/metrics", params=params).json()
        funnel = client.get(f"{BASE}/stores/{STORE}/funnel", params=params).json()

    fig, ax = plt.subplots(figsize=(12, 7))
    fig.patch.set_facecolor("#0e1117")
    ax.set_facecolor("#0e1117")
    ax.axis("off")

    ax.text(
        0.5,
        0.92,
        "Store Intelligence Dashboard",
        ha="center",
        va="top",
        fontsize=22,
        color="white",
        weight="bold",
    )
    ax.text(
        0.5,
        0.86,
        f"{STORE} | {DATE} (UTC)",
        ha="center",
        va="top",
        fontsize=12,
        color="#aaaaaa",
    )

    kpis = [
        ("Visitors", metrics["unique_visitors"]),
        ("Sessions", metrics["total_sessions"]),
        ("Revenue (INR)", "—"),
        ("Conversion", f"{metrics['conversion_rate'] * 100:.1f}%"),
    ]
    for index, (label, value) in enumerate(kpis):
        x = 0.08 + index * 0.23
        box = FancyBboxPatch(
            (x, 0.62),
            0.2,
            0.16,
            boxstyle="round,pad=0.02",
            linewidth=1,
            edgecolor="#333",
            facecolor="#1a1d24",
        )
        ax.add_patch(box)
        ax.text(
            x + 0.1,
            0.72,
            str(value),
            ha="center",
            va="center",
            fontsize=20,
            color="white",
            weight="bold",
        )
        ax.text(
            x + 0.1,
            0.65,
            label,
            ha="center",
            va="center",
            fontsize=10,
            color="#cccccc",
        )

    warn = FancyBboxPatch(
        (0.08, 0.18),
        0.84,
        0.34,
        boxstyle="round,pad=0.02",
        linewidth=1,
        edgecolor="#856404",
        facecolor="#332701",
    )
    ax.add_patch(warn)
    msg = (
        f"No sessions found for selected date ({DATE}).\n\n"
        "Sessions open on ENTRY/REENTRY (CAM3). Current dataset has zone events only.\n"
        "Run CAM3 pipeline + re-bridge to populate sessions."
    )
    ax.text(0.5, 0.35, msg, ha="center", va="center", fontsize=11, color="#ffeeba")

    empty_path = OUT / "dashboard_empty_state.png"
    fig.savefig(empty_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved {empty_path}")

    fig2, ax2 = plt.subplots(figsize=(10, 5))
    fig2.patch.set_facecolor("#0e1117")
    ax2.set_facecolor("#0e1117")

    stage_keys = [
        "unique_visitors",
        "reached_any_zone",
        "billing_queue",
        "converted_visitors",
    ]
    labels = ["Visitors", "Engaged", "Billing", "Purchases"]
    counts: list[int] = []
    for key in stage_keys:
        count = 0
        for stage in funnel["stages"]:
            if stage["stage"] == key:
                count = stage["count"]
                break
        counts.append(count)

    ax2.bar(labels, counts, color="#4e79a7")
    ax2.set_title(f"Funnel reference — {DATE} (shown when sessions > 0)", color="white")
    ax2.tick_params(colors="white")
    for spine in ax2.spines.values():
        spine.set_color("#444")
    ax2.set_ylabel("Count", color="white")

    funnel_path = OUT / "dashboard_funnel_zero_state.png"
    fig2.savefig(funnel_path, dpi=150, bbox_inches="tight", facecolor=fig2.get_facecolor())
    plt.close(fig2)
    print(f"Saved {funnel_path}")


if __name__ == "__main__":
    main()
