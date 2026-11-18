#!/usr/bin/env python3
"""Live network flow feature extractor (LycoSTand-compatible).

Captures live packets (no PCAP/offline mode) and exports per-flow features
matching the Lycos-IDS2017 feature set (72 features).

Design goals:
- Do NOT store payloads; store only minimal per-packet fields required.
- Use bounded queues to avoid unbounded memory growth.
- Use threads: one capture thread, one aggregator thread, N export worker threads.

Notes
- Requires root or CAP_NET_RAW for live sniffing.
- Uses Scapy for packet capture/parsing.

Output
- CSV with the exact feature header order requested by the user.

"""

from __future__ import annotations

import argparse
import csv
import math
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

try:
    import socketio  # type: ignore
except Exception:
    socketio = None


MICROSECONDS = 1_000_000.0


def _fmt_value(name: str, value: float) -> str:
    """Format values in a LycoSTand-compatible way.

    - Keep integer-like fields as integers.
    - Keep most floats at 6 decimals.
    - Use scientific notation for very large/small magnitudes.
    """

    int_like = {
        "fwd_pkt_cnt",
        "bwd_pkt_cnt",
        "fwd_pkt_len_tot",
        "bwd_pkt_len_tot",
        "fwd_pkt_hdr_len_tot",
        "fwd_pkt_hdr_len_min",
        "bwd_pkt_hdr_len_tot",
        "bwd_pkt_hdr_len_min",
        "fwd_non_empty_pkt_cnt",
        "bwd_non_empty_pkt_cnt",
        "flag_SYN",
        "flag_fin",
        "flag_rst",
        "flag_ack",
        "flag_psh",
        "fwd_flag_psh",
        "bwd_flag_psh",
        "flag_cwr",
        "flag_ece",
        "fwd_tcp_init_win_bytes",
        "bwd_tcp_init_win_bytes",
    }
    if name in int_like:
        return str(int(round(value)))

    # Time features are in microseconds and often appear as integers
    if "duration" in name or "iat" in name or name.startswith("active") or name.startswith("idle"):
        if abs(value) >= 1.0:
            return str(int(round(value)))
        return f"{value:.6f}"

    if value == 0.0:
        return "0"
    mag = abs(value)
    if mag >= 1e6 or mag < 1e-3:
        return f"{value:.6e}"
    return f"{value:.6f}"

try:
    from scapy.all import AsyncSniffer, IP, IPv6, TCP, UDP  # type: ignore
except Exception as exc:  # pragma: no cover
    raise SystemExit(
        "Scapy is required. Install with: pip install scapy\n"
        f"Import error: {exc}"
    )


FEATURES: List[str] = [
    "flow_duration",
    "down_up_ratio",
    "pkt_len_max",
    "pkt_len_min",
    "pkt_len_mean",
    "pkt_len_var",
    "pkt_len_std",
    "bytes_per_s",
    "pkt_per_s",
    "fwd_pkt_per_s",
    "bwd_pkt_per_s",
    "fwd_pkt_cnt",
    "fwd_pkt_len_tot",
    "fwd_pkt_len_max",
    "fwd_pkt_len_min",
    "fwd_pkt_len_mean",
    "fwd_pkt_len_std",
    "fwd_pkt_hdr_len_tot",
    "fwd_pkt_hdr_len_min",
    "fwd_non_empty_pkt_cnt",
    "bwd_pkt_cnt",
    "bwd_pkt_len_tot",
    "bwd_pkt_len_max",
    "bwd_pkt_len_min",
    "bwd_pkt_len_mean",
    "bwd_pkt_len_std",
    "bwd_pkt_hdr_len_tot",
    "bwd_pkt_hdr_len_min",
    "bwd_non_empty_pkt_cnt",
    "iat_max",
    "iat_min",
    "iat_mean",
    "iat_std",
    "fwd_iat_tot",
    "fwd_iat_max",
    "fwd_iat_min",
    "fwd_iat_mean",
    "fwd_iat_std",
    "bwd_iat_tot",
    "bwd_iat_max",
    "bwd_iat_min",
    "bwd_iat_mean",
    "bwd_iat_std",
    "active_max",
    "active_min",
    "active_mean",
    "active_std",
    "idle_max",
    "idle_min",
    "idle_mean",
    "idle_std",
    "flag_SYN",
    "flag_fin",
    "flag_rst",
    "flag_ack",
    "flag_psh",
    "fwd_flag_psh",
    "bwd_flag_psh",
    "flag_cwr",
    "flag_ece",
    "fwd_bulk_bytes_mean",
    "fwd_bulk_pkt_mean",
    "fwd_bulk_rate_mean",
    "bwd_bulk_bytes_mean",
    "bwd_bulk_pkt_mean",
    "bwd_bulk_rate_mean",
    "fwd_subflow_bytes_mean",
    "fwd_subflow_pkt_mean",
    "bwd_subflow_bytes_mean",
    "bwd_subflow_pkt_mean",
    "fwd_tcp_init_win_bytes",
    "bwd_tcp_init_win_bytes",
]


@dataclass(frozen=True)
class PacketRecord:
    ts: float
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    proto: int  # 6 TCP, 17 UDP
    ip_header_len: int
    l4_header_len: int
    pkt_len: int
    payload_len: int
    tcp_flags: int
    tcp_window: int


class RunningStats:
    __slots__ = ("n", "mean", "m2", "min", "max", "sum")

    def __init__(self) -> None:
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.min = float("inf")
        self.max = float("-inf")
        self.sum = 0.0

    def update(self, x: float) -> None:
        self.n += 1
        self.sum += x
        if x < self.min:
            self.min = x
        if x > self.max:
            self.max = x
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    def finalize(self) -> Tuple[float, float, float, float, float]:
        if self.n == 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        var = self.m2 / self.n if self.n > 0 else 0.0
        std = math.sqrt(var) if var > 0 else 0.0
        minv = 0.0 if self.min == float("inf") else self.min
        maxv = 0.0 if self.max == float("-inf") else self.max
        return minv, maxv, self.mean, std, var


