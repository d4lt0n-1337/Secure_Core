#!/usr/bin/env python3
"""
SecureCore IDS — Stepped Stress Test
Runs clean per-level tests at specific user counts.
Each level runs for 90s with 15s cooldown between levels.

Usage:
  python run_stepped_test.py --host http://localhost:5000
"""

import subprocess
import os
import csv
import time
import sys
from pathlib import Path
from datetime import datetime


LEVELS = [10, 20, 30, 40, 50, 75, 100]
DURATION = "90s"
SPAWN_RATE = 10


def run_test(host, users, results_dir):
    label = f"step_{users}u"
    csv_prefix = str(results_dir / label)

    cmd = [
        "locust",
        "-f", "locustfile_stress.py",
        "--host", host,
        "--headless",
        "-u", str(users),
        "-r", str(min(users, SPAWN_RATE)),
        "-t", DURATION,
        "--csv", csv_prefix,
        "--csv-full-history",
    ]

    print(f"\n{'='*60}")
    print(f"  Level: {users} concurrent users")
    print(f"{'='*60}")

    subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)), timeout=300)
    return csv_prefix


def parse_stats(csv_prefix):
    stats_file = f"{csv_prefix}_stats.csv"
    if not os.path.exists(stats_file):
        return {}

    with open(stats_file) as f:
        for row in csv.DictReader(f):
            if row.get("Name") == "inference_result":
                total = int(row.get("Request Count", 0))
                fails = int(row.get("Failure Count", 0))
                return {
                    "total": total,
                    "failures": fails,
                    "error_pct": (fails / total * 100) if total > 0 else 0,
                    "median": float(row.get("Median Response Time", 0)),
                    "avg": float(row.get("Average Response Time", 0)),
                    "min": float(row.get("Min Response Time", 0)),
                    "max": float(row.get("Max Response Time", 0)),
                    "p50": float(row.get("50%", 0)),
                    "p90": float(row.get("90%", 0)),
                    "p95": float(row.get("95%", 0)),
                    "p99": float(row.get("99%", 0)),
                    "rps": float(row.get("Requests/s", 0)),
                }
    return {}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://localhost:5000")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(__file__).parent / "results" / f"stepped_{ts}"
    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nSecureCore IDS — Stepped Stress Test")
    print(f"Levels: {LEVELS} users")
    print(f"Results: {results_dir}")

    all_results = []

    for users in LEVELS:
        prefix = run_test(args.host, users, results_dir)
        m = parse_stats(prefix)
        all_results.append((users, m))

        # Check breaking point
        if m:
            if m.get("p99", 0) > 1000:
                print(f"\n⚠  BREAKING POINT: P99 = {m['p99']:.0f}ms > 1000ms at {users} users")
            if m.get("error_pct", 0) > 5:
                print(f"\n⚠  BREAKING POINT: Error rate = {m['error_pct']:.1f}% > 5% at {users} users")

        print("\n  ⏳ Cooling down 15s...")
        time.sleep(15)

    # Print summary table
    print(f"\n{'='*90}")
    print(f"{'Users':>8} | {'Total':>7} | {'Median':>8} | {'P90':>8} | {'P95':>8} | {'P99':>8} | {'Max':>8} | {'RPS':>6} | {'Err%':>6}")
    print("-" * 90)
    for users, m in all_results:
        if m:
            print(f"{users:>8} | {m['total']:>7} | {m['median']:>7.0f}ms | {m['p90']:>7.0f}ms | {m['p95']:>7.0f}ms | {m['p99']:>7.0f}ms | {m['max']:>7.0f}ms | {m['rps']:>6.1f} | {m['error_pct']:>5.1f}%")

    # Save summary CSV
    summary_file = results_dir / "summary.csv"
    with open(summary_file, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["users", "total_requests", "median_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms", "rps", "error_pct"])
        for users, m in all_results:
            if m:
                w.writerow([users, m["total"], m["median"], m["p90"], m["p95"], m["p99"], m["max"], f"{m['rps']:.2f}", f"{m['error_pct']:.2f}"])

    print(f"\n✅ Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
