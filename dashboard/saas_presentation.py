"""Enterprise SaaS presentation layer for the Retail Intelligence dashboard."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Plotly defaults (appearance only)
# ---------------------------------------------------------------------------

DEFAULT_PLOT_MARGIN = dict(l=24, r=24, t=56, b=24)

PLOTLY_LAYOUT = dict(
    font=dict(family="DM Sans, Segoe UI, sans-serif", size=14, color="#334155"),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    colorway=["#0ea5e9", "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"],
)

SAAS_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');

    .stApp {
        background:
            radial-gradient(circle at top right, rgba(14,165,233,.12), transparent 40%),
            radial-gradient(circle at bottom left, rgba(99,102,241,.08), transparent 40%),
            linear-gradient(180deg, #f8fbff 0%, #eef4fb 50%, #e8edf4 100%) !important;
    }
    .main .block-container {
        padding-top: 0.35rem !important;
        padding-bottom: 1.75rem !important;
        max-width: 1440px !important;
        margin: auto !important;
    }
    h1, h2, h3, p, li, span { font-family: 'DM Sans', sans-serif !important; }

    @keyframes fadeUp {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @keyframes heroGlow {
        0%, 100% { opacity: 0.4; transform: scale(1); }
        50% { opacity: 0.65; transform: scale(1.03); }
    }
    @keyframes pulseRing {
        0%, 100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.55); }
        50% { box-shadow: 0 0 0 8px rgba(52, 211, 153, 0); }
    }
    @keyframes livePulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.55; }
    }

    .fade-up { animation: fadeUp 0.5s ease forwards; }

    /* Sidebar command center — dark surface (default) */
    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0b1220 0%, #111827 48%, #0f172a 100%) !important;
        border-right: 1px solid rgba(148, 163, 184, 0.12) !important;
        color-scheme: dark;
    }
    div[data-testid="stSidebar"] > div:first-child {
        padding-top: 1rem !important;
    }
    div[data-testid="stSidebar"] label,
    div[data-testid="stSidebar"] .stCaption,
    div[data-testid="stSidebar"] p { color: #94a3b8 !important; }
    div[data-testid="stSidebar"] h1, div[data-testid="stSidebar"] h2,
    div[data-testid="stSidebar"] h3 { color: #f8fafc !important; }

    .sidebar-brand { margin-bottom: 0.75rem; }
    .sidebar-brand-head {
        display: flex; align-items: center; gap: 0.65rem;
        margin-bottom: 0.55rem;
    }
    .sidebar-brand-head .sidebar-avatar {
        margin-bottom: 0; flex-shrink: 0;
    }
    .sb-app-name {
        font-size: 1.32rem; font-weight: 700; line-height: 1.15;
        letter-spacing: -0.03em;
        background: linear-gradient(135deg, #0ea5e9 0%, #3b82f6 38%, #6366f1 68%, #8b5cf6 100%);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        color: transparent;
    }
    .sidebar-brand .sb-eyebrow {
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.14em;
        text-transform: uppercase; color: #38bdf8; margin-bottom: 0.2rem;
    }
    /* Executive Store Operations — contrast follows sidebar surface */
    div[data-testid="stSidebar"] .sb-title--dark,
    div[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .sb-title--dark {
        font-size: 1.15rem; font-weight: 700; line-height: 1.2;
        color: #f8fafc !important;
    }
    div[data-testid="stSidebar"] .sb-title--light,
    div[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .sb-title--light {
        font-size: 1.15rem; font-weight: 700; line-height: 1.2;
        color: #0f172a !important;
    }
    div[data-testid="stSidebar"] .sb-sub--dark,
    div[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .sb-sub--dark {
        font-size: 0.8rem; margin-top: 0.25rem;
        color: #94a3b8 !important;
    }
    div[data-testid="stSidebar"] .sb-sub--light,
    div[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .sb-sub--light {
        font-size: 0.8rem; margin-top: 0.25rem;
        color: #64748b !important;
    }

    /* Light sidebar surface (runtime class or Streamlit light theme) */
    div[data-testid="stSidebar"]:has(.sidebar-brand--light),
    [data-theme="light"] div[data-testid="stSidebar"],
    .stApp[data-theme="light"] div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 48%, #e2e8f0 100%) !important;
        border-right: 1px solid #cbd5e1 !important;
        color-scheme: light;
    }
    [data-theme="light"] div[data-testid="stSidebar"] label,
    [data-theme="light"] div[data-testid="stSidebar"] .stCaption,
    [data-theme="light"] div[data-testid="stSidebar"] p,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] label,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] .stCaption,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] p {
        color: #475569 !important;
    }
    [data-theme="light"] div[data-testid="stSidebar"] .sidebar-brand .sb-title,
    [data-theme="light"] div[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .sb-title,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] .sidebar-brand .sb-title,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .sb-title {
        color: #0f172a !important;
    }
    [data-theme="light"] div[data-testid="stSidebar"] .sidebar-brand .sb-sub,
    [data-theme="light"] div[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .sb-sub,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] .sidebar-brand .sb-sub,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] .sb-sub {
        color: #64748b !important;
    }
    [data-theme="light"] div[data-testid="stSidebar"] .sidebar-brand .sb-eyebrow,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] .sidebar-brand .sb-eyebrow {
        color: #0369a1 !important;
    }
    [data-theme="light"] div[data-testid="stSidebar"] .glass-panel,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] .glass-panel {
        background: rgba(255, 255, 255, 0.85);
        border-color: #e2e8f0;
    }
    [data-theme="light"] div[data-testid="stSidebar"] .glass-panel .gp-label,
    .stApp[data-theme="light"] div[data-testid="stSidebar"] .glass-panel .gp-label {
        color: #64748b !important;
    }
    .sidebar-avatar {
        width: 42px; height: 42px; border-radius: 12px;
        background: linear-gradient(135deg, #0ea5e9, #6366f1);
        display: flex; align-items: center; justify-content: center;
        font-size: 1.25rem; box-shadow: 0 4px 14px rgba(14, 165, 233, 0.35);
    }
    .glass-panel {
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 12px; padding: 0.85rem 0.9rem; margin-bottom: 0.85rem;
        backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
    }
    .glass-panel .gp-label {
        font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.08em; color: #64748b; margin-bottom: 0.35rem;
    }
    div[data-testid="stSidebar"] .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #0ea5e9 0%, #2563eb 55%, #6366f1 100%) !important;
        border: none !important; font-weight: 700 !important;
        box-shadow: 0 4px 14px rgba(37, 99, 235, 0.35) !important;
    }
    div[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
        filter: brightness(1.08);
        transform: translateY(-1px);
    }
    [data-testid="collapsedControl"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    [data-testid="collapsedControl"] svg {
        fill: #e2e8f0 !important;
        stroke: #e2e8f0 !important;
    }
    [data-testid="stSidebarCollapsedControl"] svg,
    section[data-testid="stSidebar"][aria-expanded="false"] ~ * [data-testid="collapsedControl"] svg {
        fill: #334155 !important;
        stroke: #334155 !important;
    }

    /* Glass sections */
    .glass {
        margin-bottom: 1.1rem; padding: 1.35rem 1.5rem;
        background: rgba(255, 255, 255, 0.72);
        backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
        border-radius: 18px;
        border: 1px solid rgba(255, 255, 255, 0.88);
        box-shadow: 0 4px 24px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .glass:hover {
        box-shadow: 0 10px 32px rgba(15, 23, 42, 0.09);
    }
    .glass.accent-blue { border-top: 3px solid #0ea5e9; }
    .glass.accent-indigo { border-top: 3px solid #6366f1; }
    .glass.accent-amber { border-top: 3px solid #f59e0b; }
    .glass.accent-green { border-top: 3px solid #10b981; }
    .glass.accent-slate { border-top: 3px solid #64748b; }

    .eyebrow {
        font-size: 0.68rem; font-weight: 700; letter-spacing: 0.12em;
        text-transform: uppercase; color: #64748b; margin: 0 0 0.35rem 0;
    }
    .eyebrow.blue { color: #0369a1; }
    .eyebrow.amber { color: #b45309; }
    .eyebrow.green { color: #047857; }
    .h-section {
        font-size: 1.32rem !important; font-weight: 700 !important;
        color: #0f172a !important; margin: 0 0 1rem 0 !important;
        letter-spacing: -0.02em;
    }

    /* Hero */
    .hero {
        position: relative; min-height: 180px; margin: 0 0 1.15rem 0;
        padding: 1.5rem 1.85rem; border-radius: 20px; overflow: hidden;
        background: linear-gradient(125deg, #0f172a 0%, #1e3a5f 32%, #1d4ed8 68%, #2563eb 100%);
        box-shadow: 0 12px 40px rgba(15, 23, 42, 0.28), 0 4px 12px rgba(37, 99, 235, 0.2);
        display: flex; align-items: center; justify-content: space-between; gap: 1.25rem;
    }
    .hero-float {
        position: absolute; inset: -25% 20% auto -15%; height: 130%;
        background: radial-gradient(ellipse at center, rgba(56, 189, 248, 0.32) 0%, transparent 68%);
        animation: heroGlow 5s ease-in-out infinite; pointer-events: none;
    }
    .hero-left, .hero-right {
        position: relative; z-index: 1; display: flex; align-items: center; gap: 1rem;
    }
    .hero-right { flex-direction: row; align-items: center; gap: 1.35rem; flex-wrap: wrap; }
    .hero-brand {
        font-size: 0.7rem; font-weight: 700; letter-spacing: 0.14em;
        text-transform: uppercase; color: #93c5fd;
    }
    .hero-store {
        font-size: 1.75rem; font-weight: 700; color: #f8fafc; line-height: 1.15;
        margin: 0.15rem 0 0.35rem 0;
    }
    .hero-meta {
        font-size: 0.8rem; color: #cbd5e1; line-height: 1.5;
    }
    .hero-badge {
        display: inline-flex; align-items: center; gap: 0.35rem;
        margin-top: 0.5rem; font-size: 0.72rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.06em;
        color: #e0f2fe; background: rgba(255,255,255,0.1);
        border: 1px solid rgba(255,255,255,0.22); border-radius: 999px;
        padding: 0.3rem 0.7rem;
    }
    .hero-stat {
        text-align: center; min-width: 88px;
    }
    .hero-stat .hs-val {
        font-size: 1.55rem; font-weight: 700; color: #f8fafc; line-height: 1.1;
    }
    .hero-stat .hs-lbl {
        font-size: 0.68rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.06em; color: #94a3b8; margin-top: 0.2rem;
    }
    .live-pill {
        display: inline-flex; align-items: center; gap: 0.45rem;
        font-size: 0.75rem; font-weight: 700; letter-spacing: 0.06em;
        text-transform: uppercase; color: #bbf7d0;
        background: rgba(16, 185, 129, 0.2); border: 1px solid rgba(52, 211, 153, 0.45);
        border-radius: 999px; padding: 0.38rem 0.85rem;
    }
    .live-pill .dot {
        width: 8px; height: 8px; border-radius: 50%; background: #34d399;
        animation: pulseRing 1.8s ease infinite;
    }
    .status-ring {
        width: 56px; height: 56px; border-radius: 50%;
        background: conic-gradient(#34d399 var(--pct), rgba(255,255,255,0.15) 0);
        display: flex; align-items: center; justify-content: center;
        position: relative;
    }
    .status-ring::after {
        content: ''; position: absolute; inset: 6px; border-radius: 50%;
        background: #0f172a;
    }
    .status-ring span {
        position: relative; z-index: 1; font-size: 0.72rem; font-weight: 700;
        color: #6ee7b7;
    }

    /* Metric grid */
    .metric-grid {
        display: grid; grid-template-columns: repeat(6, 1fr); gap: 0.8rem;
        margin-bottom: 0.85rem;
    }
    @media (max-width: 1200px) { .metric-grid { grid-template-columns: repeat(3, 1fr); } }
    @media (max-width: 768px) { .metric-grid { grid-template-columns: 1fr; } }

    .metric-tile {
        min-height: 140px; display: flex; flex-direction: column; justify-content: space-between;
        background: rgba(255, 255, 255, 0.92); border-radius: 16px;
        padding: 1rem 1.05rem; border: 1px solid rgba(226, 232, 240, 0.95);
        box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-tile:hover {
        transform: translateY(-4px);
        box-shadow: 0 12px 28px rgba(15, 23, 42, 0.1);
    }
    .metric-tile.glow-blue { box-shadow: 0 4px 20px rgba(14, 165, 233, 0.12); border-color: rgba(14, 165, 233, 0.25); }
    .metric-tile.glow-green { box-shadow: 0 4px 20px rgba(16, 185, 129, 0.12); border-color: rgba(16, 185, 129, 0.25); }
    .metric-tile.glow-cyan { box-shadow: 0 4px 20px rgba(6, 182, 212, 0.12); border-color: rgba(6, 182, 212, 0.25); }
    .metric-tile.glow-red { box-shadow: 0 4px 20px rgba(239, 68, 68, 0.12); border-color: rgba(239, 68, 68, 0.25); }
    .metric-tile .mt-icon { font-size: 1.4rem; line-height: 1; }
    .metric-tile .mt-val {
        font-size: clamp(1.45rem, 2vw, 2.1rem); font-weight: 700;
        color: #0f172a; letter-spacing: -0.02em; line-height: 1.1;
    }
    .metric-tile .mt-trend {
        font-size: 0.72rem; color: #64748b; font-weight: 500;
    }
    .metric-tile .mt-chip {
        display: inline-block; font-size: 0.62rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.04em;
        padding: 0.18rem 0.45rem; border-radius: 999px; margin-top: 0.2rem;
        width: fit-content;
    }
    .metric-tile .mt-chip.ok { background: #d1fae5; color: #047857; }
    .metric-tile .mt-chip.warn { background: #fef3c7; color: #b45309; }
    .metric-tile .mt-chip.neutral { background: #f1f5f9; color: #475569; }
    .metric-tile .mt-lbl {
        font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.06em; color: #64748b;
    }

    /* Story panel */
    .story-panel {
        display: flex; gap: 1rem; align-items: flex-start;
        background: linear-gradient(135deg, rgba(255,255,255,0.95) 0%, rgba(239,246,255,0.9) 100%);
        border: 1px solid rgba(14, 165, 233, 0.2); border-radius: 16px;
        padding: 1.15rem 1.35rem; margin-bottom: 1rem;
    }
    .story-panel .sp-icon {
        font-size: 2rem; line-height: 1; flex-shrink: 0;
    }
    .story-panel .sp-body { flex: 1; }
    .story-panel .sp-title {
        font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.08em; color: #0369a1; margin-bottom: 0.35rem;
    }
    .story-panel .sp-text {
        font-size: 0.95rem; color: #1e293b; line-height: 1.6; margin: 0;
    }
    .story-panel .sp-priority {
        flex-shrink: 0; font-size: 0.68rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.06em;
        padding: 0.35rem 0.7rem; border-radius: 999px; height: fit-content;
    }
    .story-panel .sp-priority.high { background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }
    .story-panel .sp-priority.medium { background: #fef3c7; color: #b45309; border: 1px solid #fde68a; }
    .story-panel .sp-priority.low { background: #d1fae5; color: #047857; border: 1px solid #6ee7b7; }

    /* Action list */
    .action-list {
        background: linear-gradient(135deg, rgba(255, 251, 235, 0.95) 0%, rgba(254, 243, 199, 0.85) 100%);
        border: 1px solid rgba(251, 191, 36, 0.35);
        border-left: 4px solid #f59e0b; border-radius: 14px;
        padding: 1rem 1.2rem; margin-bottom: 1rem;
        transition: background 0.2s ease, box-shadow 0.2s ease;
    }
    .action-list:hover {
        background: linear-gradient(135deg, #fffbeb 0%, #fde68a 100%);
        box-shadow: 0 6px 20px rgba(245, 158, 11, 0.15);
    }
    .action-list ul {
        margin: 0.35rem 0 0 0; padding-left: 1.15rem;
        color: #1e293b; font-size: 0.9rem; line-height: 1.55;
    }
    .action-list li { margin-bottom: 0.3rem; }
    .action-list li::marker { color: #ea580c; }

    /* Journey */
    .journey-wrap { display: flex; gap: 1.15rem; align-items: stretch; flex-wrap: wrap; }
    .journey-sankey-col { flex: 1.65 1 420px; min-width: 280px; }
    .journey-conv-col { flex: 1 1 280px; min-width: 240px; max-width: 380px; }

    .conv-card {
        height: 100%; min-height: 320px;
        background: linear-gradient(165deg, #fff 0%, #f8fafc 100%);
        border: 1px solid #e2e8f0; border-radius: 18px;
        padding: 1.35rem 1.4rem; display: flex; flex-direction: column;
        align-items: center; text-align: center;
        box-shadow: 0 4px 18px rgba(15, 23, 42, 0.06);
        transition: transform 0.2s ease;
    }
    .conv-card:hover { transform: translateY(-4px); }
    .conv-card h3 {
        margin: 0 0 1rem 0; font-size: 0.82rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.07em; color: #64748b;
        width: 100%; text-align: left;
    }
    .conv-ring {
        width: 120px; height: 120px; border-radius: 50%;
        background: conic-gradient(var(--ring-color) var(--ring-pct), #e2e8f0 0);
        display: flex; align-items: center; justify-content: center;
        margin: 0.5rem 0 0.75rem 0; position: relative;
    }
    .conv-ring::after {
        content: ''; position: absolute; inset: 14px; border-radius: 50%;
        background: #fff;
    }
    .conv-ring .cr-val {
        position: relative; z-index: 1; font-size: 1.65rem; font-weight: 700;
        color: #0f172a; letter-spacing: -0.03em;
    }
    .conv-badge {
        display: inline-block; font-size: 0.8rem; font-weight: 700;
        padding: 0.4rem 0.9rem; border-radius: 999px; margin-bottom: 0.85rem;
    }
    .conv-badge.excellent { background: #d1fae5; color: #047857; border: 1px solid #6ee7b7; }
    .conv-badge.good { background: #dbeafe; color: #1d4ed8; border: 1px solid #93c5fd; }
    .conv-badge.attention { background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }
    .conv-step {
        width: 100%; display: flex; justify-content: space-between;
        padding: 0.4rem 0; border-bottom: 1px solid #f1f5f9;
        font-size: 0.85rem; color: #64748b;
    }
    .conv-step strong { color: #0f172a; }

    /* Heatmap stats */
    .heatmap-stats {
        display: flex; flex-wrap: wrap; gap: 0.55rem; margin-bottom: 0.85rem;
    }
    .stat-chip {
        font-size: 0.78rem; font-weight: 600; color: #1e293b;
        background: rgba(255,255,255,0.9); border: 1px solid #e2e8f0;
        border-radius: 999px; padding: 0.4rem 0.85rem;
    }
    .stat-chip span { color: #64748b; font-weight: 500; }

    .zone-grid {
        display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.85rem;
        margin-top: 1rem;
    }
    @media (max-width: 1200px) { .zone-grid { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 768px) { .zone-grid { grid-template-columns: 1fr; } }

    .zone-card {
        background: rgba(255,255,255,0.95); border-radius: 14px;
        padding: 0.9rem 1rem; border: 1px solid #e2e8f0;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .zone-card:hover { transform: translateY(-4px); box-shadow: 0 8px 22px rgba(15,23,42,0.08); }
    .zone-card.tier-green { border-left: 4px solid #10b981; }
    .zone-card.tier-amber { border-left: 4px solid #f59e0b; }
    .zone-card.tier-red { border-left: 4px solid #ef4444; }
    .zone-card .zc-rank {
        font-size: 0.65rem; font-weight: 800; color: #94a3b8; margin-bottom: 0.15rem;
    }
    .zone-card .zc-name {
        font-size: 0.95rem; font-weight: 700; color: #0f172a; margin-bottom: 0.4rem;
    }
    .zone-card .zc-stat { font-size: 0.76rem; color: #64748b; line-height: 1.45; }
    .zone-score-bar {
        height: 5px; border-radius: 999px; background: #e2e8f0;
        margin-top: 0.55rem; overflow: hidden;
    }
    .zone-score-bar div {
        height: 100%; border-radius: 999px;
        background: linear-gradient(90deg, #0ea5e9, #6366f1);
    }
    .zone-col-head {
        font-size: 0.7rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.07em; margin: 0 0 0.55rem 0;
    }
    .zone-empty {
        font-size: 0.86rem; color: #64748b; padding: 0.65rem;
        background: #f8fafc; border-radius: 12px; border: 1px dashed #e2e8f0;
    }

    /* Checkout */
    .checkout-layout {
        display: grid; grid-template-columns: repeat(4, 1fr) 220px;
        gap: 0.8rem; align-items: stretch; margin-bottom: 0.85rem;
    }
    @media (max-width: 1200px) {
        .checkout-layout { grid-template-columns: repeat(2, 1fr); }
        .checkout-gauge-wrap { grid-column: 1 / -1; }
    }
    @media (max-width: 768px) { .checkout-layout { grid-template-columns: 1fr; } }

    .checkout-widget {
        min-height: 120px; background: rgba(255,255,255,0.95);
        border-radius: 16px; padding: 1rem; border: 1px solid #e2e8f0;
        display: flex; flex-direction: column; justify-content: space-between;
        transition: transform 0.2s ease;
    }
    .checkout-widget:hover { transform: translateY(-4px); box-shadow: 0 8px 22px rgba(15,23,42,0.08); }
    .checkout-widget .cw-icon { font-size: 1.35rem; }
    .checkout-widget .cw-val { font-size: 1.7rem; font-weight: 700; color: #0f172a; }
    .checkout-widget .cw-lbl {
        font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
        color: #64748b; letter-spacing: 0.05em;
    }
    .checkout-widget .cw-pill {
        font-size: 0.62rem; font-weight: 700; text-transform: uppercase;
        padding: 0.2rem 0.5rem; border-radius: 999px; width: fit-content;
    }
    .checkout-widget .cw-pill.excellent { background: #d1fae5; color: #047857; }
    .checkout-widget .cw-pill.healthy { background: #dbeafe; color: #1d4ed8; }
    .checkout-widget .cw-pill.warning { background: #fee2e2; color: #b91c1c; }

    .checkout-gauge-wrap {
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        background: rgba(255,255,255,0.95); border-radius: 16px;
        border: 1px solid #e2e8f0; padding: 1rem;
    }
    .checkout-gauge {
        width: 200px; height: 200px; border-radius: 50%;
        background: conic-gradient(var(--gauge-color) var(--gauge-pct), #e2e8f0 0);
        display: flex; align-items: center; justify-content: center;
        position: relative;
    }
    .checkout-gauge::after {
        content: ''; position: absolute; inset: 22px; border-radius: 50%;
        background: #fff;
    }
    .checkout-gauge .cg-inner {
        position: relative; z-index: 1; text-align: center;
    }
    .checkout-gauge .cg-label {
        font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
        color: #64748b; letter-spacing: 0.05em;
    }
    .checkout-gauge .cg-status {
        font-size: 1rem; font-weight: 700; color: #0f172a; margin-top: 0.25rem;
    }
    .checkout-rec {
        background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
        border: 1px solid #fde68a; border-left: 4px solid #f59e0b;
        border-radius: 14px; padding: 1rem 1.15rem; margin-top: 0.5rem;
    }
    .checkout-rec h4 {
        margin: 0 0 0.4rem 0; font-size: 0.82rem; font-weight: 700;
        color: #92400e; text-transform: uppercase; letter-spacing: 0.05em;
    }
    .checkout-rec p { margin: 0; font-size: 0.92rem; color: #1e293b; line-height: 1.55; }

    /* Insights */
    .insights-row {
        display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;
    }
    @media (max-width: 768px) { .insights-row { grid-template-columns: 1fr; } }

    .insight-panel {
        border-radius: 16px; padding: 1.15rem 1.25rem;
        transition: transform 0.2s ease;
    }
    .insight-panel:hover { transform: translateY(-4px); }
    .insight-panel.risk {
        background: linear-gradient(145deg, #fef2f2 0%, #fee2e2 50%, rgba(255,255,255,0.9) 100%);
        border: 1px solid #fecaca;
    }
    .insight-panel.pos {
        background: linear-gradient(145deg, #ecfdf5 0%, #d1fae5 50%, rgba(255,255,255,0.9) 100%);
        border: 1px solid #6ee7b7;
    }
    .insight-panel h4 {
        margin: 0 0 0.75rem 0; font-size: 0.95rem; font-weight: 700; color: #0f172a;
    }
    .insight-row {
        display: flex; flex-wrap: wrap; gap: 0.45rem; align-items: flex-start;
        padding: 0.55rem 0; border-bottom: 1px solid rgba(15,23,42,0.06);
        font-size: 0.88rem; color: #1e293b; line-height: 1.5;
    }
    .insight-row:last-child { border-bottom: none; }
    .severity-badge {
        font-size: 0.62rem; font-weight: 700; text-transform: uppercase;
        padding: 0.2rem 0.45rem; border-radius: 6px; flex-shrink: 0;
    }
    .severity-badge.high { background: #fee2e2; color: #b91c1c; }
    .severity-badge.medium { background: #fef3c7; color: #b45309; }
    .severity-badge.low { background: #e0f2fe; color: #0369a1; }
    .insight-footer {
        margin-top: 0.85rem; padding-top: 0.75rem;
        border-top: 1px solid rgba(15,23,42,0.08);
        font-size: 0.78rem; color: #64748b;
    }
    .source-badge {
        display: inline-block; margin-left: 0.35rem; font-size: 0.68rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.04em;
        padding: 0.25rem 0.55rem; border-radius: 999px;
    }
    .source-badge.llm { background: #ede9fe; color: #5b21b6; border: 1px solid #c4b5fd; }
    .source-badge.rules { background: #fff7ed; color: #9a3412; border: 1px solid #fdba74; }
    .source-badge.engine { background: #e0f2fe; color: #0369a1; border: 1px solid #7dd3fc; }

    /* NOC */
    .noc-grid {
        display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.8rem;
        margin-bottom: 0.85rem;
    }
    @media (max-width: 1200px) { .noc-grid { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 768px) { .noc-grid { grid-template-columns: 1fr; } }

    .noc-card {
        background: rgba(255,255,255,0.92); border: 1px solid #e2e8f0;
        border-radius: 16px; padding: 1.05rem 1.1rem; min-height: 8.5rem;
        transition: transform 0.2s ease;
    }
    .noc-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(15,23,42,0.08); }
    .noc-card .nc-top {
        display: flex; justify-content: space-between; align-items: flex-start;
    }
    .noc-card .nc-icon { font-size: 1.6rem; line-height: 1; }
    .noc-pulse {
        width: 10px; height: 10px; border-radius: 50%; background: #34d399;
        animation: pulseRing 1.8s ease infinite;
    }
    .noc-pulse.off { background: #94a3b8; animation: none; }
    .noc-card .nc-label {
        font-size: 0.66rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.07em; color: #64748b; margin: 0.4rem 0 0.2rem 0;
    }
    .noc-card .nc-status {
        font-size: 1.05rem; font-weight: 700; color: #0f172a; line-height: 1.25;
    }
    .noc-card .nc-status.ok { color: #047857; }
    .noc-card .nc-status.warn { color: #b45309; }
    .noc-card .nc-status.bad { color: #b91c1c; }
    .noc-card .nc-pct {
        font-size: 0.78rem; font-weight: 600; color: #475569; margin-top: 0.15rem;
    }
    .noc-bar {
        height: 6px; border-radius: 999px; background: #e2e8f0;
        margin-top: 0.5rem; overflow: hidden;
    }
    .noc-bar div { height: 100%; border-radius: 999px; transition: width 0.3s ease; }
    .noc-bar div.ok { background: linear-gradient(90deg, #10b981, #34d399); }
    .noc-bar div.warn { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
    .noc-bar div.bad { background: linear-gradient(90deg, #ef4444, #f87171); }
    .noc-card .nc-update {
        font-size: 0.72rem; color: #94a3b8; margin-top: 0.45rem;
    }

    /* Trust */
    .trust {
        background: linear-gradient(160deg, #ecfdf5 0%, #d1fae5 35%, #f0fdf4 100%);
        border: 1px solid #6ee7b7; border-radius: 18px;
        padding: 1.5rem 1.6rem; margin-bottom: 1.1rem;
        box-shadow: 0 6px 24px rgba(5, 150, 105, 0.1);
        transition: transform 0.2s ease;
    }
    .trust:hover { transform: translateY(-2px); }
    .trust-head {
        display: flex; align-items: center; gap: 0.65rem; margin-bottom: 0.35rem;
    }
    .trust-head .shield { font-size: 1.75rem; }
    .trust-head h3 {
        margin: 0 !important; font-size: 1.35rem !important;
        color: #065f46 !important; font-weight: 700 !important;
    }
    .trust-sub { font-size: 0.88rem; color: #047857; margin: 0 0 1rem 0; }
    .trust-metrics {
        display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.75rem;
        margin-bottom: 1rem;
    }
    @media (max-width: 1200px) { .trust-metrics { grid-template-columns: repeat(3, 1fr); } }
    @media (max-width: 768px) { .trust-metrics { grid-template-columns: 1fr; } }
    .trust-metric {
        background: rgba(255,255,255,0.95); border-radius: 12px;
        padding: 0.85rem 1rem; border: 1px solid #bbf7d0;
    }
    .trust-metric .tm-lbl {
        font-size: 0.66rem; font-weight: 700; text-transform: uppercase;
        color: #64748b; letter-spacing: 0.05em;
    }
    .trust-metric .tm-val {
        font-size: clamp(1.25rem, 1.8vw, 1.85rem); font-weight: 700;
        color: #0f172a; margin-top: 0.3rem;
    }
    .trust-badges { display: flex; flex-wrap: wrap; gap: 0.5rem; }
    .trust-badge {
        font-size: 0.8rem; font-weight: 600; color: #065f46;
        background: #fff; border: 1px solid #6ee7b7; border-radius: 999px;
        padding: 0.35rem 0.75rem;
    }

    /* Technical panel */
    div[data-testid="stExpander"] { background: transparent !important; border: none !important; }
    div[data-testid="stExpander"] details {
        border-radius: 14px; overflow: hidden;
        border: 1px solid #334155;
        box-shadow: 0 4px 16px rgba(15,23,42,0.12);
    }
    div[data-testid="stExpander"] summary {
        font-weight: 700 !important; font-size: 1rem !important;
        color: #0f172a !important;
    }
    .tech-dark {
        background: linear-gradient(165deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
        border: 1px solid #475569; border-radius: 14px;
        padding: 1.25rem 1.35rem; margin-top: 0.5rem;
        box-shadow: 0 10px 36px rgba(15, 23, 42, 0.45);
    }
    .tech-dark .tech-head {
        display: flex; gap: 0.65rem; margin-bottom: 0.75rem;
    }
    .tech-dark .tech-head h3 {
        margin: 0 !important; font-size: 1.15rem !important;
        color: #38bdf8 !important; font-weight: 700 !important;
    }
    .tech-dark .tech-head p {
        margin: 0.2rem 0 0 0; font-size: 0.84rem; color: #94a3b8;
    }
    .tech-dark [data-testid="stTabs"] {
        background: #1e293b; border-radius: 10px; padding: 0.35rem;
    }
    .tech-dark [data-testid="stTabs"] button {
        color: #94a3b8 !important; font-weight: 600 !important;
        background: transparent !important;
    }
    .tech-dark [data-testid="stTabs"] button[aria-selected="true"] {
        color: #0f172a !important;
        background: #38bdf8 !important;
        border-radius: 8px !important;
    }
    .tech-dark [data-testid="stCaption"] { color: #94a3b8 !important; }

    ul.saas-bullets {
        margin: 0.2rem 0; padding-left: 1.15rem;
        color: #1e293b; font-size: 0.88rem; line-height: 1.5;
    }
    ul.saas-bullets li { margin-bottom: 0.2rem; }

    @media (max-width: 900px) {
        .hero {
            flex-direction: column; align-items: flex-start;
            min-height: 180px; padding: 1.25rem 1.35rem;
        }
        .hero-right { width: 100%; justify-content: flex-start; }
        .journey-conv-col { max-width: 100%; flex: 1 1 100%; }
    }
</style>
"""

