"""`python -m pipeline.ingest --classify`: new fields with the flag, byte-identical output without it."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from pipeline.ingest import main

FS = 2e6  # a raw recording well below 20 MS/s, like an RTL-SDR
CENTRE = 433.92e6

# sha256 of the output of `main` on the fixtures below, recorded at d2b4208, before
# --classify existed. Without --classify the output must stay exactly this.
GOLDEN = {
    "raw": "bc73887a50a6ff7e8a340a901abcb1e86fdd08b5ac7d3851dc5d2c88eb302b38",
    "sigmf": "b3351bf2c0a944b006bfed450a94912ff352f371ce04479d8c83b9ff2284284b",
}


def capture(n=400_000, seed=7):
    """Noise with two tone bursts, as interleaved values."""
    rng = np.random.default_rng(seed)
    iq = 0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    t = np.arange(n) / FS
    for a, b, f in ((50_000, 90_000, 200e3), (250_000, 330_000, -300e3)):
        iq[a:b] += 0.5 * np.exp(2j * np.pi * f * t[a:b])
    return iq


def raw_file(tmp_path):
    iq = capture()
    values = np.empty(2 * len(iq), dtype=np.int8)
    values[0::2] = np.clip(np.round(iq.real * 127), -128, 127)
    values[1::2] = np.clip(np.round(iq.imag * 127), -128, 127)
    path = tmp_path / "capture.cs8"
    values.tofile(path)
    return path


def sigmf_file(tmp_path):
    iq = capture(seed=8).astype(np.complex64)
    data = tmp_path / "rec.sigmf-data"
    iq.view(np.float32).astype("<f4").tofile(data)
    meta = {
        "global": {"core:datatype": "cf32_le", "core:sample_rate": FS, "core:version": "1.0.0"},
        "captures": [{"core:sample_start": 0, "core:frequency": 2.437e9},
                     {"core:sample_start": 200_000, "core:frequency": 915e6}],
        "annotations": [],
    }
    (tmp_path / "rec.sigmf-meta").write_text(json.dumps(meta))
    return tmp_path / "rec.sigmf-meta"


def run(argv, tmp_path, name="out.jsonl"):
    out = tmp_path / name
    assert main([*argv, "-o", str(out)]) == 0
    return out.read_bytes()


def test_without_classify_output_is_byte_identical(tmp_path):
    raw = run([str(raw_file(tmp_path)), "--sample-rate", "2M", "--center-freq", "433.92M"], tmp_path, "raw.jsonl")
    sig = run([str(sigmf_file(tmp_path))], tmp_path, "sig.jsonl")
    assert hashlib.sha256(raw).hexdigest() == GOLDEN["raw"]
    assert hashlib.sha256(sig).hexdigest() == GOLDEN["sigmf"]
    for line in (raw + sig).decode().splitlines():
        row = json.loads(line)
        assert not {"signal_class", "class_confidence", "class_probs"} & set(row)


if __name__ == "__main__":  # print the golden hashes (run once on the commit before --classify)
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        raw = run([str(raw_file(d)), "--sample-rate", "2M", "--center-freq", "433.92M"], d, "raw.jsonl")
        sig = run([str(sigmf_file(d))], d, "sig.jsonl")
        print("raw", hashlib.sha256(raw).hexdigest(), len(raw.splitlines()))
        print("sigmf", hashlib.sha256(sig).hexdigest(), len(sig.splitlines()))
        sys.stdout.write(sig.decode())