class FlowState:
    """Per-flow state tracker — LycoSTand-compatible.

    Key differences from CICFlowMeter:
    - pkt_len = payload length (IP total - IP hdr - L4 hdr), NOT total IP length.
    - hdr_len = L4 header length only.
    - Bulk detection uses 4-packet threshold with 1-second timeout (in µs).
    - Subflow count starts at 1 and increments when inter-packet gap > 1 second.
    """

    __slots__ = (
        "flow_id",
        "src_ip",
        "dst_ip",
        "src_port",
        "dst_port",
        "proto",
        "start_ts",
        "last_ts",
        "last_fwd_ts",
        "last_bwd_ts",
        "flow_iat",
        "fwd_iat",
        "bwd_iat",
        "pkt_len_stats",
        "fwd_len_stats",
        "bwd_len_stats",
        "fwd_pkts",
        "bwd_pkts",
        "fwd_hdr_len_sum",
        "bwd_hdr_len_sum",
        "fwd_hdr_len_min",
        "bwd_hdr_len_min",
        "fwd_non_empty_pkt_cnt",
        "bwd_non_empty_pkt_cnt",
        "fin",
        "syn",
        "rst",
        "psh",
        "ack",
        "cwe",
        "ece",
        "fwd_psh",
        "bwd_psh",
        "init_win_fwd",
        "init_win_bwd",
        "activity_timeout",
        "active_periods",
        "idle_periods",
        "_cur_active_start",
        "_last_activity_ts",
        # Subflow (LycoSTand: starts at 1, increments when gap > 1s)
        "_subflow_cnt",
        # Bulk tracking (LycoSTand algorithm)
        "_fwd_bulk_state_cnt",
        "_fwd_bulk_pkt_cnt",
        "_fwd_bulk_size_total",
        "_fwd_bulk_duration",
        "_fwd_bulk_pkt_cnt_helper",
        "_fwd_bulk_size_helper",
        "_fwd_bulk_start_helper",
        "_fwd_bulk_last_ts",
        "_bwd_bulk_state_cnt",
        "_bwd_bulk_pkt_cnt",
        "_bwd_bulk_size_total",
        "_bwd_bulk_duration",
        "_bwd_bulk_pkt_cnt_helper",
        "_bwd_bulk_size_helper",
        "_bwd_bulk_start_helper",
        "_bwd_bulk_last_ts",
        # TCP close tracking
        "_fwd_fin_seen",
        "_bwd_fin_seen",
        "_rst_seen",
    )

    def __init__(
        self,
        flow_id: Tuple[str, int, str, int, int],
        first: PacketRecord,
        activity_timeout_s: float,
    ) -> None:
        self.flow_id = flow_id
        self.src_ip, self.src_port, self.dst_ip, self.dst_port, self.proto = flow_id

        self.start_ts = first.ts
        self.last_ts = first.ts
        self.last_fwd_ts = None  # type: Optional[float]
        self.last_bwd_ts = None  # type: Optional[float]

        self.flow_iat = RunningStats()
        self.fwd_iat = RunningStats()
        self.bwd_iat = RunningStats()

        # LycoSTand: pkt_len = payload length (not total IP length)
        self.pkt_len_stats = RunningStats()
        self.fwd_len_stats = RunningStats()
        self.bwd_len_stats = RunningStats()

        self.fwd_pkts = 0
        self.bwd_pkts = 0

        # hdr_len in LycoSTand = L4 header length only
        self.fwd_hdr_len_sum = 0
        self.bwd_hdr_len_sum = 0
        self.fwd_hdr_len_min = None  # type: Optional[int]
        self.bwd_hdr_len_min = None  # type: Optional[int]

        self.fwd_non_empty_pkt_cnt = 0
        self.bwd_non_empty_pkt_cnt = 0

        self.fin = 0
        self.syn = 0
        self.rst = 0
        self.psh = 0
        self.ack = 0
        self.cwe = 0
        self.ece = 0

        self.fwd_psh = 0
        self.bwd_psh = 0

        self.init_win_fwd = None  # type: Optional[int]
        self.init_win_bwd = None  # type: Optional[int]

        self.activity_timeout = activity_timeout_s
        self.active_periods: List[float] = []
        self.idle_periods: List[float] = []
        self._cur_active_start = first.ts
        self._last_activity_ts = first.ts

        # LycoSTand: subflow_cnt starts at 1, increments when gap > 1s
        self._subflow_cnt = 1

        # Bulk tracking — LycoSTand algorithm
        self._fwd_bulk_state_cnt = 0
        self._fwd_bulk_pkt_cnt = 0
        self._fwd_bulk_size_total = 0
        self._fwd_bulk_duration = 0.0
        self._fwd_bulk_pkt_cnt_helper = 0
        self._fwd_bulk_size_helper = 0
        self._fwd_bulk_start_helper = 0.0
        self._fwd_bulk_last_ts = 0.0
        self._bwd_bulk_state_cnt = 0
        self._bwd_bulk_pkt_cnt = 0
        self._bwd_bulk_size_total = 0
        self._bwd_bulk_duration = 0.0
        self._bwd_bulk_pkt_cnt_helper = 0
        self._bwd_bulk_size_helper = 0
        self._bwd_bulk_start_helper = 0.0
        self._bwd_bulk_last_ts = 0.0

        # TCP close tracking
        self._fwd_fin_seen = 0
        self._bwd_fin_seen = 0
        self._rst_seen = 0

    def _update_active_idle(self, ts: float) -> None:
        gap = ts - self._last_activity_ts
        if gap > self.activity_timeout:
            active_dur = max(0.0, self._last_activity_ts - self._cur_active_start)
            self.active_periods.append(active_dur)
            self.idle_periods.append(gap)
            self._cur_active_start = ts
        self._last_activity_ts = ts

    def _update_subflow(self, ts: float) -> None:
        """LycoSTand: subflow increments when gap > 1 second (1_000_000 µs)."""
        if ts - self.last_ts > 1.0:
            self._subflow_cnt += 1

    def _update_fwd_bulk(self, pkt_len: int, ts_us: float) -> None:
        """LycoSTand forward bulk algorithm (4-packet threshold, 1s timeout)."""
        # If backward happened after our current bulk start, reset
        if self._bwd_bulk_last_ts > self._fwd_bulk_start_helper:
            self._fwd_bulk_start_helper = 0.0
        if pkt_len < 1:
            return
        if self._fwd_bulk_start_helper == 0.0:
            self._fwd_bulk_start_helper = ts_us
            self._fwd_bulk_pkt_cnt_helper = 1
            self._fwd_bulk_size_helper = pkt_len
            self._fwd_bulk_last_ts = ts_us
        else:
            if (ts_us - self._fwd_bulk_last_ts) > MICROSECONDS:
                # Gap > 1 second → restart
                self._fwd_bulk_start_helper = ts_us
                self._fwd_bulk_last_ts = ts_us
                self._fwd_bulk_pkt_cnt_helper = 1
                self._fwd_bulk_size_helper = pkt_len
            else:
                self._fwd_bulk_pkt_cnt_helper += 1
                self._fwd_bulk_size_helper += pkt_len
                if self._fwd_bulk_pkt_cnt_helper == 4:
                    self._fwd_bulk_state_cnt += 1
                    self._fwd_bulk_pkt_cnt += self._fwd_bulk_pkt_cnt_helper
                    self._fwd_bulk_size_total += self._fwd_bulk_size_helper
                    ts_diff = ts_us - self._fwd_bulk_start_helper
                    if ts_diff > 0:
                        self._fwd_bulk_duration += ts_diff
                elif self._fwd_bulk_pkt_cnt_helper > 4:
                    self._fwd_bulk_pkt_cnt += 1
                    self._fwd_bulk_size_total += pkt_len
                    ts_diff = ts_us - self._fwd_bulk_last_ts
                    if ts_diff > 0:
                        self._fwd_bulk_duration += ts_diff
                self._fwd_bulk_last_ts = ts_us

    def _update_bwd_bulk(self, pkt_len: int, ts_us: float) -> None:
        """LycoSTand backward bulk algorithm."""
        if self._fwd_bulk_last_ts > self._bwd_bulk_start_helper:
            self._bwd_bulk_start_helper = 0.0
        if pkt_len < 1:
            return
        if self._bwd_bulk_start_helper == 0.0:
            self._bwd_bulk_start_helper = ts_us
            self._bwd_bulk_pkt_cnt_helper = 1
            self._bwd_bulk_size_helper = pkt_len
            self._bwd_bulk_last_ts = ts_us
        else:
            if (ts_us - self._bwd_bulk_last_ts) > MICROSECONDS:
                self._bwd_bulk_start_helper = ts_us
                self._bwd_bulk_last_ts = ts_us
                self._bwd_bulk_pkt_cnt_helper = 1
                self._bwd_bulk_size_helper = pkt_len
            else:
                self._bwd_bulk_pkt_cnt_helper += 1
                self._bwd_bulk_size_helper += pkt_len
                if self._bwd_bulk_pkt_cnt_helper == 4:
                    self._bwd_bulk_state_cnt += 1
                    self._bwd_bulk_pkt_cnt += self._bwd_bulk_pkt_cnt_helper
                    self._bwd_bulk_size_total += self._bwd_bulk_size_helper
                    ts_diff = ts_us - self._bwd_bulk_start_helper
                    if ts_diff > 0:
                        self._bwd_bulk_duration += ts_diff
                elif self._bwd_bulk_pkt_cnt_helper > 4:
                    self._bwd_bulk_pkt_cnt += 1
                    self._bwd_bulk_size_total += pkt_len
                    ts_diff = ts_us - self._bwd_bulk_last_ts
                    if ts_diff > 0:
                        self._bwd_bulk_duration += ts_diff
                self._bwd_bulk_last_ts = ts_us

    @staticmethod
    def _flag_set(flags: int, mask: int) -> int:
        return 1 if (flags & mask) != 0 else 0

    def add_packet(self, pkt: PacketRecord, is_forward: bool) -> None:
        if pkt.ts < self.last_ts:
            pkt_ts = self.last_ts
        else:
            pkt_ts = pkt.ts

        if self.last_ts is not None and pkt_ts > self.last_ts:
            self.flow_iat.update(pkt_ts - self.last_ts)

        self._update_active_idle(pkt_ts)
        self._update_subflow(pkt_ts)

        # LycoSTand: pkt_len = payload length (ip_len - ip_hdr - l4_hdr)
        payload_len = pkt.payload_len
        # LycoSTand: hdr_len = L4 header length only
        l4_hdr_len = pkt.l4_header_len

        self.pkt_len_stats.update(float(payload_len))

        # Bulk tracking uses microsecond timestamps
        ts_us = pkt_ts * MICROSECONDS

        if is_forward:
            if self.last_fwd_ts is not None and pkt_ts > self.last_fwd_ts:
                self.fwd_iat.update(pkt_ts - self.last_fwd_ts)
            self.last_fwd_ts = pkt_ts

            self.fwd_pkts += 1
            self.fwd_hdr_len_sum += l4_hdr_len
            self.fwd_len_stats.update(float(payload_len))

            if self.fwd_hdr_len_min is None or l4_hdr_len < self.fwd_hdr_len_min:
                self.fwd_hdr_len_min = l4_hdr_len

            if payload_len > 0:
                self.fwd_non_empty_pkt_cnt += 1

            if pkt.proto == 6:
                if self.init_win_fwd is None and pkt.tcp_window >= 0:
                    self.init_win_fwd = pkt.tcp_window

            if self._flag_set(pkt.tcp_flags, 0x08):
                self.fwd_psh += 1

            self._update_fwd_bulk(payload_len, ts_us)

        else:
            if self.last_bwd_ts is not None and pkt_ts > self.last_bwd_ts:
                self.bwd_iat.update(pkt_ts - self.last_bwd_ts)
            self.last_bwd_ts = pkt_ts

            self.bwd_pkts += 1
            self.bwd_hdr_len_sum += l4_hdr_len
            self.bwd_len_stats.update(float(payload_len))

            if self.bwd_hdr_len_min is None or l4_hdr_len < self.bwd_hdr_len_min:
                self.bwd_hdr_len_min = l4_hdr_len

            if payload_len > 0:
                self.bwd_non_empty_pkt_cnt += 1

            if pkt.proto == 6:
                if self.init_win_bwd is None and pkt.tcp_window >= 0:
                    self.init_win_bwd = pkt.tcp_window

            if self._flag_set(pkt.tcp_flags, 0x08):
                self.bwd_psh += 1

            self._update_bwd_bulk(payload_len, ts_us)

        self.last_ts = pkt_ts

        if pkt.proto == 6:
            self.fin += self._flag_set(pkt.tcp_flags, 0x01)
            self.syn += self._flag_set(pkt.tcp_flags, 0x02)
            self.rst += self._flag_set(pkt.tcp_flags, 0x04)
            self.psh += self._flag_set(pkt.tcp_flags, 0x08)
            self.ack += self._flag_set(pkt.tcp_flags, 0x10)
            self.ece += self._flag_set(pkt.tcp_flags, 0x40)
            self.cwe += self._flag_set(pkt.tcp_flags, 0x80)

            # Track termination flags for flow closure
            if self._flag_set(pkt.tcp_flags, 0x04):
                self._rst_seen = 1
            if self._flag_set(pkt.tcp_flags, 0x01):
                if is_forward:
                    self._fwd_fin_seen += 1
                else:
                    self._bwd_fin_seen += 1

    def should_close_on_tcp_flags(self) -> bool:
        """CICFlowMeter-style close triggers (TCP only).

        - RST closes immediately.
        - FIN closes only after both directions have seen FIN at least once.
        """
        if self._rst_seen:
            return True
        if self._fwd_fin_seen >= 1 and self._bwd_fin_seen >= 1:
            return True
        return False

    def finalize_row(self) -> List[float]:
        """Produce a 72-feature row matching LycoSTand output order."""
        # LycoSTand uses microseconds for duration and IAT features.
        duration_s = max(0.0, self.last_ts - self.start_ts)
        duration_us = duration_s * MICROSECONDS
        total_pkts = self.fwd_pkts + self.bwd_pkts

        # --- End-of-flow calculations (featcalc_endOfFlow_update) ---
        # Rates (per second)
        fwd_pkt_per_s = (self.fwd_pkts / duration_s) if duration_s > 0 else 0.0
        bwd_pkt_per_s = (self.bwd_pkts / duration_s) if duration_s > 0 else 0.0
        pkt_per_s = fwd_pkt_per_s + bwd_pkt_per_s

        fwd_bytes_sum = self.fwd_len_stats.sum
        bwd_bytes_sum = self.bwd_len_stats.sum
        fwd_bytes_per_s = (fwd_bytes_sum / duration_s) if duration_s > 0 else 0.0
        bwd_bytes_per_s = (bwd_bytes_sum / duration_s) if duration_s > 0 else 0.0
        bytes_per_s = fwd_bytes_per_s + bwd_bytes_per_s

        # Down/Up ratio
        down_up_ratio = (self.bwd_pkts / self.fwd_pkts) if self.fwd_pkts > 0 else 0.0

        # Bulk means (LycoSTand: total / state_cnt, rate = total / duration_s)
        fwd_bulk_bytes_mean = (self._fwd_bulk_size_total / self._fwd_bulk_state_cnt) if self._fwd_bulk_state_cnt > 0 else 0.0
        fwd_bulk_pkt_mean = (self._fwd_bulk_pkt_cnt / self._fwd_bulk_state_cnt) if self._fwd_bulk_state_cnt > 0 else 0.0
        fwd_bulk_dur_s = self._fwd_bulk_duration / MICROSECONDS
        fwd_bulk_rate_mean = (self._fwd_bulk_size_total / fwd_bulk_dur_s) if fwd_bulk_dur_s > 0 else 0.0

        bwd_bulk_bytes_mean = (self._bwd_bulk_size_total / self._bwd_bulk_state_cnt) if self._bwd_bulk_state_cnt > 0 else 0.0
        bwd_bulk_pkt_mean = (self._bwd_bulk_pkt_cnt / self._bwd_bulk_state_cnt) if self._bwd_bulk_state_cnt > 0 else 0.0
        bwd_bulk_dur_s = self._bwd_bulk_duration / MICROSECONDS
        bwd_bulk_rate_mean = (self._bwd_bulk_size_total / bwd_bulk_dur_s) if bwd_bulk_dur_s > 0 else 0.0

        # Subflow means (LycoSTand: total / subflow_cnt)
        sc = self._subflow_cnt if self._subflow_cnt > 0 else 1
        fwd_subflow_pkt = self.fwd_pkts / sc
        fwd_subflow_bytes = fwd_bytes_sum / sc
        bwd_subflow_pkt = self.bwd_pkts / sc
        bwd_subflow_bytes = bwd_bytes_sum / sc

        # --- Packet length stats ---
        fwd_min, fwd_max, fwd_mean, fwd_std, _ = self.fwd_len_stats.finalize()
        bwd_min, bwd_max, bwd_mean, bwd_std, _ = self.bwd_len_stats.finalize()
        pkt_min, pkt_max, pkt_mean, pkt_std, pkt_var = self.pkt_len_stats.finalize()

        # --- IAT stats (convert to microseconds) ---
        fiat_min_s, fiat_max_s, fiat_mean_s, fiat_std_s, _ = self.flow_iat.finalize()
        fwd_iat_min_s, fwd_iat_max_s, fwd_iat_mean_s, fwd_iat_std_s, _ = self.fwd_iat.finalize()
        bwd_iat_min_s, bwd_iat_max_s, bwd_iat_mean_s, bwd_iat_std_s, _ = self.bwd_iat.finalize()

        fiat_min = max(0.0, fiat_min_s) * MICROSECONDS
        fiat_max = fiat_max_s * MICROSECONDS
        fiat_mean = fiat_mean_s * MICROSECONDS
        fiat_std = fiat_std_s * MICROSECONDS
        fwd_iat_total = self.fwd_iat.sum * MICROSECONDS
        fwd_iat_min = max(0.0, fwd_iat_min_s) * MICROSECONDS
        fwd_iat_max = fwd_iat_max_s * MICROSECONDS
        fwd_iat_mean = fwd_iat_mean_s * MICROSECONDS
        fwd_iat_std = fwd_iat_std_s * MICROSECONDS
        bwd_iat_total = self.bwd_iat.sum * MICROSECONDS
        bwd_iat_min = max(0.0, bwd_iat_min_s) * MICROSECONDS
        bwd_iat_max = bwd_iat_max_s * MICROSECONDS
        bwd_iat_mean = bwd_iat_mean_s * MICROSECONDS
        bwd_iat_std = bwd_iat_std_s * MICROSECONDS

        # --- Active / Idle stats (in microseconds) ---
        active_stats = RunningStats()
        idle_stats = RunningStats()
        end_active = max(0.0, self._last_activity_ts - self._cur_active_start)
        self.active_periods.append(end_active)
        for x in self.active_periods:
            active_stats.update(float(x))
        for x in self.idle_periods:
            idle_stats.update(float(x))

        _, active_max_s, active_mean_s, active_std_s, _ = active_stats.finalize()
        active_min_s = active_stats.min if active_stats.n > 0 else 0.0
        active_min_s = 0.0 if active_min_s == float("inf") else float(active_min_s)

        active_max = active_max_s * MICROSECONDS
        active_min = active_min_s * MICROSECONDS
        active_mean = active_mean_s * MICROSECONDS
        active_std = active_std_s * MICROSECONDS

        _, idle_max_s, idle_mean_s, idle_std_s, _ = idle_stats.finalize()
        idle_min_s = idle_stats.min if idle_stats.n > 0 else 0.0
        idle_min_s = 0.0 if idle_min_s == float("inf") else float(idle_min_s)

        idle_max = idle_max_s * MICROSECONDS
        idle_min = idle_min_s * MICROSECONDS
        idle_mean = idle_mean_s * MICROSECONDS
        idle_std = idle_std_s * MICROSECONDS

        # TCP init window bytes (-1 if not TCP or no bwd packets)
        init_win_fwd = float(self.init_win_fwd) if self.init_win_fwd is not None else -1.0
        init_win_bwd = float(self.init_win_bwd) if self.init_win_bwd is not None else -1.0

        # --- Build the 72-feature row in FEATURES order ---
        row: Dict[str, float] = {
            "flow_duration": duration_us,
            "down_up_ratio": down_up_ratio,
            "pkt_len_max": pkt_max,
            "pkt_len_min": pkt_min,
            "pkt_len_mean": pkt_mean,
            "pkt_len_var": pkt_var,
            "pkt_len_std": pkt_std,
            "bytes_per_s": bytes_per_s,
            "pkt_per_s": pkt_per_s,
            "fwd_pkt_per_s": fwd_pkt_per_s,
            "bwd_pkt_per_s": bwd_pkt_per_s,
            "fwd_pkt_cnt": float(self.fwd_pkts),
            "fwd_pkt_len_tot": fwd_bytes_sum,
            "fwd_pkt_len_max": fwd_max,
            "fwd_pkt_len_min": fwd_min,
            "fwd_pkt_len_mean": fwd_mean,
            "fwd_pkt_len_std": fwd_std,
            "fwd_pkt_hdr_len_tot": float(self.fwd_hdr_len_sum),
            "fwd_pkt_hdr_len_min": float(self.fwd_hdr_len_min or 0),
            "fwd_non_empty_pkt_cnt": float(self.fwd_non_empty_pkt_cnt),
            "bwd_pkt_cnt": float(self.bwd_pkts),
            "bwd_pkt_len_tot": bwd_bytes_sum,
            "bwd_pkt_len_max": bwd_max,
            "bwd_pkt_len_min": bwd_min,
            "bwd_pkt_len_mean": bwd_mean,
            "bwd_pkt_len_std": bwd_std,
            "bwd_pkt_hdr_len_tot": float(self.bwd_hdr_len_sum),
            "bwd_pkt_hdr_len_min": float(self.bwd_hdr_len_min or 0),
            "bwd_non_empty_pkt_cnt": float(self.bwd_non_empty_pkt_cnt),
            "iat_max": fiat_max,
            "iat_min": fiat_min,
            "iat_mean": fiat_mean,
            "iat_std": fiat_std,
            "fwd_iat_tot": fwd_iat_total,
            "fwd_iat_max": fwd_iat_max,
            "fwd_iat_min": fwd_iat_min,
            "fwd_iat_mean": fwd_iat_mean,
            "fwd_iat_std": fwd_iat_std,
            "bwd_iat_tot": bwd_iat_total,
            "bwd_iat_max": bwd_iat_max,
            "bwd_iat_min": bwd_iat_min,
            "bwd_iat_mean": bwd_iat_mean,
            "bwd_iat_std": bwd_iat_std,
            "active_max": active_max,
            "active_min": active_min,
            "active_mean": active_mean,
            "active_std": active_std,
            "idle_max": idle_max,
            "idle_min": idle_min,
            "idle_mean": idle_mean,
            "idle_std": idle_std,
            "flag_SYN": float(self.syn),
            "flag_fin": float(self.fin),
            "flag_rst": float(self.rst),
            "flag_ack": float(self.ack),
            "flag_psh": float(self.psh),
            "fwd_flag_psh": float(self.fwd_psh),
            "bwd_flag_psh": float(self.bwd_psh),
            "flag_cwr": float(self.cwe),
            "flag_ece": float(self.ece),
            "fwd_bulk_bytes_mean": fwd_bulk_bytes_mean,
            "fwd_bulk_pkt_mean": fwd_bulk_pkt_mean,
            "fwd_bulk_rate_mean": fwd_bulk_rate_mean,
            "bwd_bulk_bytes_mean": bwd_bulk_bytes_mean,
            "bwd_bulk_pkt_mean": bwd_bulk_pkt_mean,
            "bwd_bulk_rate_mean": bwd_bulk_rate_mean,
            "fwd_subflow_bytes_mean": fwd_subflow_bytes,
            "fwd_subflow_pkt_mean": fwd_subflow_pkt,
            "bwd_subflow_bytes_mean": bwd_subflow_bytes,
            "bwd_subflow_pkt_mean": bwd_subflow_pkt,
            "fwd_tcp_init_win_bytes": init_win_fwd,
            "bwd_tcp_init_win_bytes": init_win_bwd,
        }

        return [row[name] for name in FEATURES]


