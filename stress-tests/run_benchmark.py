#!/usr/bin/env python3
"""
SecureCore IDS — Automated Benchmark Runner
Runs Locust at multiple concurrency levels and collects CSV data
for research paper evaluation section.

Output:
  results/
    test_10users_stats.csv
    test_50users_stats.csv
    test_100users_stats.csv
    test_200users_stats.csv
    summary.csv          ← aggregated results for paper

Usage:
  pip install -r requirements.txt
  python run_benchmark.py [--host http://localhost:5000]
"""

import subprocess
import os
import sys
import csv
import time
import argparse
from pathlib import Path
from datetime import datetime


# ─── Benchmark Configuration ───
BENCHMARK_CONFIGS = [
    {"users": 10,  "spawn_rate": 2,   "duration": "60s",  "label": "10users"},
    {"users": 50,  "spawn_rate": 5,   "duration": "120s", "label": "50users"},
    {"users": 100, "spawn_rate": 10,  "duration": "120s", "label": "100users"},
    {"users": 200, "spawn_rate": 20,  "duration": "120s", "label": "200users"},
]


def run_locust_test(host: str, config: dict, results_dir: Path):
    """Run a single Locust test and save CSV output."""
    label = config["label"]
    csv_prefix = str(results_dir / f"test_{label}")

    cmd = [
        "locust",
        "-f", "locustfile.py",
        "--host", host,
        "--headless",
        "-u", str(config["users"]),
        "-r", str(config["spawn_rate"]),
        "-t", config["duration"],
        "--csv", csv_prefix,
        "--csv-full-history",
    ]

    print(f"\n{'='*60}")
    print(f"  Running: {config['users']} users, spawn rate {config['spawn_rate']}/s, {config['duration']}")
    print(f"  Output:  {csv_prefix}_stats.csv")
    print(f"{'='*60}\n")

    result = subprocess.run(
        cmd,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        timeout=600,
    )

    if result.returncode != 0:
        print(f"  ⚠ Locust test '{label}' finished with exit code {result.returncode}")

    return csv_prefix


def parse_stats_csv(csv_prefix: str) -> dict:
    """Parse Locust stats CSV and extract key metrics."""
    stats_file = f"{csv_prefix}_stats.csv"
    if not os.path.exists(stats_file):
        return {}

    metrics = {}
    with open(stats_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Name") == "Aggregated":
                metrics = {
                    "total_requests": int(row.get("Request Count", 0)),
                    "failure_count": int(row.get("Failure Count", 0)),
                    "median_ms": float(row.get("Median Response Time", 0)),
                    "avg_ms": float(row.get("Average Response Time", 0)),
                    "min_ms": float(row.get("Min Response Time", 0)),
                    "max_ms": float(row.get("Max Response Time", 0)),
                    "p50_ms": float(row.get("50%", 0)),
                    "p90_ms": float(row.get("90%", 0)),
                    "p95_ms": float(row.get("95%", 0)),
                    "p99_ms": float(row.get("99%", 0)),
                    "rps": float(row.get("Requests/s", 0)),
                    "failures_per_s": float(row.get("Failures/s", 0)),
                }
                break
    return metrics


def create_summary(results_dir: Path, all_results: list):
    """Create a summary CSV with all benchmark results."""
    summary_file = results_dir / "summary.csv"

    headers = [
        "concurrent_users", "spawn_rate", "duration",
        "total_requests", "failure_count", "error_rate_%",
        "median_ms", "avg_ms", "min_ms", "max_ms",
        "p50_ms", "p90_ms", "p95_ms", "p99_ms",
        "rps", "failures_per_s",
    ]

    with open(summary_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()

        for config, metrics in all_results:
            if not metrics:
                continue

            total = metrics.get("total_requests", 0)
            failures = metrics.get("failure_count", 0)
            error_rate = (failures / total * 100) if total > 0 else 0

            row = {
                "concurrent_users": config["users"],
                "spawn_rate": config["spawn_rate"],
                "duration": config["duration"],
                "total_requests": total,
                "failure_count": failures,
                "error_rate_%": f"{error_rate:.2f}",
                **{k: metrics.get(k, 0) for k in headers[6:]},
            }
            writer.writerow(row)

    print(f"\n{'='*60}")
    print(f"  Summary saved to: {summary_file}")
    print(f"{'='*60}")

    # Print table to console
    print(f"\n{'Concurrent Users':>20} | {'Median (ms)':>12} | {'P95 (ms)':>10} | {'P99 (ms)':>10} | {'RPS':>10} | {'Error %':>10}")
    print("-" * 90)
    for config, metrics in all_results:
        if metrics:
            total = metrics.get("total_requests", 0)
            failures = metrics.get("failure_count", 0)
            error_rate = (failures / total * 100) if total > 0 else 0
            print(
                f"{config['users']:>20} | {metrics.get('median_ms', 0):>12.1f} | "
                f"{metrics.get('p95_ms', 0):>10.1f} | {metrics.get('p99_ms', 0):>10.1f} | "
                f"{metrics.get('rps', 0):>10.1f} | {error_rate:>9.2f}%"
            )


def main():
    parser = argparse.ArgumentParser(description="SecureCore IDS Benchmark Runner")
    parser.add_argument("--host", default="http://localhost:5000", help="Backend URL")
    parser.add_argument("--levels", nargs="+", type=int, help="Override user levels (e.g., --levels 10 50)")
    args = parser.parse_args()

    # Create results directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(__file__).parent / "results" / timestamp
    results_dir.mkdir(parents=True, exist_ok=True)

    configs = BENCHMARK_CONFIGS
    if args.levels:
        configs = [c for c in configs if c["users"] in args.levels]

    print(f"\nSecureCore IDS — Stress Test Benchmark")
    print(f"Host:          {args.host}")
    print(f"Results dir:   {results_dir}")
    print(f"Test levels:   {[c['users'] for c in configs]} concurrent users")
    print(f"Started at:    {datetime.now().isoformat()}")

    all_results = []
    for config in configs:
        csv_prefix = run_locust_test(args.host, config, results_dir)
        metrics = parse_stats_csv(csv_prefix)
        all_results.append((config, metrics))

        # Cool-down between tests
        print("\n  ⏳ Cooling down for 10 seconds...")
        time.sleep(10)

    create_summary(results_dir, all_results)
    print(f"\n✅ All benchmarks complete! Results in: {results_dir}")


if __name__ == "__main__":
    main()