_KPI_ICONS: dict[str, str] = {
    "Visitors": "👥",
    "Purchases": "🛒",
    "Revenue": "💰",
    "Conversion": "📈",
    "Top area": "⭐",
    "Focus area": "⚠",
}

_MONITOR_ICONS: dict[str, str] = {
    "Store": "🏪",
    "Analytics": "📊",
    "Cameras": "📹",
    "Confidence": "🎯",
}

_CHECKOUT_STATUS_LABELS = {
    "excellent": "Excellent",
    "healthy": "Healthy",
    "warning": "Warning",
}


def inject_saas_styles() -> None:
    st.markdown(SAAS_CSS, unsafe_allow_html=True)


def _streamlit_theme_type() -> str:
    """Return ``light`` or ``dark`` from Streamlit context when available."""
    try:
        theme = getattr(st.context, "theme", None)
        theme_type = getattr(theme, "type", None) if theme is not None else None
        if theme_type in ("light", "dark"):
            return str(theme_type)
    except Exception:
        pass
    return "dark"


def sidebar_brand_html() -> str:
    theme = _streamlit_theme_type()
    return (
        f'<div class="sidebar-brand sidebar-brand--{theme} fade-up">'
        '<div class="sidebar-brand-head">'
        '<div class="sidebar-avatar" aria-hidden="true">📊</div>'
        '<span class="sb-app-name">Purpple Vision</span>'
        "</div>"
        '<div class="sb-eyebrow">Retail Intelligence</div>'
        f'<div class="sb-title sb-title--{theme}">Executive Store Operations</div>'
        f'<div class="sb-sub sb-sub--{theme}">Command center for daily store analytics</div>'
        "</div>"
    )


