"""Collect labeled over-the-air recordings: the N5172B generator transmits a known
signal and the RadioHound HackRF next to it records it.

    python -m collect.sweep probe --mode BPSK --powers=-70,-60,-50,-40   # find a good power
    python -m collect.sweep run --plan collect/plans/saturday.json         # full sweep
    add --dry-run to either to use a simulated generator and server

Each plan row gets one recording with RF off (what was already on the air), then
several with RF on. Recordings are saved as SigMF under --out, one folder per row,
plus a manifest.csv line each. A finished row is skipped on the next run, so an
interrupted sweep resumes where it stopped. RF is switched off on every exit.
"""

import argparse
import csv
import dataclasses
import itertools
import json
import logging
import signal
import sys
from pathlib import Path

import numpy as np

from collect.radiohound import FULL_SCALE, FakeClient, RadioHoundClient
from collect.siggen.n5172b_control import N5172BController
from collect.siggen.n5172b_waveforms import WaveformConfig, build_waveform

GENERATOR_IP = "10.173.170.235"
MAX_POWER_DBM = -10.0      # agreed with RadioHound; never exceeded
CAPTURE_HALF_SPAN_HZ = 9e6  # HackRF records +/-10 MHz; keep signals 1 MHz inside
WAVEFORM_FIELDS = {f.name for f in dataclasses.fields(WaveformConfig)}
MANIFEST_FIELDS = ["row", "file", "rf", "mode", "power_dbm", "bandwidth_hz",
                   "offset_hz", "seed", "gain", "peak", "clipped", "snr_db", "timestamp"]

log = logging.getLogger("collect")


# ---------------------------------------------------------------- the plan

def _as_list(value):
    return value if isinstance(value, list) else [value]


def expand_plan(plan):
    """Turn a plan into rows. In each signal entry, list values are swept, so
    {"mode": "BPSK", "bandwidth_hz": [1e6, 2e6]} gives two signals. Each signal
    is then repeated for every power and frequency offset."""
    rows = []
    for spec in plan["signals"]:
        spec = dict(spec)
        unknown = set(spec) - WAVEFORM_FIELDS - {"mode"}
        if unknown:
            raise ValueError("Unknown signal settings: " + ", ".join(sorted(unknown)))
        keys = sorted(spec)
        for values in itertools.product(*(_as_list(spec[k]) for k in keys)):
            settings = dict(zip(keys, values))
            mode = settings["mode"].upper()
            offsets = [0.0] if mode == "CW" else plan["offsets_hz"]
            for power, offset in itertools.product(plan["powers_dbm"], offsets):
                rows.append(dict(settings, mode=mode, power_dbm=float(power),
                                 frequency_offset_hz=float(offset)))
    for index, row in enumerate(rows):
        row.setdefault("seed", plan.get("seed", 1000) + index)
        row["id"] = row_id(row)
        check_row(row)
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Two plan rows have the same settings")
    return rows


def row_id(row):
    parts = [row["mode"], "p{:g}".format(row["power_dbm"])]
    for key, tag in (("bandwidth_hz", "bw"), ("fm_deviation_hz", "dev"),
                     ("fm_tone_hz", "tone"), ("alpha", "a"), ("ofdm_fft", "fft")):
        if key in row:
            parts.append("{}{:g}".format(tag, row[key]))
    if row["mode"] != "CW":
        parts.append("off{:g}".format(row["frequency_offset_hz"]))
    parts.append("s{}".format(row["seed"]))
    return "_".join(parts).replace(".", "p").replace("-", "m").replace("+", "")


def waveform_for(row):
    """The generator waveform for a row, or None for an unmodulated carrier."""
    if row["mode"] == "CW":
        return None
    return build_waveform(WaveformConfig(**{k: v for k, v in row.items() if k in WAVEFORM_FIELDS}))


def check_row(row):
    """Refuse unsafe power and signals that would not fit in the recording."""
    if row["power_dbm"] > MAX_POWER_DBM:
        raise ValueError("{}: power {} dBm is above the {} dBm limit".format(
            row["id"], row["power_dbm"], MAX_POWER_DBM))
    waveform = waveform_for(row)
    if waveform is not None:
        meta = waveform.metadata
        if max(abs(meta["lower_edge_hz"]), abs(meta["upper_edge_hz"])) > CAPTURE_HALF_SPAN_HZ:
            raise ValueError("{}: signal reaches past +/-{:g} MHz of the recording".format(
                row["id"], CAPTURE_HALF_SPAN_HZ / 1e6))


