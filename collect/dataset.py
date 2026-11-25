"""Share the RadioHound recordings: pack them into one archive, fetch it back, and
read a recording in either format.

The recordings are written as complex float32 (cf32_le), but every value is an
8-bit HackRF sample divided by 127. `pack` stores them as SigMF ci8 instead,
which loses nothing and is 8 times smaller. `read_recording` returns complex64
for both formats, so code that reads recordings does not care which it gets.

    python -m collect.dataset pack     # maintainers: build the release archive
    python -m collect.dataset fetch    # everyone else: download and unpack it
"""

import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import numpy as np

from collect.radiohound import SAMPLE_SCALE

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("data/radiohound", "data/radiohound-room", "data/radiohound-ambient")
RELEASE = json.loads((Path(__file__).parent / "release.json").read_text())
# Samples to drop at the start of every recording (stale block and tuning transient).
SKIP_SAMPLES = 262_144


def read_recording(base, skip=SKIP_SAMPLES):
    """Samples (complex64, server scale) and metadata of <base>.sigmf-*."""
    base = str(base)
    meta = json.loads(Path(base + ".sigmf-meta").read_text())
    datatype = meta["global"]["core:datatype"]
    if datatype == "cf32_le":
        iq = np.fromfile(base + ".sigmf-data", dtype="<c8")
    elif datatype == "ci8":
        # Divided in float64, as the server does, so values match cf32 bit for bit.
        pairs = np.fromfile(base + ".sigmf-data", dtype=np.int8) / float(meta["global"]["argus:scale"])
        iq = (pairs[0::2] + 1j * pairs[1::2]).astype(np.complex64)
    else:
        raise ValueError(f"{base}: unsupported datatype {datatype}")
    return iq[skip:], meta


def to_ci8(iq):
    """cf32 samples to interleaved int8; refuses anything that is not exactly 8-bit."""
    pairs = iq.view(np.float32) * SAMPLE_SCALE
    ints = np.round(pairs)
    if np.abs(pairs - ints).max(initial=0) > 1e-3 or ints.min(initial=0) < -128 or ints.max(initial=0) > 127:
        raise ValueError("Samples are not 8-bit values divided by 127")
    return ints.astype(np.int8)


def _add(tar, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def pack(root, folders, archive):
    """Write every recording of `folders` (relative to root) as ci8 into a .tar.gz."""
    root, count = Path(root), 0
    with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
        for folder in folders:
            for path in sorted((root / folder).rglob("*")):
                name = str(path.relative_to(root))
                if path.name.endswith(".sigmf-meta"):
                    base = str(path)[: -len(".sigmf-meta")]
                    meta = json.loads(path.read_text())
                    if meta["global"]["core:datatype"] == "cf32_le":
                        ints = to_ci8(np.fromfile(base + ".sigmf-data", dtype="<c8"))
                        meta["global"]["core:datatype"] = "ci8"
                        meta["global"]["argus:scale"] = SAMPLE_SCALE
                        data = ints.tobytes()
                    else:
                        data = Path(base + ".sigmf-data").read_bytes()
                    _add(tar, name, json.dumps(meta, indent=1).encode())
                    _add(tar, name[: -len("meta")] + "data", data)
                    count += 1
                elif path.is_file() and not path.name.endswith(".sigmf-data"):
                    tar.add(path, name)  # manifest.csv, done.json
    return count


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(root=ROOT, release=RELEASE):
    """Download the release archive, check it, and unpack it under root/data/."""
    root = Path(root)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / release["asset"]
        print(f"Downloading {release['url']} ({release['bytes'] / 1e6:.0f} MB) ...")
        with urllib.request.urlopen(release["url"]) as response, open(archive, "wb") as out:
            shutil.copyfileobj(response, out)
        if sha256(archive) != release["sha256"]:
            raise ValueError("Download does not match the expected checksum")
        with tarfile.open(archive) as tar:
            tar.extractall(root, filter="data")
    for folder in FOLDERS:
        rows = list(csv.DictReader(open(root / folder / "manifest.csv")))
        print(f"{folder}: {len(rows)} recordings")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pack", help="build the release archive from data/radiohound*")
    p.add_argument("--out", default=f"data/{RELEASE['asset']}")
    sub.add_parser("fetch", help="download and unpack the release archive into data/")
    args = parser.parse_args(argv)
    if args.command == "pack":
        count = pack(ROOT, FOLDERS, args.out)
        print(f"{count} recordings -> {args.out}, {Path(args.out).stat().st_size / 1e6:.0f} MB, "
              f"sha256 {sha256(args.out)}")
    else:
        fetch()


if __name__ == "__main__":
    sys.exit(main())
