"""The data pipeline on real front-end output (Engineer 4's process_recording), synthetic signal."""

import numpy as np

from mcls import manifest
from mcls.contracts import Recording
from mcls.dataset import Augmenter, WindowStore, audit_window_hashes, build
from mcls.dataset import build_manifest
from mcls.frontend.process import FrontendParams, process_recording
from mcls.frontend.views import stft_view

CLASSES = ("drone_link", "wifi", "bluetooth", "background")


def recording(recording_id, label, seed):
    rate, total = 40e6, 1_200_000
    rng = np.random.default_rng(seed)
    x = (rng.standard_normal(total) + 1j * rng.standard_normal(total)) * 0.01
    burst = rng.standard_normal(300_000) + 1j * rng.standard_normal(300_000)
    x[200_000:500_000] += np.convolve(burst, np.ones(8) / np.sqrt(8), mode="same")
    x = x.astype(np.complex64)
    return Recording(
        dataset="fake", recording_id=recording_id, source_file=f"{recording_id}.bin", sample_rate_hz=rate,
        center_frequency_hz=2.44e9, num_samples=total, label=label, label_strength="strong", is_real=True,
        license="CC BY 4.0", read=lambda s, c: x[s:s + c].copy(), emitter_id=f"model_{seed % 2}",
    )


def test_front_end_rows_build_into_a_manifest(tmp_path):
    shards = tmp_path / "shards"
    for i in range(6):
        rec = recording(f"rec{i}", ("drone_link", "wifi")[i % 2], seed=i)
        process_recording(rec, shards, None, FrontendParams(max_windows_per_burst=4))
    rows = build([shards], seed=2, cap=0)
    assert len(rows) == 6 * 4
    manifest.check_leakage(rows)
    store = WindowStore()
    assert audit_window_hashes(rows, store) == []
    windows, labels = store.get(rows, CLASSES)
    assert windows.shape == (24, 4096) and set(labels.tolist()) == {0, 1}
    train = next(r for r in rows if r.split == "train")
    out = Augmenter()(store.window(train), np.random.default_rng(0), train)
    assert stft_view(out[None]).shape == (1, 1, 64, 64)

    target = tmp_path / "data" / "manifest.jsonl"
    argv = ["--shards", str(shards), "--out", str(target), "--seed", "2", "--classes", "v1"]
    assert build_manifest.main(argv) == 0
    first = target.read_bytes()
    assert build_manifest.main(argv) == 0
    assert target.read_bytes() == first
    reread = manifest.read(target, CLASSES)
    assert np.array_equal(WindowStore(target.parent).windows(reread), store.windows(sorted(rows, key=lambda r: r.window_id)))
