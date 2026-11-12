"""Turn a capture into a data file the Library accepts.

    python -m pipeline.ingest sweep.csv -o signals.jsonl
    python -m pipeline.ingest capture.cs8 --sample-rate 20M --center-freq 2.437G -o signals.jsonl
    python -m pipeline.ingest recording.sigmf-meta -o signals.jsonl

A `.csv` is read as rtl_power or hackrf_sweep output; `.sigmf-meta`, `.sigmf-data`
or `.sigmf` as a SigMF recording; `.cu8`, `.cs8`, `.ci16` and `.cf32` as raw IQ.
Every row has center_frequency_hz, bandwidth_hz and modulation ("unknown"), so the
file can be added under Data and classified as it is. The extra measurements
(power, noise floor, SNR, duty cycle, ...) ride along; the classifier ignores them.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from pipeline.inputs import InputError, combine_observations
from pipeline.iq import IQError, read_raw, read_sigmf
from pipeline.sweep import THRESHOLD_DB, SweepError, detect_signals, read_sweep

# What the dashboard accepts per data file (frontend/lib/laya-files.ts).
LIBRARY_LIMIT_BYTES = 2 * 1024 * 1024

_UNITS = {"": 1.0, "k": 1e3, "m": 1e6, "g": 1e9}


def hertz(text: str) -> float:
    """'2.437G', '20M', '915e6' or '433920000' in Hz."""
    match = re.fullmatch(r"\s*([0-9]*\.?[0-9]+(?:e[+-]?[0-9]+)?)\s*([kmg]?)(?:hz)?\s*", text.lower())
    if not match:
        raise argparse.ArgumentTypeError(f"{text!r} is not a frequency, such as 2.437G or 20M.")
    return float(match.group(1)) * _UNITS[match.group(2)]


def ingest(path: Path, sample_rate_hz: float | None = None, center_frequency_hz: float | None = None,
           datatype: str | None = None, threshold_db: float = THRESHOLD_DB) -> list[dict]:
    """Observation rows for one capture file, checked against the Library's rules."""
    path = Path(path)
    name = path.name.lower()
    if name.endswith((".sigmf-meta", ".sigmf-data", ".sigmf")):
        rows = read_sigmf(path)
    elif name.endswith(".csv"):
        rows = detect_signals(read_sweep(path.read_text()), threshold_db)
        for row in rows:
            row["source"] = path.name
    else:
        rows = read_raw(path, sample_rate_hz, center_frequency_hz, datatype)
    for index, row in enumerate(rows):
        row["id"] = index
    if rows:
        # The same check the Library runs, so a file written here is never refused there.
        combine_observations([(path.name, json.dumps(rows))], limit=len(rows))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Turn a sweep or IQ capture into Argus observation rows.")
    parser.add_argument("capture", type=Path, help="a .csv sweep, a SigMF recording, or a raw .cu8/.cs8/.ci16/.cf32 file")
    parser.add_argument("-o", "--output", type=Path, help="JSONL file to write (default: print to stdout)")
    parser.add_argument("--sample-rate", type=hertz, help="raw IQ only: samples per second, e.g. 20M")
    parser.add_argument("--center-freq", type=hertz, help="raw IQ only: the frequency the radio was tuned to, e.g. 2.437G")
    parser.add_argument("--format", dest="datatype", help="raw IQ only: cu8, ci8, ci16_le or cf32_le, when the suffix does not say")
    parser.add_argument("--threshold-db", type=float, default=THRESHOLD_DB,
                        help=f"sweeps only: how far above the noise floor a signal must rise (default {THRESHOLD_DB:g} dB)")
    args = parser.parse_args(argv)

    if not args.capture.exists():
        print(f"{args.capture} does not exist.", file=sys.stderr)
        return 1
    try:
        rows = ingest(args.capture, args.sample_rate, args.center_freq, args.datatype, args.threshold_db)
    except (SweepError, IQError, InputError) as exc:
        print(exc, file=sys.stderr)
        return 1

    text = "".join(json.dumps(row) + "\n" for row in rows)
    if args.output:
        args.output.write_text(text)
        print(f"wrote {len(rows)} signals to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    if not rows:
        print("No signal rose above the noise floor.", file=sys.stderr)
    if len(text.encode()) > LIBRARY_LIMIT_BYTES:
        print("The output is over the Library's 2 MB limit; split it before adding it under Data.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