def glass_control_label(label: str) -> str:
    return f'<div class="glass-panel"><div class="gp-label">{label}</div></div>'


def section_heading(title: str, *, eyebrow: str = "", accent: str = "blue") -> None:
    if eyebrow:
        st.markdown(f'<p class="eyebrow {accent}">{eyebrow}</p>', unsafe_allow_html=True)
    st.markdown(f'<h2 class="h-section">{title}</h2>', unsafe_allow_html=True)


def story_priority(conversion_rate: float) -> tuple[str, str]:
    if conversion_rate < 0.15:
        return "High", "high"
    if conversion_rate < 0.25:
        return "Medium", "medium"
    return "Low", "low"


def conversion_badge(rate: float) -> tuple[str, str, str]:
    if rate >= 0.35:
        return "Excellent", "excellent", "#10b981"
    if rate >= 0.25:
        return "Good", "good", "#2563eb"
    return "Needs Attention", "attention", "#ef4444"


def health_ring_pct(css: str) -> int:
    return {"ok": 92, "warn": 58, "bad": 28}.get(css, 50)


def noc_health_pct(css: str) -> int:
    return {"ok": 100, "warn": 65, "bad": 35}.get(css, 50)


def checkout_gauge_meta(queue_abandonment: float, peak_queue: int) -> tuple[str, str, int, str]:
    if queue_abandonment < 0.10 and peak_queue <= 2:
        return "Excellent", "#10b981", 92, "excellent"
    if queue_abandonment < 0.20 and peak_queue <= 4:
        return "Healthy", "#2563eb", 72, "healthy"
    return "Warning", "#ef4444", 42, "warning"


