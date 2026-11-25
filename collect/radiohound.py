"""Client for RadioHound's capture server.

One request makes the HackRF on a sensor node record about 26 ms (524,288 I/Q
samples at 20 MS/s) and returns it as JSON with the samples base64-encoded
complex64. A request takes about 20 s, almost all of it waiting on the server.
Standard library only, so CI needs nothing extra.
"""

import base64
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import numpy as np

SERVER = "http://radiohound2.ee.nd.edu:8000"
NODE = "3484e4fcf564"

# The server sends HackRF 8-bit samples divided by 127, so a step is 1/127 and
# the largest value is 1.0 (-128 reads as -128/127).
SAMPLE_SCALE = 127
FULL_SCALE = 1.0


@dataclass
class Capture:
    iq: np.ndarray
    sample_rate: float
    center_frequency: float
    gain: int
    timestamp: str
    info: dict = field(default_factory=dict)  # every other field from the server


def parse_capture(payload):
    """Turn the server's JSON into a Capture."""
    if payload.get("type", "complex64") != "complex64":
        raise ValueError("Unexpected sample type " + repr(payload.get("type")))
    iq = np.frombuffer(base64.b64decode(payload["data"]), dtype=np.complex64)
    info = {k: v for k, v in payload.items() if k != "data"}
    return Capture(iq=iq, sample_rate=float(payload["sample_rate"]),
                   center_frequency=float(payload["center_frequency"]),
                   gain=int(payload["gain"]), timestamp=str(payload["timestamp"]),
                   info=info)


class RadioHoundClient:
    """Fetch captures one at a time, with a minimum gap between requests so the
    shared server is never hammered."""

    def __init__(self, server=SERVER, node=NODE, min_gap_s=2.0, retries=2, timeout_s=90):
        self.server = server.rstrip("/")
        self.node = node
        self.min_gap_s = min_gap_s
        self.retries = retries
        self.timeout_s = timeout_s
        self._last = 0.0

    def url(self, freq_mhz, gain):
        query = urllib.parse.urlencode({"freq": freq_mhz, "timeout": 30, "gain": gain})
        return "{}/api/scan/{}/raw?{}".format(self.server, self.node, query)

    def _get(self, url):
        with urllib.request.urlopen(url, timeout=self.timeout_s) as response:
            return json.load(response)

    def capture(self, freq_mhz, gain):
        url = self.url(freq_mhz, gain)
        for attempt in range(self.retries + 1):
            wait = self.min_gap_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                payload = self._get(url)
                self._last = time.monotonic()
                return parse_capture(payload)
            except Exception:
                self._last = time.monotonic()
                if attempt == self.retries:
                    raise
                time.sleep(10 * (attempt + 1))  # back off before retrying


class FakeClient:
    """Stands in for the server in dry runs and tests: noise, plus a tone when the
    linked demo generator has RF on."""

    def __init__(self, generator=None, n=4096, seed=0):
        self.generator = generator
        self.n = n
        self.rng = np.random.default_rng(seed)

    def capture(self, freq_mhz, gain):
        noise = (self.rng.normal(size=self.n) + 1j * self.rng.normal(size=self.n)) * 0.01
        if self.generator is not None and self.generator.read_status()["rf_on"]:
            noise += 0.2 * np.exp(2j * np.pi * 0.1 * np.arange(self.n))
        iq = (np.round(noise.real * 128) + 1j * np.round(noise.imag * 128)) / 128
        return Capture(iq=iq.astype(np.complex64), sample_rate=20e6,
                       center_frequency=freq_mhz * 1e6, gain=gain,
                       timestamp="1970-01-01T00:00:00+00:00", info={"fake": True})