# ---------------------------------------------------------------- recordings

def band_power(iq):
    """Mean power with the DC offset removed (the HackRF adds a large one)."""
    iq = iq.astype(np.complex128)
    return float(np.mean(np.abs(iq - iq.mean()) ** 2))


def quality(iq, noise_power=None):
    """Peak sample, whether the 8-bit receiver clipped, and the signal-to-noise
    ratio against an RF-off recording."""
    peak = float(max(np.abs(iq.real).max(), np.abs(iq.imag).max()))
    snr_db = None
    if noise_power:
        excess = band_power(iq) - noise_power
        snr_db = round(10 * np.log10(excess / noise_power), 2) if excess > 0 else float("-inf")
    return {"peak": round(peak, 4), "clipped": peak >= FULL_SCALE * 0.99, "snr_db": snr_db}


def write_sigmf(base, capture, label, extra):
    """Write <base>.sigmf-data (cf32_le) and <base>.sigmf-meta."""
    base.parent.mkdir(parents=True, exist_ok=True)
    capture.iq.astype("<c8").tofile(str(base) + ".sigmf-data")
    meta = {
        "global": {
            "core:datatype": "cf32_le",
            "core:sample_rate": capture.sample_rate,
            "core:version": "1.0.0",
            "core:hw": "HackRF One on RadioHound node {}, Keysight N5172B transmitter".format(
                capture.info.get("mac_address", "?")),
            "core:description": "Argus over-the-air collection",
            "argus:server": capture.info,
        },
        "captures": [{"core:sample_start": 0, "core:frequency": capture.center_frequency,
                      "core:datetime": capture.timestamp}],
        "annotations": [dict({"core:sample_start": 0, "core:sample_count": int(len(capture.iq)),
                              "core:label": label}, **{"argus:" + k: v for k, v in extra.items()})],
    }
    Path(str(base) + ".sigmf-meta").write_text(json.dumps(meta, indent=1, default=str))


class Manifest:
    def __init__(self, path):
        self.path = path
        new = not path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a", newline="")
        self.writer = csv.DictWriter(self.file, MANIFEST_FIELDS)
        if new:
            self.writer.writeheader()

    def add(self, **values):
        self.writer.writerow({k: values.get(k) for k in MANIFEST_FIELDS})
        self.file.flush()

    def close(self):
        self.file.close()


# ---------------------------------------------------------------- generator

def transmit(gen, row, carrier_hz):
    """Configure the generator for a row. RF stays off; the caller switches it on."""
    if row["power_dbm"] > MAX_POWER_DBM:  # second check, right before the instrument
        raise ValueError("Refusing power above {} dBm".format(MAX_POWER_DBM))
    gen.set_rf(False)
    gen.set_carrier(carrier_hz, row["power_dbm"])
    waveform = waveform_for(row)
    if waveform is None:
        gen.set_cw()
        return {"mode": "CW", "bandwidth_hz": 0.0}
    gen.apply_waveform(waveform)
    return waveform.metadata


def shutdown(gen):
    """Best effort: RF off and remove this session's waveforms."""
    for step in (lambda: gen.set_rf(False), gen.cleanup_waveforms):
        try:
            step()
        except Exception as exc:  # keep going; the next step may still work
            log.error("Shutdown step failed: %s. Check the generator's RF Off.", exc)


def _stop_on_sigterm():
    def handler(signum, frame):
        raise KeyboardInterrupt("SIGTERM")
    signal.signal(signal.SIGTERM, handler)


# ---------------------------------------------------------------- commands