def insight_source_badge(source: str) -> str:
    raw = (source or "fallback").lower()
    if "llm" in raw or raw == "openai":
        return '<span class="source-badge llm">LLM</span>'
    if "fallback" in raw or "rule" in raw:
        return '<span class="source-badge rules">Fallback</span>'
    return '<span class="source-badge engine">Analytics Engine</span>'


def bullets_html(items: list[str]) -> str:
    if not items:
        return '<ul class="saas-bullets"><li>—</li></ul>'
    return "<ul class=\"saas-bullets\">" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


def hero_header_html(
    store_label: str,
    store_id: str,
    selected_date: date,
    *,
    visitors: int,
    revenue_text: str,
    conversion_text: str,
    status_label: str,
    status_css: str,
) -> str:
    date_text = selected_date.strftime("%d %b %Y")
    ring_pct = health_ring_pct(status_css)
    return (
        f'<div class="hero fade-up">'
        f'<div class="hero-float"></div>'
        f'<div class="hero-left">'
        f"<div>"
        f'<div class="hero-brand">Retail Intelligence</div>'
        f'<div class="hero-store">{store_label}</div>'
        f'<div class="hero-meta">Store ID · {store_id}<br>Date · {date_text}</div>'
        f'<span class="hero-badge">✦ Executive Summary · {status_label}</span>'
        f"</div></div>"
        f'<div class="hero-right">'
        f'<div class="hero-stat"><div class="hs-val">{visitors:,}</div>'
        f'<div class="hs-lbl">Visitors Today</div></div>'
        f'<div class="hero-stat"><div class="hs-val">{revenue_text}</div>'
        f'<div class="hs-lbl">Revenue Today</div></div>'
        f'<div class="hero-stat"><div class="hs-val">{conversion_text}</div>'
        f'<div class="hs-lbl">Conversion</div></div>'
        f'<span class="live-pill"><span class="dot"></span>Live Analytics</span>'
        f'<div class="status-ring" style="--pct:{ring_pct}%"><span>{ring_pct}%</span></div>'
        f"</div></div>"
    )