class FlowManager:
    def __init__(
        self,
        export_queue: queue.Queue[FlowState],
        flow_timeout_s: float,
        idle_timeout_s: float,
        activity_timeout_s: float,
    ) -> None:
        self.export_queue = export_queue
        self.flow_timeout_s = flow_timeout_s
        self.idle_timeout_s = idle_timeout_s
        self.activity_timeout_s = activity_timeout_s
        self.flows: Dict[Tuple[str, int, str, int, int], FlowState] = {}
        # Only the aggregator thread mutates flows; lock not needed.

    @staticmethod
    def _flow_id_for(pkt: PacketRecord) -> Tuple[str, int, str, int, int]:
        return (pkt.src_ip, pkt.src_port, pkt.dst_ip, pkt.dst_port, pkt.proto)

    @staticmethod
    def _reverse_flow_id(flow_id: Tuple[str, int, str, int, int]) -> Tuple[str, int, str, int, int]:
        src_ip, src_port, dst_ip, dst_port, proto = flow_id
        return (dst_ip, dst_port, src_ip, src_port, proto)

    def handle_packet(self, pkt: PacketRecord) -> None:
        fid = self._flow_id_for(pkt)
        rid = self._reverse_flow_id(fid)

        # Direction detection:
        # - Prefer SYN without ACK (TCP) to define forward direction.
        # - Fallback: first-seen direction.
        flow = self.flows.get(fid)
        if flow is not None:
            is_forward = True
        else:
            flow = self.flows.get(rid)
            is_forward = False

        if flow is None:
            flow = FlowState(fid, pkt, self.activity_timeout_s)
            self.flows[fid] = flow
            is_forward = True

        # If TCP SYN (no ACK) arrives on the reverse direction, flip the flow key
        # so the SYN sender becomes the forward direction.
        if pkt.proto == 6:
            syn = (pkt.tcp_flags & 0x02) != 0
            ack = (pkt.tcp_flags & 0x10) != 0
            if syn and not ack and not is_forward:
                # Re-key flow to make SYN direction forward
                current_key = flow.flow_id
                new_key = rid
                if current_key != new_key:
                    self.flows.pop(current_key, None)
                    flow.flow_id = new_key  # type: ignore[attr-defined]
                    flow.src_ip, flow.src_port, flow.dst_ip, flow.dst_port, flow.proto = new_key  # type: ignore[attr-defined]
                    self.flows[new_key] = flow
                is_forward = True

        flow.add_packet(pkt, is_forward=is_forward)

        # TCP immediate close conditions (FIN/RST)
        if pkt.proto == 6 and flow.should_close_on_tcp_flags():
            # Remove flow by its current key and export
            self.flows.pop(flow.flow_id, None)
            if (flow.fwd_pkts + flow.bwd_pkts) > 1:
                self.export_queue.put(flow)

    def reap_expired(self, now_ts: float) -> None:
        expired: List[Tuple[str, int, str, int, int]] = []
        for fid, flow in self.flows.items():
            if (now_ts - flow.start_ts) > self.flow_timeout_s:
                expired.append(fid)
                continue
            if (now_ts - flow.last_ts) > self.idle_timeout_s:
                expired.append(fid)

        for fid in expired:
            flow = self.flows.pop(fid, None)
            if flow is not None and (flow.fwd_pkts + flow.bwd_pkts) > 1:
                self.export_queue.put(flow)


