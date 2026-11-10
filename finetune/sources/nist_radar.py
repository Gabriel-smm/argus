"""Turn one subset of the NIST 3.5 GHz radar dataset (mds2-2116) into training rows.

The dataset is 200 files of 200 simulated radar waveforms each: pulse trains of
five kinds (P0N#1, P0N#2, Q3N#1-3) in white noise, 80 ms at 10 MS/s, about half of
them noise only. This script fetches a single subset and its label table, runs
`pipeline.features.detect_bursts` on every waveform that holds a radar signal, and
writes one row per detected burst. The waveforms are baseband; the centre frequency
is assigned (the middle of the CBRS band), so `frequency_assigned` is true.

Licence: NIST data, public domain in the United States (data.nist.gov/od/id/mds2-2116).
"""

import argparse
import csv
import statistics

import h5py
import numpy as np

from finetune.sources.common import RAW, TRAIN, write_jsonl
from finetune.sources.fetch import download, sha256
from pipeline.features import detect_bursts

GROUP = 1
SUBSET = 1
BASE = "https://data.nist.gov/od/ds/ark:/88434/mds2-2116/SimulatedRadarWaveforms"
FILES = [
    (
        f"{BASE}/Group{GROUP}/group{GROUP}_subset_{SUBSET}.mat",
        f"nist_radar/group{GROUP}_subset_{SUBSET}.mat",
        2463731809,
        "e5e3d1c76892266d484abe1670723922759c0b94d02d750dffdfcf7da330f2d5",
    ),
    (
        f"{BASE}/Group{GROUP}/group{GROUP}_subset_CSVInfo/group{GROUP}_waveformTableSubset_{SUBSET}.csv",
        f"nist_radar/group{GROUP}_waveformTableSubset_{SUBSET}.csv",
        19761,
        "ae77c6d221aa1bc44238f64059ecf0c3a2ad955b8c440159e861ea7b93d336f1",
    ),
]
DATASET = RAW / FILES[0][1]
TABLE = RAW / FILES[1][1]
OUTPUT = TRAIN / "nist_radar.jsonl"
SOURCE = "nist_radar_mds2-2116"
LABEL_SERVICE = "pulsed_radar"
# The waveforms are baseband. They are placed in the middle of the 3.55-3.70 GHz
# CBRS band, where the radars they imitate operate.
CENTER_FREQUENCY_HZ = 3.55e9
FEATURES = (
    "center_frequency_hz", "bandwidth_hz", "snr_db", "duty_cycle", "burst_duration_s",
    "hopping", "pulse_interval_s", "modulation", "truncated",
)


def fetch() -> None:
    for url, name, size, checksum in FILES:
        target = RAW / name
        download(url, target, size)
        if sha256(target) != checksum:
            raise SystemExit(f"{target} failed its sha256 check. Delete it and run again.")


def load_table() -> list[dict]:
    with open(TABLE) as source:
        return list(csv.DictReader(source))


# The HDF5 chunks are (200, 20) and gzip-compressed: every chunk holds all 200
# waveforms, so reading one waveform decompresses the whole file. Reading all of
# them in column blocks costs the same as reading one (about 15 s, 1.3 GB in memory).
BLOCK = 40_000