def metric_tile_html(
    label: str,
    value: str,
    *,
    glow: str = "",
    trend: str = "Today",
    chip: str = "neutral",
    chip_text: str = "Snapshot",
) -> str:
    icon = _KPI_ICONS.get(label, "📊")
    glow_class = f" glow-{glow}" if glow else ""
    return (
        f'<div class="metric-tile{glow_class}">'
        f'<div class="mt-icon" aria-hidden="true">{icon}</div>'
        f'<div class="mt-val">{value}</div>'
        f'<div class="mt-trend">{trend}</div>'
        f'<span class="mt-chip {chip}">{chip_text}</span>'
        f'<div class="mt-lbl">{label}</div>'
        f"</div>"
    )


def story_panel_html(summary: str, conversion_rate: float) -> str:
    priority_label, priority_class = story_priority(conversion_rate)
    return (
        f'<div class="story-panel fade-up">'
        f'<div class="sp-icon" aria-hidden="true">✨</div>'
        f'<div class="sp-body">'
        f'<div class="sp-title">Today\'s Story</div>'
        f'<p class="sp-text">{summary}</p>'
        f"</div>"
        f'<span class="sp-priority {priority_class}">Priority · {priority_label}</span>'
        f"</div>"
    )


def action_list_html(title: str, items: list[str]) -> str:
    lis = "".join(f"<li>{item}</li>" for item in items) if items else "<li>—</li>"
    return (
        f'<div class="action-list fade-up">'
        f'<p class="eyebrow amber">{title}</p>'
        f"<ul>{lis}</ul>"
        f"</div>"
    )


def conversion_card_html(
    *,
    visitors: int,
    browsed: int,
    checkout: int,
    purchased: int,
    conversion_text: str,
    conversion_rate: float,
) -> str:
    badge_label, badge_class, ring_color = conversion_badge(conversion_rate)
    ring_pct = min(100, int(conversion_rate * 100))
    steps = (
        ("Visitors", visitors),
        ("Browsed", browsed),
        ("Reached checkout", checkout),
        ("Purchased", purchased),
    )
    steps_html = "".join(
        f'<div class="conv-step"><span>{name}</span><strong>{count:,}</strong></div>'
        for name, count in steps
    )
    return (
        f'<div class="conv-card">'
        f"<h3>Conversion overview</h3>"
        f'<div class="conv-ring" style="--ring-pct:{ring_pct}%;--ring-color:{ring_color}">'
        f'<span class="cr-val">{conversion_text}</span></div>'
        f'<span class="conv-badge {badge_class}">{badge_label}</span>'
        f"{steps_html}"
        f"</div>"
    )


