"""
SecureCore IDS — Stress-to-Fail Ramp-Up Test
Gradually increases concurrent users until the system degrades.

Breaking-point criteria (whichever comes first):
  - P99 latency > 1000ms (1 second)
  - Inference error rate > 5%

Usage:
  locust -f locustfile_stress.py --host http://localhost:5000 \
    --headless -u 500 -r 10 -t 300s \
    --csv results/stress_rampup --csv-full-history
"""

import time
import random
import json
import logging
from locust import User, task, between, events
import socketio

logger = logging.getLogger(__name__)

# ─── Configuration ───
API_TOKEN = "sk_live_securecore_KP-hBxdMdXz4oj4sRTWzfb7tmy7JoEs8QMUtZYQB7ScGs36nS4_Sl1nZ5QQTkkER"
WS_NAMESPACE = "/ws/inference"
NUM_FEATURES = 72


def generate_random_features():
    """Generate a realistic random 72-feature CICFlowMeter vector."""
    features = []
    # Flow Duration (microseconds)
    features.append(random.uniform(0, 120_000_000))
    # Total Fwd/Bwd Packets
    features.append(random.randint(0, 10000))
    features.append(random.randint(0, 10000))
    # Total Length Fwd/Bwd Packets
    features.append(random.uniform(0, 1_000_000))
    features.append(random.uniform(0, 1_000_000))
    # Packet length stats (max, min, mean, std) x2
    for _ in range(8):
        features.append(random.uniform(0, 65535))
    # Flow Bytes/s, Flow Packets/s
    features.append(random.uniform(0, 1_000_000))
    features.append(random.uniform(0, 100_000))
    # Flow IAT (mean, std, max, min)
    for _ in range(4):
        features.append(random.uniform(0, 10_000_000))
    # Fwd IAT (total, mean, std, max, min)
    for _ in range(5):
        features.append(random.uniform(0, 10_000_000))
    # Bwd IAT (total, mean, std, max, min)
    for _ in range(5):
        features.append(random.uniform(0, 10_000_000))
    # Flag counts, header lengths, etc.
    for _ in range(18):
        features.append(random.randint(0, 100))
    # FIN, SYN, RST, PSH, ACK, URG, CWE, ECE
    for _ in range(8):
        features.append(random.randint(0, 1))
    # Remaining features
    remaining = NUM_FEATURES - len(features)
    for _ in range(remaining):
        features.append(random.uniform(0, 65535))
    return features[:NUM_FEATURES]


def generate_metadata():
    """Generate random packet metadata."""
    return {
        "source_ip": f"192.168.{random.randint(1, 254)}.{random.randint(1, 254)}",
        "destination_ip": f"10.0.{random.randint(0, 10)}.{random.randint(1, 254)}",
        "source_port": random.randint(1024, 65535),
        "destination_port": random.choice([80, 443, 22, 53, 8080, 3389]),
        "protocol": random.choice(["TCP", "UDP"]),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


class StressUser(User):
    """Simulates an IDS client. Sends inference requests continuously
    and measures end-to-end latency.

    wait_time between requests is tight (0.2-0.5s) to maximise load.
    """

    wait_time = between(0.2, 0.5)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sio = None
        self._connected = False
        self._pending = {}
        self._counter = 0

    def on_start(self):
        """Connect to WebSocket when user starts."""
        self.sio = socketio.Client(
            reconnection=False,
            logger=False,
            engineio_logger=False,
        )

        @self.sio.on("connected", namespace=WS_NAMESPACE)
        def on_connected(data):
            self._connected = True

        @self.sio.on("inference_result", namespace=WS_NAMESPACE)
        def on_inference_result(data):
            recv_time = time.time()
            if self._pending:
                oldest_key = min(self._pending.keys())
                send_time = self._pending.pop(oldest_key)
                latency_ms = (recv_time - send_time) * 1000
                is_error = "error" in data
                events.request.fire(
                    request_type="WSS",
                    name="inference_result",
                    response_time=latency_ms,
                    response_length=len(json.dumps(data)),
                    exception=data.get("error") if is_error else None,
                )

        @self.sio.on("inference_queued", namespace=WS_NAMESPACE)
        def on_queued(data):
            pass

        @self.sio.on("error", namespace=WS_NAMESPACE)
        def on_error(data):
            events.request.fire(
                request_type="WSS",
                name="ws_error",
                response_time=0,
                response_length=0,
                exception=data.get("message", "Unknown WS error"),
            )

        connect_start = time.time()
        try:
            self.sio.connect(
                self.host,
                namespaces=[WS_NAMESPACE],
                auth={"api_token": API_TOKEN},
                wait_timeout=30,
            )
            connect_time = (time.time() - connect_start) * 1000
            events.request.fire(
                request_type="WSS",
                name="ws_connect",
                response_time=connect_time,
                response_length=0,
                exception=None,
            )
        except Exception as e:
            connect_time = (time.time() - connect_start) * 1000
            events.request.fire(
                request_type="WSS",
                name="ws_connect",
                response_time=connect_time,
                response_length=0,
                exception=str(e),
            )
            self._connected = False

    def on_stop(self):
        if self.sio and self.sio.connected:
            try:
                self.sio.disconnect()
            except Exception:
                pass

    @task
    def send_inference(self):
        """Send an inference request with 72 features + metadata."""
        if not self._connected or not self.sio or not self.sio.connected:
            return

        self._counter += 1
        req_id = self._counter

        payload = {
            "features": generate_random_features(),
            **generate_metadata(),
        }

        self._pending[req_id] = time.time()

        try:
            self.sio.emit("inference", payload, namespace=WS_NAMESPACE)
        except Exception as e:
            self._pending.pop(req_id, None)
            events.request.fire(
                request_type="WSS",
                name="inference_send_error",
                response_time=0,
                response_length=0,
                exception=str(e),
            )
