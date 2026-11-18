#!/usr/bin/env python3
"""Generate charts for SecureCore IDS — Final Academic Evaluation Report (PostgreSQL)."""

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from pathlib import Path

# ─── Output directory ───
OUT_DIR = Path(__file__).parent / "charts"
OUT_DIR.mkdir(exist_ok=True)

# ─── Style ───
plt.style.use('seaborn-v0_8-whitegrid')
COLORS = {
    'primary':  '#2563eb',
    'danger':   '#dc2626',
    'warning':  '#f59e0b',
    'success':  '#10b981',
    'purple':   '#7c3aed',
    'gray':     '#6b7280',
    'teal':     '#14b8a6',
}

# ─── Optimised PostgreSQL test data ───
PG_DATA = {
    10:  {'median': 34,    'p95': 100,   'p99': 140,   'max': 170,   'rps': 27.9, 'err': 0.0},
    20:  {'median': 23000, 'p95': 37000, 'p99': 39000, 'max': 39000, 'rps': 17.7, 'err': 0.0},
    30:  {'median': 14000, 'p95': 46000, 'p99': 49000, 'max': 49000, 'rps': 13.6, 'err': 0.0},
    50:  {'median': 47000, 'p95': 50000, 'p99': 51000, 'max': 56000, 'rps': 21.3, 'err': 68.4},
    100: {'median': 30000, 'p95': 45000, 'p99': 45000, 'max': 45000, 'rps': 1.8,  'err': 3.9},
}

USERS = sorted(PG_DATA.keys())


