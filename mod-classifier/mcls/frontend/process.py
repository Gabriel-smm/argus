"""One recording in, shards and rows out: survey, channelize, find bursts, cut, write.

The recording is read in chunks (never whole). The 20 MS/s stream is cut into
detection blocks of DETECT_BLOCK samples; a burst still running at the end of a
block that started in the block's second half is carried whole into the next
block, so it is detected and windowed once. Bursts longer than half a block are
split at the block edge (both pieces are windowed; detect_bursts marks them
truncated).
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from mcls.contracts import SAMPLE_DTYPE, SAMPLE_RATE_HZ, WINDOW_SAMPLES, ManifestRow, Recording, band_of
from mcls.frontend import windows as W
from mcls.frontend.channelize import Channelizer, choose_offset
from mcls.frontend.shards import MAX_WINDOWS_PER_SHARD, ShardWriter

#: Native samples read per call to Recording.read (16 MB of complex64).
READ_CHUNK = 1 << 21
#: 20 MS/s samples per detect_bursts call: about 0.21 s, as pipeline/iq.py.
DETECT_BLOCK = 1 << 22
BACKGROUND = "background"


@dataclass
class FrontendParams:
    max_windows_per_burst: int = W.MAX_PER_BURST
    max_windows_per_recording: int | None = None
    limit_seconds: float | None = None
    min_active: float = W.MIN_ACTIVE
    read_chunk: int = READ_CHUNK
    detect_block: int = DETECT_BLOCK
    max_windows_per_shard: int = MAX_WINDOWS_PER_SHARD


def stem_for(source_file: str) -> str:
    """'GPSL1+AMtone/x.bin' -> 'GPSL1+AMtone__x' (path separators flattened, last suffix dropped)."""
    flat = source_file.replace("\\", "/").replace("/", "__")
    stem = Path(flat).stem
    return stem or flat


def _finite(value, digits):
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if math.isfinite(value) else None


def base_row(rec: Recording, centre_hz: float) -> dict:
    """The ManifestRow fields shared by every window of a recording, in contract order, without split."""
    return {
        "window_id": "", "shard": "", "offset": 0, "length": WINDOW_SAMPLES,
        "dataset": rec.dataset, "recording_id": rec.recording_id,
        "label": rec.label, "label_strength": rec.label_strength,
        "native_rate_hz": float(rec.sample_rate_hz), "center_frequency_hz": float(centre_hz),
        "band": band_of(centre_hz), "is_real": bool(rec.is_real), "license": rec.license,
        "emitter_id": rec.emitter_id, "snr_db_est": None, "bandwidth_hz": None, "duty_cycle": None,
    }


def process_recording(rec: Recording, out_dir: Path, stem: str | None = None,
                      params: FrontendParams | None = None) -> dict:
    """Write `<stem>.sNNN.npy` and `<stem>.sNNN.rows.jsonl`; return the recording's stats."""
    params = params or FrontendParams()
    stem = stem or stem_for(rec.source_file)
    t_begin = time.perf_counter()
    timing = {"survey_s": 0.0, "read_s": 0.0, "channelize_s": 0.0, "detect_s": 0.0, "window_s": 0.0}

    n_total = rec.num_samples
    if params.limit_seconds is not None:
        n_total = min(n_total, max(1, int(round(params.limit_seconds * rec.sample_rate_hz))))

    t = time.perf_counter()
    offset = choose_offset(rec.read, n_total, rec.sample_rate_hz)
    timing["survey_s"] = time.perf_counter() - t
    ch = Channelizer(rec.sample_rate_hz, offset)
    centre = rec.center_frequency_hz + ch.offset_hz
    template = base_row(rec, centre)
    background = rec.label == BACKGROUND

    writer = ShardWriter(out_dir, stem, params.max_windows_per_shard)
    state = {"bursts": 0, "rejected": 0, "windows": 0, "blocks": 0, "done": False}
    buf = np.zeros(0, dtype=SAMPLE_DTYPE)
    buf_abs = 0  # 20 MS/s index of buf[0]
    produced = 0

    def handle(block: np.ndarray, final: bool) -> int:
        """Detect and window one block; return how many samples it consumed."""
        t0 = time.perf_counter()
        bursts = W.detect(block, centre)
        timing["detect_s"] += time.perf_counter() - t0
        consume = len(block)
        if not final:
            carried = [b for b in bursts if b["end"] >= len(block) - 1 and b["start"] > len(block) // 2]
            if carried:
                consume = min(b["start"] for b in carried)
                bursts = [b for b in bursts if b["start"] < consume]
        t0 = time.perf_counter()
        state["blocks"] += 1
        state["bursts"] += len(bursts)
        if background:
            wins = W.idle_windows(block[:consume], bursts, params.max_windows_per_burst)
        else:
            wins, rejected = W.burst_windows(block, bursts, params.max_windows_per_burst, params.min_active,
                                             floor=W.noise_floor(block))
            state["rejected"] += rejected
        cap = params.max_windows_per_recording
        if cap is not None and state["windows"] + len(wins) >= cap:
            wins = wins[: cap - state["windows"]]
            state["done"] = True
        samples = W.cut(block, wins)
        rows = []
        for w in wins:
            row = dict(template)
            row["window_id"] = f"{rec.dataset}/{stem}/{state['windows'] + len(rows):06d}"
            if w.burst is not None:
                row["snr_db_est"] = _finite(w.burst.get("snr_db"), 2)
                row["bandwidth_hz"] = _finite(w.burst.get("bandwidth_hz"), 0)
                row["duty_cycle"] = _finite(w.burst.get("duty_cycle"), 5)
            rows.append(row)
        writer.add(samples, rows)
        state["windows"] += len(rows)
        timing["window_s"] += time.perf_counter() - t0
        return consume

    try:
        start = 0
        while start < n_total and not state["done"]:
            count = min(params.read_chunk, n_total - start)
            t0 = time.perf_counter()
            x = rec.read(start, count)
            timing["read_s"] += time.perf_counter() - t0
            t0 = time.perf_counter()
            y = ch.process(x)
            timing["channelize_s"] += time.perf_counter() - t0
            start += count
            produced += len(y)
            buf = np.concatenate([buf, y])
            while len(buf) >= params.detect_block and not state["done"]:
                used = handle(buf[: params.detect_block], final=False)
                buf, buf_abs = buf[used:], buf_abs + used
        if not state["done"]:
            t0 = time.perf_counter()
            y = ch.flush()
            timing["channelize_s"] += time.perf_counter() - t0
            produced += len(y)
            buf = np.concatenate([buf, y])
            while len(buf) >= WINDOW_SAMPLES and not state["done"]:
                final = len(buf) <= params.detect_block
                used = handle(buf[: params.detect_block], final=final)
                buf, buf_abs = buf[used:], buf_abs + used
                if final:
                    break
    finally:
        writer.close()

    return {
        "dataset": rec.dataset,
        "recording_id": rec.recording_id,
        "source_file": rec.source_file,
        "stem": stem,
        "label": rec.label,
        "native_rate_hz": rec.sample_rate_hz,
        "recording_center_hz": rec.center_frequency_hz,
        "slice_offset_hz": ch.offset_hz,
        "slice_center_hz": centre,
        "resampler": {"up": ch.up, "down": ch.down, "taps": ch.taps},
        "native_samples_read": int(start),
        "seconds_processed": start / rec.sample_rate_hz,
        "samples_20msps": int(produced),
        "detect_blocks": state["blocks"],
        "bursts": state["bursts"],
        "windows": state["windows"],
        "windows_rejected_inactive": state["rejected"],
        "shards": writer.shards,
        "wall_s": round(time.perf_counter() - t_begin, 3),
        "timing_s": {k: round(v, 3) for k, v in timing.items()},
        "params": asdict(params),
    }


def check_rows(rows: list[dict]) -> None:
    """Raise ValueError unless every row is a valid ManifestRow once a split is added."""
    for row in rows:
        if "split" in row:
            raise ValueError(f"{row.get('window_id')}: rows files carry no split")
        ManifestRow.from_dict({**row, "split": "train"}).validate()