def waveforms(limit: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """The IQ matrix as complex64 (one waveform per row) and the radar-present flags."""
    if not DATASET.exists():
        raise SystemExit(f"{DATASET} is missing. Run: python -m finetune.sources.nist_radar --fetch")
    with h5py.File(DATASET, "r") as store:
        data = store[f"group{GROUP}_waveformSubset_{SUBSET}"]
        status = np.asarray(store[f"group{GROUP}_radarStatusSubset_{SUBSET}"]).reshape(-1).astype(bool)
        rows = data.shape[0] if limit is None else min(limit, data.shape[0])
        iq = np.empty((rows, data.shape[1]), dtype=np.complex64)
        for start in range(0, data.shape[1], BLOCK):
            iq[:, start : start + BLOCK] = as_complex(data[:rows, start : start + BLOCK])
    return iq, status[:rows]


def as_complex(block) -> np.ndarray:
    """MATLAB v7.3 stores complex arrays as a compound (real, imag) dtype."""
    block = np.asarray(block)
    if block.dtype.names:
        return (block["real"] + 1j * block["imag"]).astype(np.complex64)
    return block.astype(np.complex64)


def expected(info: dict, iq: np.ndarray) -> dict:
    """What the label table says the detector should find.

    NIST's `SNR` column is a peak SNR whose reference bandwidth the data dictionary
    does not state, and it does not match the samples under any simple reading. So
    the SNR to check against is measured here from the labelled pulse positions:
    mean power inside the pulses over the noise power of the whole band.
    """
    fs = float(info["SamplingFrequency"])
    pps = float(info["PulsesPerSecond"])
    width = float(info["ActualPulseWidth"])
    start = float(info["radarSignalStartTime"])
    pulses = int(float(info["PulsesPerBurst"]))
    power = np.abs(iq) ** 2
    mask = np.zeros(len(power), dtype=bool)
    for k in range(pulses):
        a = int(round((start + k / pps) * fs))
        mask[a : a + int(round(width * fs))] = True
    noise = power[~mask].mean()
    return {
        "pulse_interval_s": 1 / pps,
        "duty_cycle": width * pps,
        "label_snr_db": float(info["SNR"]),
        "mean_snr_db": float(10 * np.log10(power[mask].mean() / noise)),
        "offset_hz": float(info["radarSignalCenterFreq"]),
        "pulses": pulses,
        "chirp_hz": float(info["ChirpWidth"]) if info["ChirpWidth"] != "NaN" else None,
    }


def histogram(name: str, values: list[float], bins: int = 12, width: int = 40) -> str:
    counts, edges = np.histogram(values, bins=bins)
    lines = [f"{name}  (n={len(values)}, min={min(values):.4g}, median={statistics.median(values):.4g}, max={max(values):.4g})"]
    for count, low, high in zip(counts, edges[:-1], edges[1:]):
        bar = "#" * round(width * count / max(counts.max(), 1))
        lines.append(f"  {low:>12.4g} - {high:<12.4g} {count:>4} {bar}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch", action="store_true", help="download the subset (2.5 GB) and its table first")
    parser.add_argument("--limit", type=int, default=None, help="only process the first N waveforms")
    parser.add_argument("--hist", action="store_true", help="print text histograms of the features")
    args = parser.parse_args()
    if args.fetch:
        fetch()

    table = load_table()
    data, status = waveforms(args.limit)
    count = len(status)
    rows, checks = [], []
    skipped = missed = 0
    missed_labels = []
    for index in range(count):
        info = table[index]
        if not status[index]:
            skipped += 1
            continue
        iq = data[index]
        bursts = detect_bursts(iq, float(info["SamplingFrequency"]), CENTER_FREQUENCY_HZ)
        if not bursts:
            missed += 1
            missed_labels.append((info["BinNo"], info["SNR"], expected(info, iq)["mean_snr_db"]))
            continue
        for burst in bursts:
            row = {key: burst[key] for key in FEATURES}
            row["center_frequency_hz"] = round(row["center_frequency_hz"])
            row["bandwidth_hz"] = round(row["bandwidth_hz"])
            row["snr_db"] = round(row["snr_db"], 2)
            row["duty_cycle"] = round(row["duty_cycle"], 5)
            row.update(
                label_service=LABEL_SERVICE,
                label_signal=info["BinNo"],
                source=SOURCE,
                file=f"Group{GROUP}/group{GROUP}_subset_{SUBSET}.mat#{index}",
                simulated=True,
                frequency_assigned=True,
            )
            rows.append(row)
        checks.append((index, info["BinNo"], len(bursts), bursts[0], expected(info, iq)))

    print(f"waveforms: {count} read, {skipped} noise only, {missed} with radar but no burst found, {len(rows)} bursts")
    per_waveform = [c[2] for c in checks]
    print(f"bursts per radar waveform: min {min(per_waveform)}, median {statistics.median(per_waveform)}, max {max(per_waveform)}")

    if missed_labels:
        print("missed (bin, NIST SNR, mean in-pulse SNR over band noise):",
              ", ".join(f"{b} {s} {m:.1f}dB" for b, s, m in missed_labels))

    print("\nmeasured / expected, first burst of each waveform. 'mean snr' is mean in-pulse power over")
    print("whole-band noise, measured from the labelled positions; 'nist' is the table's SNR column.")
    print(f"{'idx':>4} {'bin':<6} {'#b':>2} {'interval ms':>18} {'duty':>14} {'mean snr dB':>14} {'nist':>5} {'offset kHz':>18} {'pulses':>10} {'bw MHz':>7} {'chirp':>6} {'hop':>5} {'trunc':>5}")
    for index, label, n, b, e in checks[:40]:
        interval = f"{(b['pulse_interval_s'] or float('nan'))*1e3:>8.3f}/{e['pulse_interval_s']*1e3:<8.3f}"
        duty = f"{b['duty_cycle']:>6.3f}/{e['duty_cycle']:<6.3f}"
        snr = f"{b['mean_snr_db']:>6.1f}/{e['mean_snr_db']:<6.1f}"
        offset = f"{(b['center_frequency_hz']-CENTER_FREQUENCY_HZ)/1e3:>8.1f}/{e['offset_hz']/1e3:<8.1f}"
        pulses = f"{b['pulses']:>4}/{e['pulses']:<4}"
        chirp = f"{e['chirp_hz']/1e6:>6.0f}" if e["chirp_hz"] else f"{'-':>6}"
        print(f"{index:>4} {label:<6} {n:>2} {interval:>18} {duty:>14} {snr:>14} {e['label_snr_db']:>5.0f} {offset:>18} {pulses:>10} {b['bandwidth_hz']/1e6:>7.2f} {chirp} {str(b['hopping']):>5} {str(b['truncated']):>5}")

    errors = {
        "pulse interval rel. error": [abs(b["pulse_interval_s"] / e["pulse_interval_s"] - 1) for *_, b, e in checks if b["pulse_interval_s"]],
        "duty cycle rel. error": [abs(b["duty_cycle"] / e["duty_cycle"] - 1) for *_, b, e in checks],
        "mean snr error dB": [b["mean_snr_db"] - e["mean_snr_db"] for *_, b, e in checks],
        "centre offset error kHz": [(b["center_frequency_hz"] - CENTER_FREQUENCY_HZ - e["offset_hz"]) / 1e3 for *_, b, e in checks],
        "pulse count error": [b["pulses"] - e["pulses"] for *_, b, e in checks],
    }
    print()
    for name, values in errors.items():
        if values:
            print(f"{name:<28} median {statistics.median(values):>8.3f}   p90 |.| {np.percentile(np.abs(values), 90):>8.3f}   n={len(values)}")

    if args.hist:
        report = []
        for key in ("bandwidth_hz", "snr_db", "duty_cycle", "burst_duration_s", "pulse_interval_s"):
            values = [row[key] for row in rows if row[key] is not None]
            if values:
                report.append(histogram(key, values))
        report.append(f"hopping: {sum(r['hopping'] for r in rows)} of {len(rows)}   truncated: {sum(r['truncated'] for r in rows)} of {len(rows)}")
        text = "\n\n".join(report)
        print("\n" + text)
        out = TRAIN.parent.parent / "finetune" / "out" / "nist_radar_hist.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
        print(f"\nsaved {out}")

    if args.limit is None:
        write_jsonl(OUTPUT, rows)
        print(f"wrote {len(rows)} rows to {OUTPUT}")
    else:
        print(f"--limit set: not writing {OUTPUT}")


if __name__ == "__main__":
    main()