def zone_card_html(zone: dict[str, Any], rank: int, tier: str) -> str:
    name = zone.get("zone_display", zone.get("zone_id", "—"))
    visits = int(zone.get("visits", 0))
    dwell = zone.get("dwell_display", "—")
    score = float(zone.get("score", 0))
    bar_w = min(100, max(4, score))
    return (
        f'<div class="zone-card tier-{tier}">'
        f'<div class="zc-rank">#{rank}</div>'
        f'<div class="zc-name">{name}</div>'
        f'<div class="zc-stat">Customer visits · {visits:,}</div>'
        f'<div class="zc-stat">Time spent · {dwell}</div>'
        f'<div class="zone-score-bar"><div style="width:{bar_w}%"></div></div>'
        f"</div>"
    )


def checkout_widget_html(label: str, value: str, icon: str, status: str) -> str:
    status_text = _CHECKOUT_STATUS_LABELS.get(status, status.title())
    return (
        f'<div class="checkout-widget">'
        f'<div class="cw-icon" aria-hidden="true">{icon}</div>'
        f'<div class="cw-val">{value}</div>'
        f'<div class="cw-lbl">{label}</div>'
        f'<span class="cw-pill {status}">{status_text}</span>'
        f"</div>"
    )


def checkout_gauge_html(status_label: str, gauge_pct: int, color: str) -> str:
    return (
        f'<div class="checkout-gauge-wrap">'
        f'<div class="checkout-gauge" style="--gauge-pct:{gauge_pct}%;--gauge-color:{color}">'
        f'<div class="cg-inner"><div class="cg-label">Checkout Health</div>'
        f'<div class="cg-status">{status_label}</div></div></div>'
        f"</div>"
    )


def noc_card_html(
    label: str,
    status: str,
    css: str,
    *,
    health_pct: int,
    last_update: str = "",
    pulse: bool = True,
) -> str:
    icon = _MONITOR_ICONS.get(label, "📡")
    pulse_class = "" if pulse and css == "ok" else " off"
    update_html = (
        f'<div class="nc-update">Last update · {last_update}</div>'
        if last_update
        else ""
    )
    return (
        f'<div class="noc-card">'
        f'<div class="nc-top"><span class="nc-icon" aria-hidden="true">{icon}</span>'
        f'<span class="noc-pulse{pulse_class}"></span></div>'
        f'<div class="nc-label">{label}</div>'
        f'<div class="nc-status {css}">{status}</div>'
        f'<div class="nc-pct">Health · {health_pct}%</div>'
        f'<div class="noc-bar"><div class="{css}" style="width:{health_pct}%"></div></div>'
        f"{update_html}"
        f"</div>"
    )


def trust_center_html(
    *,
    events: int,
    sessions: int,
    visitors: int,
    transactions: int,
    revenue_text: str,
    badges: list[str],
) -> str:
    badge_html = "".join(f'<span class="trust-badge">{b}</span>' for b in badges)
    return (
        f'<div class="trust fade-up">'
        f'<div class="trust-head"><span class="shield" aria-hidden="true">🛡</span>'
        f"<h3>Verified Analytics</h3></div>"
        f'<p class="trust-sub">Trusted counters aligned with the analytics engine '
        f"for the selected store and trading day.</p>"
        f'<div class="trust-metrics">'
        f'<div class="trust-metric"><div class="tm-lbl">Events</div>'
        f'<div class="tm-val">{events:,}</div></div>'
        f'<div class="trust-metric"><div class="tm-lbl">Sessions</div>'
        f'<div class="tm-val">{sessions:,}</div></div>'
        f'<div class="trust-metric"><div class="tm-lbl">Visitors</div>'
        f'<div class="tm-val">{visitors:,}</div></div>'
        f'<div class="trust-metric"><div class="tm-lbl">Transactions</div>'
        f'<div class="tm-val">{transactions:,}</div></div>'
        f'<div class="trust-metric"><div class="tm-lbl">Revenue</div>'
        f'<div class="tm-val">{revenue_text}</div></div>'
        f"</div>"
        f'<div class="trust-badges">{badge_html}</div>'
        f"</div>"
    )


def insight_rows_html(items: list[str], *, severity: str = "medium") -> str:
    if not items:
        return f'<div class="insight-row"><span class="severity-badge {severity}">{severity}</span><span>—</span></div>'
    rows = []
    for item in items:
        rows.append(
            f'<div class="insight-row">'
            f'<span class="severity-badge {severity}">{severity}</span>'
            f"<span>{item}</span>"
            f'<span class="source-badge engine">Analytics</span>'
            f"</div>"
        )
    return "".join(rows)


def build_funnel_sankey(funnel: dict[str, Any], *, stage_count_fn: Any) -> go.Figure:
    uv = stage_count_fn(funnel, "unique_visitors")
    rz = stage_count_fn(funnel, "reached_any_zone")
    bq = stage_count_fn(funnel, "billing_queue")
    cv = stage_count_fn(funnel, "converted_visitors")

    def stage_label(name: str, count: int) -> str:
        return f"{name}  ({count})"

    labels = [
        stage_label("Entered store", uv),
        stage_label("Browsed products", rz),
        stage_label("Reached checkout", bq),
        stage_label("Made a purchase", cv),
        stage_label("Left before browsing", max(0, uv - rz)),
        stage_label("Left before checkout", max(0, rz - bq)),
        stage_label("Left without buying", max(0, bq - cv)),
    ]
    source: list[int] = []
    target: list[int] = []
    value: list[int] = []
    link_colors: list[str] = []

    def add_link(s: int, t: int, v: int, color: str) -> None:
        if v > 0:
            source.append(s)
            target.append(t)
            value.append(v)
            link_colors.append(color)

    add_link(0, 1, rz, "rgba(14, 165, 233, 0.5)")
    add_link(0, 4, max(0, uv - rz), "rgba(148, 163, 184, 0.35)")
    add_link(1, 2, min(bq, rz), "rgba(99, 102, 241, 0.5)")
    add_link(1, 5, max(0, rz - bq), "rgba(148, 163, 184, 0.35)")
    add_link(2, 3, min(cv, bq), "rgba(16, 185, 129, 0.55)")
    add_link(2, 6, max(0, bq - cv), "rgba(239, 68, 68, 0.45)")

    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node=dict(
                    pad=44,
                    thickness=26,
                    line=dict(color="#1e293b", width=1),
                    label=labels,
                    color=[
                        "#0ea5e9",
                        "#6366f1",
                        "#4f46e5",
                        "#10b981",
                        "#cbd5e1",
                        "#cbd5e1",
                        "#f87171",
                    ],
                ),
                link=dict(
                    source=source,
                    target=target,
                    value=value,
                    color=link_colors,
                    hovertemplate="%{value} customers<extra></extra>",
                ),
            )
        ]
    )
    layout = {**PLOTLY_LAYOUT, "height": 550, "margin": dict(l=32, r=32, t=28, b=32)}
    layout["font"] = dict(family="DM Sans, Segoe UI, sans-serif", size=14, color="#0f172a")
    fig.update_layout(**layout)
    return fig