def run_sweep(plan, gen, client, out_dir):
    rows = expand_plan(plan)
    carrier_hz = plan["carrier_mhz"] * 1e6
    gain, per_row = plan["gain"], plan["captures_per_row"]
    todo = [r for r in rows if not (out_dir / r["id"] / "done.json").exists()]
    minutes = len(todo) * (per_row + 1) * 21 / 60
    log.info("%d rows, %d left, about %.0f minutes", len(rows), len(todo), minutes)
    manifest = Manifest(out_dir / "manifest.csv")
    try:
        for number, row in enumerate(todo, 1):
            log.info("[%d/%d] %s", number, len(todo), row["id"])
            folder = out_dir / row["id"]
            for old in folder.glob("*.sigmf-*"):  # a half-finished row starts over
                old.unlink()
            labels = {k: v for k, v in row.items() if k != "id"}
            common = dict(row=row["id"], mode=row["mode"], power_dbm=row["power_dbm"],
                          bandwidth_hz=row.get("bandwidth_hz"),
                          offset_hz=row["frequency_offset_hz"], seed=row["seed"], gain=gain)

            gen.set_rf(False)
            off = client.capture(plan["carrier_mhz"], gain)
            noise = band_power(off.iq)
            q = quality(off.iq)
            write_sigmf(folder / "off_00", off, "noise", dict(labels, rf="off", **q))
            manifest.add(file=str(folder / "off_00"), rf="off", timestamp=off.timestamp, **common, **q)

            sent = transmit(gen, row, carrier_hz)
            gen.set_rf(True)
            try:
                for k in range(per_row):
                    cap = client.capture(plan["carrier_mhz"], gain)
                    q = quality(cap.iq, noise)
                    if q["clipped"]:
                        log.warning("  clipped (peak %.3f): lower the power or gain", q["peak"])
                    write_sigmf(folder / "on_{:02d}".format(k), cap, row["mode"],
                                dict(labels, rf="on", generator=sent, **q))
                    manifest.add(file=str(folder / "on_{:02d}".format(k)), rf="on",
                                 timestamp=cap.timestamp, **common, **q)
                    log.info("  on_%02d  snr %s dB  peak %.3f", k, q["snr_db"], q["peak"])
            finally:
                gen.set_rf(False)
            (folder / "done.json").write_text(json.dumps(row, indent=1))
    finally:
        manifest.close()


def run_probe(args, gen, client):
    """Step the power up for one signal, printing SNR, until it clips or hits the cap."""
    gen.set_rf(False)
    noise = band_power(client.capture(args.carrier_mhz, args.gain).iq)
    print("RF off: noise power {:.3g}".format(noise))
    for power in args.powers:
        row = {"mode": args.mode.upper(), "power_dbm": power, "bandwidth_hz": args.bandwidth_hz,
               "frequency_offset_hz": args.offset_hz, "seed": 1}
        row["id"] = row_id(row)
        check_row(row)
        transmit(gen, row, args.carrier_mhz * 1e6)
        gen.set_rf(True)
        try:
            q = quality(client.capture(args.carrier_mhz, args.gain).iq, noise)
        finally:
            gen.set_rf(False)
        print("{:>6.1f} dBm  snr {:>7} dB  peak {:.3f}{}".format(
            power, q["snr_db"], q["peak"], "  CLIPPED" if q["clipped"] else ""))
        if q["clipped"]:
            break


def _powers(text):
    return [float(p) for p in text.split(",") if p.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ip", default=GENERATOR_IP, help="generator address")
    parser.add_argument("--dry-run", action="store_true",
                        help="simulated generator and server; nothing is transmitted")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a sweep plan")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--out", type=Path, default=Path("data/radiohound"))
    probe = commands.add_parser("probe", help="find a usable power level")
    probe.add_argument("--mode", default="BPSK")
    probe.add_argument("--powers", type=_powers, default=_powers("-70,-60,-50,-40,-30,-20"))
    probe.add_argument("--bandwidth-hz", type=float, default=2e6)
    probe.add_argument("--offset-hz", type=float, default=3e6)
    probe.add_argument("--carrier-mhz", type=float, default=2927)
    probe.add_argument("--gain", type=int, default=30)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if args.command == "run":
        plan = json.loads(args.plan.read_text())
        expand_plan(plan)  # fail on a bad plan before touching the generator
        if args.dry_run:
            args.out = args.out.with_name(args.out.name + "-dryrun")
    gen = N5172BController(host=args.ip, timeout=15, demo=args.dry_run)
    client = FakeClient(gen) if args.dry_run else RadioHoundClient()
    _stop_on_sigterm()
    gen.connect()
    log.info("Generator: %s", gen.identity)
    try:
        if args.command == "run":
            run_sweep(plan, gen, client, args.out)
        else:
            run_probe(args, gen, client)
    except KeyboardInterrupt:
        log.warning("Stopped; finished rows are kept and will be skipped next time")
        return 130
    finally:
        shutdown(gen)
        gen.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
