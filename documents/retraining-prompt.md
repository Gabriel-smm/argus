# Prompt: train the signal classifier on the RadioHound recordings

Paste everything below the line into a new Claude Code session at the repository root.

---

I need a signal classifier, trained mainly on our new over-the-air RadioHound recordings, that we
can run live on a HackRF at a demo for non-technical DIU staff on **Dec 5**. Today's date is
in your environment; Thanksgiving is Nov 26–27 and the live-demo work (`documents/live-demo-plan.md`)
starts Nov 28, so I want a trained, evaluated model by **Nov 27**. Read
`documents/live-demo-plan.md` and `collect/README.md` first.

## What "good enough" means

The audience is non-technical. The model does not need to be perfect: it must give the right
answer most of the time on clear signals, report a confidence, and say **"unknown"** rather than
make a confident wrong guess. A calibrated, honest model beats a higher test accuracy that falls
apart on a real room.

## The data

Get it with `python -m collect.dataset fetch` (228 MB; unpacks into `data/`). Read recordings with
`collect.dataset.read_recording(base)`, which returns complex64 and **already skips the first
262,144 samples**. Never use those samples: block 1 is stale (left over from before the
request) and block 2 holds a tuning transient. What remains is 262,144 samples ≈ 13 ms at 20 MS/s.

| Folder | Content |
|---|---|
| `data/radiohound/` | 126 rows × (1 RF-off + 4 RF-on). CW, BPSK, QPSK, 8PSK, 16QAM, 64QAM at 0.5/2/5 MHz; FM at 25/75 kHz deviation; continuous OFDM at 2/5/10 MHz. Powers −40/−30/−20 dBm (≈ 5, 16, 26 dB SNR), offsets ±3 MHz |
| `data/radiohound-room/` | 72 rows × (1 off + 2 on). GFSK with and without 5 MHz hopping (Bluetooth-like), OOK at 2 and 10 kbit/s (key-fob-like), OFDM bursts at 2 and 10 MHz (Wi-Fi-like) |
| `data/radiohound-ambient/` | 96 recordings with the generator off in 8 everyday bands. Nearly empty in the clean part; useful only as noise |

Labels are exact (what the generator sent): `argus:mode`, `argus:bandwidth_hz`, `argus:power_dbm`,
`argus:frequency_offset_hz`, `argus:seed`, `argus:rf` in each `.sigmf-meta` annotation, and the same
in each folder's `manifest.csv`. One generator (Keysight N5172B) sent everything over the air to
one HackRF on top of it, at a 2927 MHz carrier.

Known quirks, all to be handled in the loader:
- `manifest.csv`'s `snr_db` was measured over the whole recording, stale blocks included.
  **Recompute SNR on the clean part** against the row's RF-off recording, and drop RF-on recordings
  under about 3 dB. One BPSK `on_00` at −20 dBm has no signal at all.
- **OOK is bursty at a slow rate:** some clean 13 ms windows hold little or no packet. Filter by
  energy found in the clean window, not by the manifest.
- 14 OOK recordings at −20 dBm and 1 GFSK recording clipped (8-bit full scale). Drop or flag them.
- The HackRF has a DC spike at the center bin; the generator clock is ≈ 27 kHz off at 2.9 GHz.
- **The center frequency is always 2927 MHz and offsets are always ±3 MHz.** Neither may become
  a feature, or the model will learn the lab setup instead of the signal.
- Recordings of the same row are near-duplicates. **Split train/test by row (`seed`), never by
  recording.** Also report results on a held-out power level (train −30/−20, test −40) to see how
  the model holds up at low SNR.

## What to build

1. **Loader:** `finetune/sources/radiohound.py`, following the other loaders in that folder. It
   returns labelled clean windows (or bursts) with the row id, mode, power and SNR.
2. **Class mapping** to what the demo shows. Proposed, open to your judgment:
   `FM → fm_broadcast`, `GFSK → bluetooth`, `OOK → keyfob_ook`, `OFDM_BURST → wifi`,
   continuous `OFDM → cellular`, `BPSK/QPSK/8PSK → psk`, `16QAM/64QAM → qam`, `CW → carrier`,
   RF-off and ambient → `noise`. Keep the finer modulation label too: a modulation detector that
   fills the observation's `modulation` field (today always `"unknown"`) is a useful by-product.
3. **Features and model.** The same code must run on the live HackRF stream, so features go in
   `pipeline/` and training calls them, as `pipeline/features.py` (`detect_bursts`, on branch
   `feat/burst-features`) already does. Start with a gradient-boosted model (LightGBM, as the
   existing burst dataset plans) on features that do not depend on absolute power: occupied
   bandwidth relative to the 20 MHz span, spectral flatness and shape, envelope statistics (duty
   cycle, burst length, amplitude variance), instantaneous-frequency statistics, and higher-order
   cumulants (C40, C42) on the normalised signal. Only try a small CNN on spectrograms or IQ if the
   features plateau, and compare both on the same split.
4. **Close the gap to a real room.** Everything was recorded by one generator, one HackRF, and one
   signal at a time. Augment: random frequency shifts of tens of kHz, added noise down to about
   0 dB SNR, random gain scaling, IQ imbalance and DC offset, many short windows (1–5 ms) per
   recording, and mixing a signal over ambient noise recordings. Measure each augmentation on
   the held-out split instead of assuming it helps.
5. **Confidence and "unknown".** Calibrate probabilities (temperature or isotonic on a calibration
   split) and choose a threshold below which the answer is `unknown`. Report coverage (share of
   windows answered) against accuracy at that threshold.
6. **Evaluation report** in the finetune README style: per-class accuracy, confusion matrix,
   results by power level, calibration, and an honest paragraph on what the numbers do **not**
   show (generator data, one receiver, no real room yet).
7. Save the model under `models/` (not committed) with a small loader the live pipeline can call.

## Constraints

- Plan before code: propose the approach, the class list and the split, and wait for my OK.
- You need two branches that may not be in `main` yet: `feat/radiohound-collect` (`collect/`,
  the fetch command and the reader) and `feat/burst-features` (`detect_bursts` and the burst
  dataset conventions: `label_service`, `source`, `file`, `simulated`). Check `main` first; start
  a `feat/` branch from `main` and merge in whichever is missing.
- Small commits with imperative subjects. CI runs `pytest` and `npx oxlint`; add tests for the
  loader and the features (no network, no hardware in tests).
- **Never `git push` or open a PR without asking me first**, every time. I work on the fork
  `Gabriel-smm/argus`; the original is `jlimaz/argus`. Ask which one a PR should target.
- Do not use absolute power or the noise floor as a feature.
