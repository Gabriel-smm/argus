# mod-classifier

The training pipeline for Argus's signal classifier: raw IQ windows in, class probabilities out. **This folder builds the pipeline; it does not train on the laptop.** Training runs on Notre Dame's CRC through shell scripts (to be added under `crc/`). The full design is in [PLAN.md](PLAN.md).

## What exists (wave 0)

| Path | What |
| --- | --- |
| `mcls/contracts.py` | The shared formats: `Recording` (what a loader yields), `ManifestRow` (one training window), `Classifier` (what a trained model offers Argus), the canonical 20 MS/s, 4096-sample complex64 window, and `band_of()` |
| `mcls/taxonomy.py`, `configs/taxonomy.toml` | The class set (v1: `drone_link`, `wifi`, `bluetooth`, `background`) and the label, strength and licence of every dataset's files |
| `mcls/manifest.py` | The JSONL manifest, splits by recording (never by window), `cross_test` hold-outs, and the leakage check |
| `mcls/config.py`, `configs/*.toml` | Run configs, checked key by key so a typo fails on the laptop, not in the CRC queue |
| `mcls/sources/` | Dataset loaders. `tampere.py` is the reference loader; the others follow its shape |
| `mcls/fetch.py` | Parallel, resumable, md5-verified downloads (see "Zenodo" below) |
| `requirements.txt` | What CRC needs. The laptop needs only numpy and pytest |
| `tests/` | pytest. Runs on the laptop with no torch |

## The contract in one paragraph

Every dataset has its own format. Each loader in `mcls/sources/` turns its files into `Recording`s that read complex64 samples on demand at the native rate. The front end (next wave) resamples to 20 MS/s, finds bursts, cuts 4096-sample windows, normalizes them, and writes shards plus one `ManifestRow` per window. Training and evaluation read only shards and the manifest. A trained model implements `Classifier.classify(windows) -> probabilities`.

## Run the tests (laptop)

```bash
cd mod-classifier && ../.venv/bin/python -m pytest tests -q
```

The real-file test runs only when the Tampere sample is in `data/raw/tampere/` (git-ignored).

## Zenodo downloads

Zenodo caps each connection at about 0.6 MB/s; parallel byte ranges add up (4 connections gave 2.4 MB/s). `mcls.fetch` uses up to 8 ranges per file, resumes after drops, and refuses a file whose md5 does not match.

```bash
python -m mcls.fetch --zenodo 4264467 --list
python -m mcls.fetch --zenodo 4264467 --only DJI_phantom_4_2G.bin --out data/raw/tampere --connections 4
```

On CRC, measure the speed once before any large download, keep to 4 to 8 connections per file, and let array jobs fetch different files at the same time. Raw files are streamed through a node's `/tmp` and deleted once their windows are cut (PLAN.md section 3.7).

## Data on the laptop

`data/` and `runs/` are git-ignored. Keep raw data here small (under about 1 GB): it exists to test loaders, not to train.