def chart_baseline_latency():
    """Baseline latency bar chart for 10-user regulated-rate test."""
    labels = ['Median', 'P95', 'P99', 'Max']
    values = [34, 100, 140, 170]
    colors = [COLORS['success'], COLORS['primary'], COLORS['warning'], COLORS['danger']]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=colors, alpha=0.85, edgecolor='white', linewidth=1.5)

    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, v + 3, f'{v} ms',
                ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax.set_ylabel('Response Time (ms)', fontsize=12, fontweight='bold')
    ax.set_title('Baseline Inference Latency — 10 Concurrent Sensors\n'
                 '(PostgreSQL 16 + Connection Pooling + Async DB Writes)',
                 fontsize=13, fontweight='bold')
    ax.set_ylim(0, 220)
    ax.grid(True, alpha=0.3, axis='y')

    # Add annotation
    ax.annotate('Zero errors (894 inferences)',
                xy=(0, 34), xytext=(1.5, 160),
                arrowprops=dict(arrowstyle='->', color=COLORS['success'], lw=1.5),
                fontsize=10, color=COLORS['success'], fontweight='bold',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#d1fae5', edgecolor=COLORS['success']))

    plt.tight_layout()
    fig.savefig(OUT_DIR / 'baseline_latency.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("  ✅ baseline_latency.png")


def chart_latency_vs_users():
    """Latency percentiles (median + P99) vs concurrent sensors."""
    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(USERS, [PG_DATA[u]['median'] for u in USERS], 'o-',
            color=COLORS['primary'], linewidth=2.5, markersize=7, label='Median Latency')
    ax.plot(USERS, [PG_DATA[u]['p99'] for u in USERS], 'D-',
            color=COLORS['danger'], linewidth=2.5, markersize=7, label='P99 Latency')

    ax.axhline(y=1000, color=COLORS['danger'], linestyle=':', alpha=0.5,
               linewidth=1.5, label='1-second threshold')

    # Shade the "healthy" zone
    ax.fill_between([5, 15], 0, 1000, alpha=0.06, color=COLORS['success'])
    ax.annotate('Healthy Zone\n(< 1 second)', xy=(10, 500), fontsize=10,
                ha='center', color=COLORS['success'], fontweight='bold')

    ax.set_xlabel('Concurrent Sensors (high-frequency: 2–5 req/s each)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Response Time (ms)', fontsize=12, fontweight='bold')
    ax.set_title('Inference Latency vs. Concurrent Sensors\n'
                 '(PostgreSQL 16 + Connection Pooling)',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_yscale('log')
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))

    plt.tight_layout()
    fig.savefig(OUT_DIR / 'latency_vs_users.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("  ✅ latency_vs_users.png")


def chart_throughput_vs_users():
    """Throughput (req/s) bar chart."""
    labels = [str(u) for u in USERS]
    rps = [PG_DATA[u]['rps'] for u in USERS]

    fig, ax = plt.subplots(figsize=(10, 6))

    bar_colors = [COLORS['success'] if r > 20 else COLORS['primary'] if r > 10 else COLORS['warning'] for r in rps]
    bars = ax.bar(labels, rps, color=bar_colors, alpha=0.85, edgecolor='white', linewidth=1.5)

    for bar, v in zip(bars, rps):
        ax.text(bar.get_x() + bar.get_width()/2, v + 0.3, f'{v:.1f}',
                ha='center', va='bottom', fontsize=9, fontweight='bold')

    ax.set_xlabel('Concurrent Sensors', fontsize=12, fontweight='bold')
    ax.set_ylabel('Throughput (inferences/s)', fontsize=12, fontweight='bold')
    ax.set_title('Inference Throughput vs. Concurrent Sensors', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    fig.savefig(OUT_DIR / 'throughput_vs_users.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("  ✅ throughput_vs_users.png")


def chart_error_rate():
    """Error rate bar chart."""
    labels = [str(u) for u in USERS]
    errors = [PG_DATA[u]['err'] for u in USERS]

    fig, ax = plt.subplots(figsize=(10, 6))

    bar_colors = [COLORS['danger'] if e > 5 else COLORS['warning'] if e > 1 else COLORS['success'] for e in errors]
    bars = ax.bar(labels, errors, color=bar_colors, alpha=0.85, edgecolor='white', linewidth=1.5)

    ax.axhline(y=5, color=COLORS['danger'], linestyle='--', alpha=0.5,
               linewidth=1.5, label='5% Error Threshold')

    for bar, v in zip(bars, errors):
        if v > 0:
            ax.text(bar.get_x() + bar.get_width()/2, v + 1, f'{v:.1f}%',
                    ha='center', va='bottom', fontsize=9, fontweight='bold')
        else:
            ax.text(bar.get_x() + bar.get_width()/2, v + 1, '0%',
                    ha='center', va='bottom', fontsize=9, fontweight='bold', color=COLORS['success'])

    ax.set_xlabel('Concurrent Sensors', fontsize=12, fontweight='bold')
    ax.set_ylabel('Error Rate (%)', fontsize=12, fontweight='bold')
    ax.set_title('Inference Error Rate vs. Concurrent Sensors', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    fig.savefig(OUT_DIR / 'error_rate_vs_users.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("  ✅ error_rate_vs_users.png")


def chart_breaking_point():
    """Breaking point — P99 vs median with annotated zones."""
    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(USERS, [PG_DATA[u]['p99'] for u in USERS], 'D-',
            color=COLORS['danger'], linewidth=2.5, markersize=8, label='P99 Latency', zorder=3)
    ax.plot(USERS, [PG_DATA[u]['median'] for u in USERS], 'o-',
            color=COLORS['primary'], linewidth=2, markersize=6, label='Median Latency', zorder=3)

    # Threshold
    ax.axhline(y=1000, color=COLORS['danger'], linestyle=':', alpha=0.6,
               linewidth=2, label='Breaking Point (1000ms)')

    # Fill above threshold
    ax.fill_between(USERS, 1000, [max(PG_DATA[u]['p99'], 1000) for u in USERS],
                     alpha=0.08, color=COLORS['danger'])

    # Annotate breaking point
    ax.annotate('Breaking Point\n~20 sensors (high-freq)',
                xy=(20, 39000), xytext=(55, 15000),
                arrowprops=dict(arrowstyle='->', color=COLORS['danger'], lw=2),
                fontsize=11, fontweight='bold', color=COLORS['danger'],
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#fef2f2', edgecolor=COLORS['danger']))

    # Annotate healthy zone
    ax.annotate('✓ 34ms median\n   0% errors',
                xy=(10, 140), xytext=(15, 80),
                fontsize=10, fontweight='bold', color=COLORS['success'],
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#d1fae5', edgecolor=COLORS['success']))

    ax.set_xlabel('Concurrent Sensors (2–5 req/s each)', fontsize=12, fontweight='bold')
    ax.set_ylabel('Response Time (ms)', fontsize=12, fontweight='bold')
    ax.set_title('Stress-to-Fail: Finding the Breaking Point\n'
                 '(PostgreSQL 16 · Docker · EC2 t3.medium limits)',
                 fontsize=13, fontweight='bold')
    ax.legend(loc='center right', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_yscale('log')
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))

    plt.tight_layout()
    fig.savefig(OUT_DIR / 'breaking_point.png', dpi=200, bbox_inches='tight')
    plt.close(fig)
    print("  ✅ breaking_point.png")


if __name__ == '__main__':
    print("\nGenerating academic evaluation charts (PostgreSQL)...")

    chart_baseline_latency()
    chart_latency_vs_users()
    chart_throughput_vs_users()
    chart_error_rate()
    chart_breaking_point()

    print(f"\n✅ All charts saved to: {OUT_DIR}")