def packet_to_record(pkt) -> Optional[PacketRecord]:
    ts = float(getattr(pkt, "time", time.time()))

    ip_layer = None
    if pkt.haslayer(IP):
        ip_layer = pkt.getlayer(IP)
        src_ip = ip_layer.src
        dst_ip = ip_layer.dst
        ip_header_len = int(ip_layer.ihl) * 4 if getattr(ip_layer, "ihl", None) else 20
        proto = int(ip_layer.proto)
        pkt_len = int(ip_layer.len) if getattr(ip_layer, "len", None) else int(len(pkt))
    elif pkt.haslayer(IPv6):
        ip_layer = pkt.getlayer(IPv6)
        src_ip = ip_layer.src
        dst_ip = ip_layer.dst
        ip_header_len = 40
        proto = int(ip_layer.nh)
        pkt_len = int(getattr(ip_layer, "plen", 0)) + 40
        if pkt_len <= 0:
            pkt_len = int(len(pkt))
    else:
        return None

    if pkt.haslayer(TCP):
        tcp = pkt.getlayer(TCP)
        src_port = int(tcp.sport)
        dst_port = int(tcp.dport)
        l4_header_len = int(tcp.dataofs) * 4 if getattr(tcp, "dataofs", None) else 20
        flags = int(tcp.flags)
        window = int(getattr(tcp, "window", 0) or 0)
        payload_len = max(0, pkt_len - ip_header_len - l4_header_len)
        return PacketRecord(
            ts=ts,
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=src_port,
            dst_port=dst_port,
            proto=6,
            ip_header_len=ip_header_len,
            l4_header_len=l4_header_len,
            pkt_len=pkt_len,
            payload_len=payload_len,
            tcp_flags=flags,
            tcp_window=window,
        )

    if pkt.haslayer(UDP):
        udp = pkt.getlayer(UDP)
        src_port = int(udp.sport)
        dst_port = int(udp.dport)
        l4_header_len = 8
        payload_len = max(0, pkt_len - ip_header_len - l4_header_len)
        return PacketRecord(
            ts=ts,
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=src_port,
            dst_port=dst_port,
            proto=17,
            ip_header_len=ip_header_len,
            l4_header_len=l4_header_len,
            pkt_len=pkt_len,
            payload_len=payload_len,
            tcp_flags=0,
            tcp_window=0,
        )

    return None


