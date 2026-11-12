"""Turn rtl_433's list of supported devices into data/context/ism_devices.csv.

rtl_433 (https://github.com/merbanan/rtl_433, GPL-2.0) decodes short bursts from
consumer devices in the 315, 433.92, 868 and 915 MHz ISM bands. We only keep its
device list, as a reference of what normally transmits in those bands.

Run once, with internet, from the repository root:

    python -m context_sources.rtl433

or point it at a README you already downloaded:

    python -m context_sources.rtl433 path/to/README.md
"""

import csv
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "context" / "ism_devices.csv"
README_URL = "https://raw.githubusercontent.com/merbanan/rtl_433/master/README.md"

# Line format in the README: "    [12]* Some Device Name"; "*" means off by default.
LINE = re.compile(r"^\s+\[(\d+)\](\*?)\s+(.+?)\s*$")

# First matching category wins; words match whole words only. Plain names an
# operator understands.
CATEGORIES = (
    ("tire pressure sensor", ("tpms", "tire", "tyre")),
    ("doorbell", ("doorbell", "door bell", "chime")),
    ("security sensor", ("security", "alarm", "smoke", "motion", "pir", "contact", "leak", "flood", "detector")),
    ("weather station", ("weather", "wetterstation", "rain", "wind", "lightning", "uv")),
    ("temperature / humidity sensor", ("temperature", "thermo", "thermometer", "hygro", "humidity", "pool", "bbq", "meat")),
    ("utility meter", ("meter", "ert", "energy", "power", "consumption", "solar", "electricity")),
    ("remote control", ("remote", "switch", "gate", "garage", "fob", "button", "outlet", "plug", "socket", "light")),
)
_PATTERNS = tuple(
    (category, re.compile(r"\b(" + "|".join(re.escape(word) for word in words) + r")s?\b", re.IGNORECASE))
    for category, words in CATEGORIES
)


def categorize(name):
    for category, pattern in _PATTERNS:
        if pattern.search(name):
            return category
    return "other device"


def parse(text):
    """Every supported device in the README, as dicts."""
    start = text.find("Supported device protocols")
    rows = []
    for line in text[start:].splitlines():
        match = LINE.match(line)
        if match:
            number, off, name = match.groups()
            rows.append(
                {
                    "rtl433_id": int(number),
                    "name": name,
                    "category": categorize(name),
                    "on_by_default": "no" if off else "yes",
                }
            )
        elif rows and line.strip() and not line.startswith(" "):
            break  # end of the device list
    return rows


def main():
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(README_URL, timeout=30) as response:
            text = response.read().decode("utf-8")
    rows = parse(text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rtl433_id", "name", "category", "on_by_default"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} device types to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