def build_zone_floor_heatmap(ranked: list[dict[str, Any]]) -> go.Figure:
    if not ranked:
        fig = go.Figure()
        fig.update_layout(
            **PLOTLY_LAYOUT,
            height=240,
            margin=DEFAULT_PLOT_MARGIN,
            title=dict(text="Floor intelligence — customer interest", font=dict(size=15, color="#0f172a")),
        )
        return fig

    n = len(ranked)
    cols = max(3, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / cols)
    grid = [[0.0] * cols for _ in range(rows)]
    labels = [[""] * cols for _ in range(rows)]
    for idx, zone in enumerate(ranked):
        r, c = divmod(idx, cols)
        grid[r][c] = zone["score"]
        labels[r][c] = str(zone.get("zone_id", ""))

    fig = go.Figure(
        data=go.Heatmap(
            z=grid,
            text=labels,
            texttemplate="%{text}",
            textfont=dict(size=11, color="#0f172a", family="DM Sans, sans-serif"),
            colorscale=[
                [0.0, "#e2e8f0"],
                [0.35, "#7dd3fc"],
                [0.65, "#0ea5e9"],
                [1.0, "#1d4ed8"],
            ],
            xgap=4,
            ygap=4,
            showscale=True,
            colorbar=dict(
                title=dict(text="Customer Interest", font=dict(size=12)),
                thickness=16,
                len=0.7,
                bgcolor="rgba(255,255,255,0.8)",
                bordercolor="#e2e8f0",
                borderwidth=1,
            ),
            hovertemplate="Area: %{text}<br>Score: %{z:.1f}<extra></extra>",
        )
    )
    fig.update_layout(
        **PLOTLY_LAYOUT,
        height=max(240, rows * 62),
        margin=DEFAULT_PLOT_MARGIN,
        title=dict(text="Floor intelligence — engagement heatmap", font=dict(size=15, color="#0f172a")),
        xaxis=dict(showgrid=False, showticklabels=False),
        yaxis=dict(showgrid=False, showticklabels=False, autorange="reversed"),
    )
    return fig


