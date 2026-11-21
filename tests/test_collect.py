"""The RadioHound collection script, run against the simulated generator and a
fake capture server. Nothing here touches the network or real hardware."""

import base64
import csv
import json

import numpy as np
import pytest

from collect import sweep
from collect.radiohound import FakeClient, parse_capture
from collect.siggen.n5172b_control import N5172BController

PLAN = {
    "carrier_mhz": 2927, "gain": 30, "captures_per_row": 2,
    "powers_dbm": [-60, -40], "offsets_hz": [-3e6, 3e6],
    "signals": [{"mode": "CW"}, {"mode": ["BPSK", "OFDM"], "bandwidth_hz": 2e6}],
}


def test_plan_expands_lists():
    rows = sweep.expand_plan(PLAN)
    assert len(rows) == 3 * 2 * 2  # CW, BPSK, OFDM x 2 powers x 2 offsets
    assert len({r["id"] for r in rows}) == len(rows)


def test_cw_moves_the_carrier_off_center():
    gen = N5172BController(demo=True)
    gen.connect()
    row = next(r for r in sweep.expand_plan(PLAN) if r["mode"] == "CW")
    sweep.transmit(gen, row, 2927e6)
    assert gen.read_status()["frequency_hz"] == 2927e6 + row["frequency_offset_hz"] != 2927e6


def test_power_above_limit_is_refused():
    with pytest.raises(ValueError, match="limit"):
        sweep.expand_plan(dict(PLAN, powers_dbm=[-5]))


def test_signal_outside_the_recording_is_refused():
    plan = dict(PLAN, offsets_hz=[8e6], signals=[{"mode": "OFDM", "bandwidth_hz": 5e6}])
    with pytest.raises(ValueError, match="past"):
        sweep.expand_plan(plan)


def test_unknown_setting_is_refused():
    with pytest.raises(ValueError, match="Unknown"):
        sweep.expand_plan(dict(PLAN, signals=[{"mode": "BPSK", "bandwith_hz": 1e6}]))


def test_quality_flags_clipping_and_measures_snr():
    rng = np.random.default_rng(0)
    noise = (rng.normal(size=4096) + 1j * rng.normal(size=4096)) * 0.01
    signal = noise + 0.1 * np.exp(2j * np.pi * 0.1 * np.arange(4096))
    q = sweep.quality(signal, sweep.band_power(noise))
    assert q["snr_db"] == pytest.approx(17, abs=1) and not q["clipped"]
    assert sweep.quality(np.full(16, 0.999 + 0j))["clipped"]


def test_parse_capture_reads_server_json():
    iq = (np.arange(8) + 1j).astype(np.complex64)
    payload = {"data": base64.b64encode(iq.tobytes()).decode(), "type": "complex64",
               "sample_rate": 20e6, "center_frequency": 2927e6, "gain": 30,
               "timestamp": "2026-11-20T18:17:50+00:00", "mac_address": "abc"}
    cap = parse_capture(payload)
    assert np.array_equal(cap.iq, iq) and cap.info["mac_address"] == "abc"
    assert "data" not in cap.info


def _run(tmp_path):
    gen = N5172BController(demo=True)
    gen.connect()
    sweep.run_sweep(PLAN, gen, FakeClient(gen, n=1024), tmp_path)
    return gen


def test_sweep_writes_sigmf_and_resumes(tmp_path):
    gen = _run(tmp_path)
    assert not gen.read_status()["rf_on"]
    rows = list(csv.DictReader(open(tmp_path / "manifest.csv")))
    assert len(rows) == 12 * 3  # one RF-off and two RF-on recordings per row
    on = [r for r in rows if r["rf"] == "on"]
    assert all(float(r["snr_db"]) > 10 for r in on)

    meta = json.loads(open(on[0]["file"] + ".sigmf-meta").read())
    assert meta["global"]["core:datatype"] == "cf32_le"
    data = np.fromfile(on[0]["file"] + ".sigmf-data", dtype="<c8")
    assert len(data) == meta["annotations"][0]["core:sample_count"] == 1024

    _run(tmp_path)  # every row is done, so nothing new is recorded
    assert len(list(csv.DictReader(open(tmp_path / "manifest.csv")))) == len(rows)


def test_rf_goes_off_when_a_capture_fails(tmp_path):
    gen = N5172BController(demo=True)
    gen.connect()

    class Broken(FakeClient):
        calls = 0

        def capture(self, freq_mhz, gain):
            Broken.calls += 1
            if Broken.calls == 2:  # first RF-on recording
                raise ConnectionError("server down")
            return super().capture(freq_mhz, gain)

    with pytest.raises(ConnectionError):
        sweep.run_sweep(PLAN, gen, Broken(gen, n=256), tmp_path)
    assert not gen.read_status()["rf_on"]


def test_sweep_can_run_in_sections(tmp_path):
    gen = N5172BController(demo=True)
    gen.connect()
    client = FakeClient(gen, n=256)
    sweep.run_sweep(PLAN, gen, client, tmp_path, only="ofdm", max_rows=2)
    done = sorted(p.parent.name for p in tmp_path.glob("*/done.json"))
    assert len(done) == 2 and all(d.startswith("OFDM") for d in done)
    sweep.run_sweep(PLAN, gen, client, tmp_path, only="OFDM")
    assert len(list(tmp_path.glob("OFDM*/done.json"))) == 4
