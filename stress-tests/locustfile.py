"""
SecureCore IDS — Locust Stress Test
Full pipeline: WebSocket connect → send features → receive ML result

Simulates multiple IDS clients sending network traffic features
through the WebSocket inference pipeline.

Usage:
  # Web UI (interactive, with charts)
  locust -f locustfile.py --host http://localhost:5000

  # Headless (for research paper data)
  locust -f locustfile.py --host http://localhost:5000 \
    --headless -u 50 -r 5 -t 120s \
    --csv results/test_50users

  # Multiple concurrency levels
  python run_benchmark.py
"""

import time
import random
import json
import logging
from locust import User, task, between, events, constant_pacing
import socketio

logger = logging.getLogger(__name__)

# ─── Configuration ───
API_TOKEN = "sk_live_securecore_LEZXYFXm8T_0bssp3i0thWvGcJoEsw-3-_a_N4M4st-uuI053jbURTts5zqAhoMb"
WS_NAMESPACE = "/ws/inference"
NUM_FEATURES = 72


def generate_random_features():
    """Generate a realistic random feature vector (72 features).
    
    Simulates CICFlowMeter/Lycos-IDS2017 extracted features.
    Features include flow duration, packet counts, byte counts,
    inter-arrival times, flags, etc.
    """
    features = []
    
    # Flow Duration (microseconds, 0 - 120,000,000)
    features.append(random.uniform(0, 120_000_000))
    
    # Total Fwd/Bwd Packets (0-10000)
    features.append(random.randint(0, 10000))
    features.append(random.randint(0, 10000))
    
    # Total Length of Fwd/Bwd Packets
    features.append(random.uniform(0, 1_000_000))
    features.append(random.uniform(0, 1_000_000))
    
    # Fwd/Bwd Packet Length (max, min, mean, std)
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
    
    # Flags (PSH, URG counts, etc.)
    for _ in range(8):
        features.append(random.randint(0, 100))
    
    # Header lengths, packet sizes, etc.
    for _ in range(10):
        features.append(random.uniform(0, 65535))
    
    # FIN, SYN, RST, PSH, ACK, URG, CWE, ECE flag counts
    for _ in range(8):
        features.append(random.randint(0, 1))
    
    # Down/Up Ratio, Avg Packet Size, etc.
    for _ in range(5):
        features.append(random.uniform(0, 65535))
    
    # Subflow counts and bytes
    for _ in range(4):
        features.append(random.uniform(0, 100_000))
    
    # Init window bytes, act data pkt fwd, min seg size fwd
    for _ in range(4):
        features.append(random.uniform(0, 65535))
    
    # Active/Idle (mean, std, max, min)
    remaining = NUM_FEATURES - len(features)
    for _ in range(remaining):
        features.append(random.uniform(0, 10_000_000))
    
    return features[:NUM_FEATURES]


def generate_metadata():
    """Generate random packet metadata for the inference request."""
    return {
        "source_ip": f"192.168.{random.randint(1, 254)}.{random.randint(1, 254)}",
        "destination_ip": f"10.0.{random.randint(0, 10)}.{random.randint(1, 254)}",
        "source_port": random.randint(1024, 65535),
        "destination_port": random.choice([80, 443, 22, 53, 8080, 3389, 3306]),
        "protocol": random.choice(["TCP", "UDP"]),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


class SocketIOUser(User):
    """Simulates an IDS client connecting via WebSocket and sending
    network features for ML inference.

    Each user:
    1. Connects to /ws/inference with an API token
    2. Sends continuous inference requests (features + metadata)
    3. Waits for and records inference_result responses
    4. Measures end-to-end latency for each request
    """

    # Wait 0.5-2s between inference requests
    wait_time = between(0.5, 2.0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sio = None
        self._connected = False
        self._pending_requests = {}  # track sent timestamps for latency
        self._request_counter = 0

    def on_start(self):
        """Connect to WebSocket when user starts."""
        self.sio = socketio.Client(
            reconnection=False,
            logger=False,
            engineio_logger=False,
        )

        # ─── Event Handlers ───
        @self.sio.on("connected", namespace=WS_NAMESPACE)
        def on_connected(data):
            self._connected = True
            logger.info(f"[User] Connected: {data}")

        @self.sio.on("inference_result", namespace=WS_NAMESPACE)
        def on_inference_result(data):
            # Calculate end-to-end latency
            recv_time = time.time()

            # Find the oldest pending request (FIFO)
            if self._pending_requests:
                oldest_key = min(self._pending_requests.keys())
                send_time = self._pending_requests.pop(oldest_key)
                latency_ms = (recv_time - send_time) * 1000

                # Report to Locust
                is_error = "error" in data
                events.request.fire(
                    request_type="WSS",
                    name="inference_result",
                    response_time=latency_ms,
                    response_length=len(json.dumps(data)),
                    exception=data.get("error") if is_error else None,
                )

                if not is_error:
                    attack_type = data.get("attack_type", "unknown")
                    confidence = data.get("confidence", 0)
                    logger.debug(
                        f"[Result] {attack_type} ({confidence:.2%}) in {latency_ms:.1f}ms"
                    )

        @self.sio.on("inference_queued", namespace=WS_NAMESPACE)
        def on_queued(data):
            pass  # ACK received, result coming async

        @self.sio.on("error", namespace=WS_NAMESPACE)
        def on_error(data):
            events.request.fire(
                request_type="WSS",
                name="ws_error",
                response_time=0,
                response_length=0,
                exception=data.get("message", "Unknown WS error"),
            )

        # Attempt connection
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
        """Disconnect when user stops."""
        if self.sio and self.sio.connected:
            try:
                self.sio.disconnect()
            except Exception:
                pass

    @task
    def send_inference(self):
        """Send a single inference request with network traffic features."""
        if not self._connected or not self.sio or not self.sio.connected:
            return

        self._request_counter += 1
        req_id = self._request_counter

        # Build payload matching the server's expected format
        payload = {
            "features": generate_random_features(),
            **generate_metadata(),
        }

        # Record send time for latency measurement
        self._pending_requests[req_id] = time.time()

        try:
            self.sio.emit("inference", payload, namespace=WS_NAMESPACE)
        except Exception as e:
            # Remove pending request on send failure
            self._pending_requests.pop(req_id, None)
            events.request.fire(
                request_type="WSS",
                name="inference_send_error",
                response_time=0,
                response_length=0,
                exception=str(e),
            )