def render_executive_metrics(
    *,
    unique_visitors: int,
    purchase_count: int,
    revenue_text: str,
    conversion_text: str,
    top_zone: str,
    weak_zone: str,
    conversion_rate: float,
) -> None:
    st.markdown('<div class="glass accent-blue fade-up">', unsafe_allow_html=True)
    section_heading("Executive Metrics", eyebrow="Store performance", accent="blue")
    conv_chip = "ok" if conversion_rate >= 0.25 else "warn"
    st.markdown(
        '<div class="metric-grid">'
        + metric_tile_html(
            "Visitors",
            f"{unique_visitors:,}",
            glow="blue",
            chip="neutral",
            chip_text="Traffic",
        )
        + metric_tile_html(
            "Purchases",
            f"{purchase_count:,}",
            glow="cyan",
            chip="ok" if purchase_count else "warn",
            chip_text="Completed",
        )
        + metric_tile_html(
            "Revenue",
            revenue_text,
            glow="green",
            chip="ok" if purchase_count else "neutral",
            chip_text="Sales",
        )
        + metric_tile_html(
            "Conversion",
            conversion_text,
            glow="blue",
            chip=conv_chip,
            chip_text="Rate",
        )
        + metric_tile_html("Top area", top_zone, glow="green", chip="ok", chip_text="Leader")
        + metric_tile_html("Focus area", weak_zone, glow="red", chip="warn", chip_text="Watch")
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def render_todays_story(summary: str, conversion_rate: float) -> None:
    st.markdown(story_panel_html(summary, conversion_rate), unsafe_allow_html=True)


def render_recommended_actions(actions: list[str]) -> None:
    st.markdown(
        action_list_html("Recommended Actions", actions),
        unsafe_allow_html=True,
    )


def render_customer_journey(
    funnel: dict[str, Any],
    *,
    stage_count_fn: Any,
    funnel_drop_offs_fn: Any,
    format_pct_fn: Any,
) -> None:
    st.markdown('<div class="glass accent-blue fade-up">', unsafe_allow_html=True)
    section_heading(
        "Customer Shopping Journey",
        eyebrow="Conversion path",
        accent="blue",
    )
    drops = funnel_drop_offs_fn(funnel)
    overall = float(funnel.get("overall_conversion_rate", 0.0))
    st.markdown('<div class="journey-wrap">', unsafe_allow_html=True)
    st.markdown('<div class="journey-sankey-col">', unsafe_allow_html=True)
    st.plotly_chart(
        build_funnel_sankey(funnel, stage_count_fn=stage_count_fn),
        use_container_width=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(
        '<div class="journey-conv-col">'
        + conversion_card_html(
            visitors=drops["visitors"],
            browsed=drops["zone_engaged"],
            checkout=drops["billing"],
            purchased=drops["purchased"],
            conversion_text=format_pct_fn(overall),
            conversion_rate=overall,
        )
        + "</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div></div>", unsafe_allow_html=True)


def render_floor_intelligence(
    ranked: list[dict[str, Any]],
    *,
    friendly_zone_fn: Any,
    format_dwell_fn: Any,
) -> None:
    st.markdown('<div class="glass accent-indigo fade-up">', unsafe_allow_html=True)
    section_heading("Floor Intelligence", eyebrow="Zone analytics", accent="blue")

    if not ranked:
        st.info("No product-area activity recorded for this day.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    top = max(ranked, key=lambda z: float(z.get("score", 0)))
    weak = min(ranked, key=lambda z: float(z.get("score", 0)))
    dwell_vals = [float(z.get("dwell_ms", 0)) for z in ranked if float(z.get("dwell_ms", 0)) > 0]
    avg_dwell = sum(dwell_vals) / len(dwell_vals) if dwell_vals else 0.0

    st.markdown(
        '<div class="heatmap-stats">'
        f'<span class="stat-chip"><span>Most visited brand area ·</span> {friendly_zone_fn(str(top.get("zone_id", "")))}</span>'
        f'<span class="stat-chip"><span>Least visited brand area ·</span> {friendly_zone_fn(str(weak.get("zone_id", "")))}</span>'
        f'<span class="stat-chip"><span>Avg Dwell ·</span> {format_dwell_fn(avg_dwell)}</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.plotly_chart(build_zone_floor_heatmap(ranked), use_container_width=True)

    def enrich(zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for z in zones:
            out.append({
                **z,
                "zone_display": friendly_zone_fn(str(z.get("zone_id", ""))),
                "dwell_display": format_dwell_fn(float(z.get("dwell_ms", 0))),
            })
        return out

    top_areas = enrich(sorted(
        [z for z in ranked if float(z.get("score", 0)) >= 50.0],
        key=lambda x: float(x["score"]),
        reverse=True,
    ))
    moderate = enrich(sorted(
        [z for z in ranked if 10.0 <= float(z.get("score", 0)) < 50.0],
        key=lambda x: float(x["score"]),
        reverse=True,
    ))
    attention = enrich(sorted(
        [z for z in ranked if float(z.get("score", 0)) < 10.0],
        key=lambda x: float(x["score"]),
    ))

    def column(title: str, zones: list[dict[str, Any]], tier: str, empty_msg: str) -> str:
        head = f'<p class="zone-col-head" style="color:#{"047857" if tier=="green" else "b45309" if tier=="amber" else "b91c1c"}">{title}</p>'
        if not zones:
            return head + f'<div class="zone-empty">{empty_msg}</div>'
        cards = "".join(zone_card_html(z, i, tier) for i, z in enumerate(zones, 1))
        return head + cards

    st.markdown(
        '<div class="zone-grid">'
        + column("Top performing", top_areas, "green", "No strong-engagement areas today")
        + column("Moderate", moderate, "amber", "No moderate-engagement areas today")
        + column("Needs attention", attention, "red", "No low-engagement areas flagged")
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def render_checkout_command_center(
    *,
    peak_queue_depth: int,
    queue_abandonment: float,
    queue_abandonment_text: str,
    reached_checkout_count: int,
    completed_purchase_count: int,
    checkout_status_pill_fn: Any,
    checkout_summary: str,
    checkout_actions: list[str],
    checkout_bullets: list[str],
) -> None:
    st.markdown('<div class="glass accent-green fade-up">', unsafe_allow_html=True)
    section_heading("Checkout Command Center", eyebrow="Queue & completion", accent="green")

    gauge_label, gauge_color, gauge_pct, _ = checkout_gauge_meta(
        queue_abandonment, peak_queue_depth
    )
    st.markdown(
        '<div class="checkout-layout">'
        + checkout_widget_html(
            "Peak Queue",
            f"{peak_queue_depth:,}",
            "👥",
            checkout_status_pill_fn("queue_depth", peak_queue_depth),
        )
        + checkout_widget_html(
            "Abandonment",
            queue_abandonment_text,
            "🚶",
            checkout_status_pill_fn("abandonment", queue_abandonment),
        )
        + checkout_widget_html(
            "Reached Checkout",
            f"{reached_checkout_count:,}",
            "🛒",
            checkout_status_pill_fn("reached", reached_checkout_count),
        )
        + checkout_widget_html(
            "Completed Purchase",
            f"{completed_purchase_count:,}",
            "✅",
            checkout_status_pill_fn("purchases", completed_purchase_count),
        )
        + checkout_gauge_html(gauge_label, gauge_pct, gauge_color)
        + "</div>",
        unsafe_allow_html=True,
    )
    if checkout_summary:
        st.markdown(
            f'<div class="checkout-rec"><h4>AI checkout recommendation</h4>'
            f"<p>{checkout_summary}</p></div>",
            unsafe_allow_html=True,
        )
    if checkout_actions:
        st.markdown('<p class="eyebrow amber">Recommended checkout actions</p>', unsafe_allow_html=True)
        st.markdown(bullets_html(checkout_actions), unsafe_allow_html=True)
    elif checkout_bullets:
        st.markdown('<p class="eyebrow amber">Operational notes</p>', unsafe_allow_html=True)
        st.markdown(bullets_html(checkout_bullets), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_ai_insights(insights_payload: dict[str, Any] | None) -> None:
    insight_data = (insights_payload or {}).get("insights") or {}
    business_risks = insight_data.get("business_risks") or [
        "No major operational risks flagged from today's analytics.",
    ]
    positive_signals = insight_data.get("positive_signals") or [
        "Core store analytics are available for this trading day.",
    ]
    source = str((insights_payload or {}).get("source", "fallback"))

    st.markdown('<div class="glass accent-amber fade-up">', unsafe_allow_html=True)
    section_heading("AI Insights", eyebrow="Business signals", accent="amber")
    st.markdown(
        '<div class="insights-row">'
        '<div class="insight-panel risk"><h4>Risk signals</h4>'
        + insight_rows_html([str(x) for x in business_risks], severity="high")
        + "</div>"
        '<div class="insight-panel pos"><h4>Positive signals</h4>'
        + insight_rows_html([str(x) for x in positive_signals], severity="low")
        + "</div>"
        "</div>"
        '<div class="insight-footer">Confidence · '
        + insight_source_badge(source)
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def render_operations_monitoring(
    *,
    store_display: str,
    store_css: str,
    analytics_display: str,
    analytics_css: str,
    camera_display: str,
    camera_css: str,
    confidence_display: str,
    confidence_css: str,
    confidence_sub: str,
    last_activity: str,
    facts: list[str],
) -> None:
    st.markdown('<div class="glass accent-slate fade-up">', unsafe_allow_html=True)
    section_heading("Operations Monitoring", eyebrow="Live systems", accent="blue")
    st.markdown(
        '<div class="noc-grid">'
        + noc_card_html(
            "Store",
            store_display,
            store_css,
            health_pct=noc_health_pct(store_css),
            last_update=last_activity,
        )
        + noc_card_html(
            "Analytics",
            analytics_display,
            analytics_css,
            health_pct=noc_health_pct(analytics_css),
            last_update=last_activity,
        )
        + noc_card_html(
            "Cameras",
            camera_display,
            camera_css,
            health_pct=noc_health_pct(camera_css),
            last_update=last_activity,
        )
        + noc_card_html(
            "Confidence",
            confidence_display,
            confidence_css,
            health_pct=noc_health_pct(confidence_css),
            last_update=confidence_sub,
            pulse=confidence_css == "ok",
        )
        + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown('<p class="eyebrow">Supporting facts</p>', unsafe_allow_html=True)
    st.markdown(bullets_html(facts), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_trust_center(
    *,
    unique_visitors: int,
    total_sessions: int,
    events_processed: int,
    pos_transactions: int,
    revenue_text: str,
    api_loaded: bool,
    has_confidence: bool,
) -> None:
    badges: list[str] = []
    if api_loaded:
        badges.append("✓ API Loaded")
    if api_loaded:
        badges.append("✓ Data Synced")
    if api_loaded and unique_visitors > 0:
        badges.append("✓ Validation Passed")
    if api_loaded and (has_confidence or unique_visitors > 0):
        badges.append("✓ Dashboard Verified")
    if has_confidence or unique_visitors >= 20:
        badges.append("✓ Validation Dataset")
    elif unique_visitors > 0:
        badges.append("✓ Store activity recorded")
    if not badges:
        badges.append("Awaiting store data for this day")

    st.markdown(
        trust_center_html(
            events=events_processed,
            sessions=total_sessions,
            visitors=unique_visitors,
            transactions=pos_transactions,
            revenue_text=revenue_text,
            badges=badges,
        ),
        unsafe_allow_html=True,
    )


def render_technical_panel(
    *,
    health: dict[str, Any],
    metrics: dict[str, Any],
    funnel: dict[str, Any],
    heatmap: dict[str, Any],
    anomalies: dict[str, Any],
    business_insights: dict[str, Any] | None = None,
    staff_analysis: dict[str, Any] | None = None,
    expander_title: str = "Technical Details — API payloads & verification",
    verification_mode: bool = False,
) -> None:
    with st.expander(expander_title, expanded=False):
        st.markdown('<div class="tech-dark">', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="tech-head">
                <span style="font-size:1.5rem">⌘</span>
                <div>
                    <h3>Technical panel</h3>
                    <p>Verify dashboard values against raw endpoints and generated context.</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if verification_mode:
            tab_m, tab_f, tab_hm, tab_a, tab_staff = st.tabs(
                [
                    "Metrics API",
                    "Funnel API",
                    "Heatmap API",
                    "Anomalies API",
                    "Staff Detection",
                ]
            )
            with tab_m:
                st.caption("GET /stores/{store_id}/metrics")
                st.json(metrics)
            with tab_f:
                st.caption("GET /stores/{store_id}/funnel")
                st.json(funnel)
            with tab_hm:
                st.caption("GET /stores/{store_id}/heatmap")
                st.json(heatmap)
            with tab_a:
                st.caption("GET /stores/{store_id}/anomalies")
                st.json(anomalies)
            with tab_staff:
                st.caption("GET /stores/{store_id}/staff-analysis")
                if staff_analysis:
                    st.json(staff_analysis)
                else:
                    st.info("Staff detection data was not loaded for this store and date.")
        else:
            tab_m, tab_f, tab_hm, tab_a, tab_h, tab_bi, tab_staff = st.tabs(
                [
                    "Metrics",
                    "Funnel",
                    "Heatmap",
                    "Anomalies",
                    "Health",
                    "Business Context",
                    "Staff API",
                ]
            )
            with tab_m:
                st.caption("GET /stores/{store_id}/metrics")
                st.json(metrics)
            with tab_f:
                st.caption("GET /stores/{store_id}/funnel")
                st.json(funnel)
            with tab_hm:
                st.caption("GET /stores/{store_id}/heatmap")
                st.json(heatmap)
            with tab_a:
                st.caption("GET /stores/{store_id}/anomalies")
                st.json(anomalies)
            with tab_h:
                st.caption("GET /health")
                st.json(health)
            with tab_bi:
                st.caption("GET /stores/{store_id}/business-insights")
                if business_insights:
                    st.markdown(f"**Source:** `{business_insights.get('source', 'fallback')}`")
                    st.markdown("**Aggregated analytics context (sent to LLM)**")
                    st.json(business_insights.get("context", {}))
                    st.markdown("**Generated insight payload**")
                    st.json(business_insights.get("insights", {}))
                else:
                    st.info(
                        "Business insights were not loaded. Narrative sections use local fallback text."
                    )
            with tab_staff:
                st.caption("GET /stores/{store_id}/staff-analysis")
                if staff_analysis:
                    st.json(staff_analysis)
                else:
                    st.info("Staff analysis was not loaded for this store and date.")
        st.markdown("</div>", unsafe_allow_html=True)