def run(
    iface: str,
    bpf_filter: str,
    out_csv: Optional[str],
    workers: int,
    packet_queue_size: int,
    flow_timeout: float,
    idle_timeout: float,
    activity_timeout: float,
    flush_interval: float,
    ws_workers: int = 0,
    ws_endpoint: Optional[str] = None,
    ws_token: Optional[str] = None,
) -> None:
    stop_event = threading.Event()

    pkt_q: queue.Queue[PacketRecord] = queue.Queue(maxsize=packet_queue_size)
    export_q: queue.Queue[FlowState] = queue.Queue(maxsize=max(1000, packet_queue_size // 2))

    send_q: queue.Queue[dict] = queue.Queue(maxsize=max(2000, packet_queue_size // 2))

    fm = FlowManager(
        export_queue=export_q,
        flow_timeout_s=flow_timeout,
        idle_timeout_s=idle_timeout,
        activity_timeout_s=activity_timeout,
    )

    csv_lock = threading.Lock()
    csv_file = None
    writer = None
    if out_csv:
        csv_file = open(out_csv, "w", newline="", encoding="utf-8")
        writer = csv.writer(csv_file)
        writer.writerow(FEATURES)

    # Optional WebSocket sender pool: each worker thread owns its own Socket.IO client.
    ws_stop = threading.Event()
    ws_threads: List[threading.Thread] = []

    def _normalize_ws_url(endpoint: str) -> str:
        ep = endpoint.strip()
        if not ep:
            raise ValueError("Empty endpoint")
        # Accept either base URL (http://host:port) or full namespace endpoint.
        if ep.endswith("/ws/inference"):
            return ep
        return ep.rstrip("/") + "/ws/inference"

    def ws_worker(worker_id: int) -> None:
        if socketio is None:
            raise SystemExit(
                "python-socketio client is required for WS sending. Install: pip install \"python-socketio[client]\""
            )
        assert ws_endpoint is not None
        assert ws_token is not None

        url = _normalize_ws_url(ws_endpoint)
        sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=0,  # infinite
            reconnection_delay=1,
            reconnection_delay_max=10,
            logger=False,
            engineio_logger=False,
        )

        connected = threading.Event()

        @sio.event(namespace="/ws/inference")
        def connect():
            connected.set()

        @sio.event(namespace="/ws/inference")
        def disconnect():
            connected.clear()

        @sio.on("error", namespace="/ws/inference")
        def on_error(msg):
            # Keep running; server may disconnect, and reconnection will retry.
            connected.clear()

        @sio.on("connected", namespace="/ws/inference")
        def on_connected(_msg):
            connected.set()

        # Connect loop
        while not ws_stop.is_set():
            try:
                sio.connect(
                    url.replace("/ws/inference", ""),
                    # Prefer Socket.IO auth payload (server-side connect(auth) handler).
                    # Also include a Bearer header for deployments that authenticate at the HTTP layer
                    # (reverse proxies / custom middleware) before the Socket.IO handshake reaches Flask.
                    auth={"api_token": ws_token},
                    headers={"Authorization": f"Bearer {ws_token}"},
                    namespaces=["/ws/inference"],
                    wait_timeout=5,
                )
                break
            except Exception:
                time.sleep(1.0)

        # Send loop
        while not ws_stop.is_set():
            try:
                payload = send_q.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                if not connected.is_set():
                    # If disconnected, requeue once and wait.
                    send_q.put(payload)
                    time.sleep(0.5)
                else:
                    sio.emit("inference", payload, namespace="/ws/inference")
            except Exception:
                # Best-effort: drop this message if send fails repeatedly.
                pass
            finally:
                send_q.task_done()

        try:
            sio.disconnect()
        except Exception:
            pass

    def export_worker() -> None:
        while not stop_event.is_set():
            try:
                flow = export_q.get(timeout=0.5)
            except queue.Empty:
                continue
            row = flow.finalize_row()
            if writer is not None:
                formatted = [_fmt_value(name, value) for name, value in zip(FEATURES, row)]
                with csv_lock:
                    writer.writerow(formatted)

            # Optional WS send: emit numeric list (joblib-friendly) + minimal metadata.
            if ws_workers > 0:
                # FlowState keys are stable: use forward direction as "source".
                # Destination Port feature is row[0] by header.
                try:
                    ts = time.time()
                    payload = {
                        "features": [float(v) for v in row],
                        "source_ip": flow.src_ip,
                        "destination_ip": flow.dst_ip,
                        "source_port": int(flow.src_port),
                        "destination_port": int(flow.dst_port),
                        "protocol": "TCP" if flow.proto == 6 else ("UDP" if flow.proto == 17 else "OTHER"),
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
                    }
                    send_q.put_nowait(payload)
                except Exception:
                    pass
            export_q.task_done()

    def aggregator() -> None:
        last_reap = time.time()
        while not stop_event.is_set():
            try:
                rec = pkt_q.get(timeout=0.2)
            except queue.Empty:
                rec = None

            if rec is not None:
                fm.handle_packet(rec)
                pkt_q.task_done()

            now = time.time()
            if (now - last_reap) >= flush_interval:
                fm.reap_expired(now)
                last_reap = now

    def on_packet(pkt) -> None:
        rec = packet_to_record(pkt)
        if rec is None:
            return
        try:
            pkt_q.put_nowait(rec)
        except queue.Full:
            # Backpressure: drop if overwhelmed.
            return

    threads: List[threading.Thread] = []

    agg_t = threading.Thread(target=aggregator, name="flow-aggregator", daemon=True)
    agg_t.start()
    threads.append(agg_t)

    for i in range(max(1, workers)):
        t = threading.Thread(target=export_worker, name=f"flow-export-{i}", daemon=True)
        t.start()
        threads.append(t)

    sniffer = AsyncSniffer(iface=iface, filter=bpf_filter, prn=on_packet, store=False)

    def _stop(*_args) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    sniffer.start()

    # Start WS sender workers if configured
    if ws_workers > 0:
        if not ws_endpoint or not ws_token:
            raise SystemExit("WS sending enabled but endpoint/token not provided")
        for i in range(ws_workers):
            t = threading.Thread(target=ws_worker, args=(i,), daemon=True)
            ws_threads.append(t)
            t.start()

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    finally:
        sniffer.stop()
        fm.reap_expired(time.time())
        stop_event.set()
        ws_stop.set()
        try:
            pkt_q.join()
        except Exception:
            pass
        try:
            export_q.join()
        except Exception:
            pass
        try:
            send_q.join()
        except Exception:
            pass
        if csv_file is not None:
            with csv_lock:
                csv_file.flush()
                csv_file.close()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Live CICFlowMeter-like flow feature extractor")
    p.add_argument("--iface", required=True, help="Network interface (e.g., eth0)")
    p.add_argument("--filter", default="tcp or udp", help="BPF filter")
    p.add_argument("--out-csv", default=None, help="Optional CSV output path (disabled by default)")
    p.add_argument("--workers", type=int, default=2, help="Number of export worker threads")
    p.add_argument("--pkt-queue", type=int, default=20000, help="Packet queue max size")
    p.add_argument("--flow-timeout", type=float, default=120.0, help="Max flow duration seconds")
    p.add_argument("--idle-timeout", type=float, default=10.0, help="Idle timeout seconds")
    p.add_argument("--activity-timeout", type=float, default=5.0, help="Activity timeout seconds")
    p.add_argument("--flush-interval", type=float, default=1.0, help="How often to reap flows (seconds)")
    p.add_argument("--config", default="elf/config.yaml", help="YAML config with api_token and endpoint")
    p.add_argument("--ws", action="store_true", help="Send features to backend via WebSocket")
    p.add_argument("--ws-workers", type=int, default=2, help="Number of WebSocket sender worker threads")
    p.add_argument("--ws-smoke-test", action="store_true", help="Connect and send synthetic payload(s), then exit")
    p.add_argument(
        "--ws-smoke-fake",
        action="store_true",
        help=(
            "Generate purely random 70-feature payloads for smoke testing (not flow-derived). "
            "Useful for demos and for mimicking old mock-like behavior."
        ),
    )
    p.add_argument("--ws-smoke-n", type=int, default=1, help="Number of smoke-test payloads to send")
    p.add_argument(
        "--ws-smoke-row",
        default=None,
        help="Optional space/comma-separated 70-float feature row to send as the first smoke-test payload",
    )
    p.add_argument("--self-test", action="store_true", help="Run a small deterministic self-test and exit")
    return p


def load_config_yaml(path: str) -> dict:
    if yaml is None:
        raise SystemExit("PyYAML is required for --config. Install with: pip install pyyaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise SystemExit("Invalid config.yaml format")
    return data


def main() -> None:
    args = build_arg_parser().parse_args()

    if args.self_test:
        _self_test()
        return

    if args.ws_smoke_test:
        cfg = load_config_yaml(args.config)
        token = str(cfg.get("api_token") or "").strip()
        endpoint = str(cfg.get("endpoint") or "").strip()
        if not token or not endpoint:
            raise SystemExit("config.yaml must include api_token and endpoint")
        _ws_smoke_test(
            endpoint,
            token,
            workers=max(1, int(args.ws_workers or 1)),
            n=max(1, int(args.ws_smoke_n or 1)),
            row_str=args.ws_smoke_row,
        )
        return

    ws_endpoint = None
    ws_token = None
    ws_workers = 0

    if args.ws:
        cfg = load_config_yaml(args.config)
        ws_token = str(cfg.get("api_token") or "").strip()
        ws_endpoint = str(cfg.get("endpoint") or "").strip()
        if not ws_token or not ws_endpoint:
            raise SystemExit("config.yaml must include api_token and endpoint when --ws is enabled")
        ws_workers = int(args.ws_workers or 1)

    run(
        iface=args.iface,
        bpf_filter=args.filter,
        out_csv=args.out_csv,
        workers=args.workers,
        packet_queue_size=args.pkt_queue,
        flow_timeout=args.flow_timeout,
        idle_timeout=args.idle_timeout,
        activity_timeout=args.activity_timeout,
        flush_interval=args.flush_interval,
        ws_workers=ws_workers,
        ws_endpoint=ws_endpoint,
        ws_token=ws_token,
    )


def _ws_smoke_test(
    endpoint: str,
    token: str,
    workers: int = 1,
    n: int = 1,
    row_str: str | None = None,
    fake: bool = False,
) -> None:
    """Quick WS test: connect, emit N inference payloads, await responses."""

    if socketio is None:
        raise SystemExit(
            "python-socketio client is required for WS sending. Install: pip install \"python-socketio[client]\""
        )

    def _parse_row(s: str) -> List[float]:
        parts = [p for p in s.replace(",", " ").split() if p]
        try:
            vals = [float(p) for p in parts]
        except Exception as exc:
            raise SystemExit(f"--ws-smoke-row parse error: {exc}")
        if len(vals) != len(FEATURES):
            raise SystemExit(f"--ws-smoke-row must have {len(FEATURES)} values; got {len(vals)}")
        return vals

    def _make_payload(features: List[float], idx: int) -> Dict[str, object]:
        now = time.time()
        return {
            "features": features,
            "source_ip": "127.0.0.1",
            "destination_ip": "127.0.0.1",
            "source_port": 10000 + idx,
            "destination_port": 80,
            "protocol": "TCP",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        }

    # Build N valid 72-feature payloads.
    # 1) If a row is provided, send it first.
    # 2) Then send some jittered variants to explore decision space.
    # 3) Finally send some standardized noise.
    base_features = [0.0] * len(FEATURES)
    if row_str:
        base_features = _parse_row(row_str)

    rng = __import__("random")
    payloads: List[Dict[str, object]] = []
    for i in range(n):
        if fake:
            feats = [rng.uniform(-3.0, 3.0) for _ in range(len(FEATURES))]
        elif i == 0 and row_str:
            feats = list(base_features)
        else:
            feats = list(base_features)

            # Apply light multiplicative jitter on non-negative features
            for j, v in enumerate(feats):
                if v == 0.0:
                    # sprinkle in small noise sometimes
                    if rng.random() < 0.15:
                        feats[j] = rng.uniform(0.0, 3.0)
                    continue
                if v > 0:
                    scale = rng.uniform(0.7, 1.3)
                    feats[j] = v * scale
                else:
                    feats[j] = v

            # Occasionally spike rate-like fields to get out of BENIGN pocket
            for name in ("bytes_per_s", "pkt_per_s", "fwd_pkt_per_s", "bwd_pkt_per_s"):
                try:
                    k = FEATURES.index(name)
                    if rng.random() < 0.35:
                        feats[k] = feats[k] + rng.uniform(1e3, 1e6)
                except ValueError:
                    pass

        payloads.append(_make_payload(feats, i))

    def _normalize_ws_url(ep: str) -> str:
        ep = ep.strip()
        if ep.endswith("/ws/inference"):
            return ep
        return ep.rstrip("/") + "/ws/inference"

    url = _normalize_ws_url(endpoint)
    base_url = url.replace("/ws/inference", "")

    sio = socketio.Client(logger=False, engineio_logger=False)
    got_connected = threading.Event()
    got_result = threading.Event()
    result_holder: Dict[str, object] = {}

    @sio.on("connected", namespace="/ws/inference")
    def _on_connected(msg):
        got_connected.set()

    @sio.on("inference_result", namespace="/ws/inference")
    def _on_result(msg):
        result_holder["result"] = msg
        got_result.set()

    @sio.on("error", namespace="/ws/inference")
    def _on_error(msg):
        result_holder["error"] = msg
        got_result.set()

    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            sio.connect(
                base_url,
                # Server uses connect(auth) for API token auth; keep that.
                # Also pass Authorization header for setups that require it at handshake time.
                auth={"api_token": token},
                headers={"Authorization": f"Bearer {token}"},
                namespaces=["/ws/inference"],
                wait_timeout=8,
            )
            last_err = None
            break
        except Exception as e:
            last_err = e
            try:
                sio.disconnect()
            except Exception:
                pass
            # brief backoff; server may be restarting or temporarily rejecting upgrades
            time.sleep(0.35 * attempt)

    if last_err is not None:
        raise SystemExit(f"WS smoke test failed: connect error: {last_err}")

    if not got_connected.wait(timeout=5):
        sio.disconnect()
        raise SystemExit("WS smoke test failed: did not receive 'connected' event")

    benign = 0
    attack = 0
    errors = 0
    last_result: object | None = None

    for i, payload in enumerate(payloads, start=1):
        got_result.clear()
        result_holder.clear()

        sio.emit("inference", payload, namespace="/ws/inference")
        if not got_result.wait(timeout=10):
            sio.disconnect()
            raise SystemExit(f"WS smoke test failed: no response from server (sample {i}/{len(payloads)})")

        if "error" in result_holder:
            errors += 1
            last_result = result_holder.get("error")
            continue

        res = result_holder.get("result")
        last_result = res
        try:
            if isinstance(res, dict) and res.get("is_attack"):
                attack += 1
            else:
                benign += 1
        except Exception:
            benign += 1

    sio.disconnect()
    print(
        f"WS smoke test done: total={len(payloads)} benign={benign} attack={attack} errors={errors} "
        f"(last={last_result})"
    )


def _self_test() -> None:
    """Deterministic unit-ish check for FIN/RST close + direction detection."""

    export_q: queue.Queue[FlowState] = queue.Queue()
    fm = FlowManager(export_queue=export_q, flow_timeout_s=120.0, idle_timeout_s=10.0, activity_timeout_s=5.0)

    base = time.time()
    a_ip = "10.0.0.1"
    b_ip = "10.0.0.2"
    a_port = 12345
    b_port = 80

    def rec(ts_off: float, src: str, sport: int, dst: str, dport: int, flags: int, payload: int = 0) -> PacketRecord:
        # Minimal consistent sizes
        ip_hl = 20
        tcp_hl = 20
        pkt_len = ip_hl + tcp_hl + payload
        return PacketRecord(
            ts=base + ts_off,
            src_ip=src,
            dst_ip=dst,
            src_port=sport,
            dst_port=dport,
            proto=6,
            ip_header_len=ip_hl,
            l4_header_len=tcp_hl,
            pkt_len=pkt_len,
            payload_len=payload,
            tcp_flags=flags,
            tcp_window=64240,
        )

    # SYN (A -> B) defines forward
    fm.handle_packet(rec(0.00, a_ip, a_port, b_ip, b_port, flags=0x02))
    # SYN/ACK (B -> A)
    fm.handle_packet(rec(0.01, b_ip, b_port, a_ip, a_port, flags=0x12))
    # ACK (A -> B)
    fm.handle_packet(rec(0.02, a_ip, a_port, b_ip, b_port, flags=0x10))
    # Data (A -> B)
    fm.handle_packet(rec(0.03, a_ip, a_port, b_ip, b_port, flags=0x18, payload=100))
    # FIN from A
    fm.handle_packet(rec(0.10, a_ip, a_port, b_ip, b_port, flags=0x11))
    assert export_q.empty(), "Flow should not close on first FIN only"
    # FIN from B closes
    fm.handle_packet(rec(0.11, b_ip, b_port, a_ip, a_port, flags=0x11))
    flow = export_q.get(timeout=1.0)
    assert flow.should_close_on_tcp_flags(), "Flow should close after both FIN"

    row = flow.finalize_row()
    assert len(row) == len(FEATURES) == 72, "Row feature length mismatch"
    assert row[FEATURES.index("fwd_pkt_cnt")] >= 1, "Expected forward packets"

    # RST immediate close
    export_q2: queue.Queue[FlowState] = queue.Queue()
    fm2 = FlowManager(export_queue=export_q2, flow_timeout_s=120.0, idle_timeout_s=10.0, activity_timeout_s=5.0)
    fm2.handle_packet(rec(0.00, a_ip, a_port, b_ip, b_port, flags=0x02))
    fm2.handle_packet(rec(0.01, b_ip, b_port, a_ip, a_port, flags=0x14))  # RST+ACK
    f2 = export_q2.get(timeout=1.0)
    assert f2.should_close_on_tcp_flags(), "Flow should close on RST"

    print("✅ self-test passed")


if __name__ == "__main__":
    main()
