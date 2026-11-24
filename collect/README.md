# Over-the-air collection (RadioHound)

Records labeled training data in RadioHound's lab. A Keysight N5172B signal
generator transmits a known signal, and a HackRF sitting next to it records it.
Both are reached over the network, so this needs Notre Dame's network (eduroam).

- `siggen/`: generator control, copied from RadioHound's SIGGEN_Standalone package (Christopher Wahl).
- `radiohound.py`: asks RadioHound's server for a recording. Each one is 524,288 I/Q samples at 20 MS/s (about 26 ms) and takes about 20 s.
- `sweep.py`: steps through a plan and saves the recordings.
- `plans/saturday.json`: the first sweep (126 rows, about 3.5 hours): BPSK, QPSK, 8PSK, 16QAM, 64QAM, FM, OFDM, CW.
- `room_waveforms.py` + `plans/room.json`: imitations of everyday signals the generator package doesn't make:
  Bluetooth-like GFSK (with or without hopping), key-fob-like OOK, and Wi-Fi-like OFDM packets
  (72 rows, about 1.5 hours).
- `plans/ambient.json`: receive only. Records what is already on the air in 8 bands (433 MHz to 5.18 GHz)
  at two gains, with the generator off (about 35 minutes). Labels are only the band's expected users,
  so use these for testing and demo tuning, not as exact training labels. 98 MHz (FM radio) times out
  on the server.

## Rules agreed with RadioHound

- Generator power stays at or below **−10 dBm**. The script refuses anything higher.
- One request at a time, at least 2 s apart. Don't overload the shared server.
- RF is switched off after every row and on every exit, including Ctrl-C.
  If the script dies hard, check the generator: `python collect/siggen/read_n5172b.py --basic`.

## Use

```bash
# 1. Try everything without hardware (simulated generator and server)
.venv/bin/python -m collect.sweep --dry-run run --plan collect/plans/saturday.json

# 2. Find a power level: raises the power until the signal clips or reaches -10 dBm
.venv/bin/python -m collect.sweep probe --powers=-70,-60,-50,-40,-30,-20

# Receive-only recording of the bands (generator stays off)
.venv/bin/python -m collect.sweep ambient --plan collect/plans/ambient.json

# 3. Put the working power levels in the plan's powers_dbm and run it
.venv/bin/python -m collect.sweep run --plan collect/plans/saturday.json
```

Rerunning the same command resumes: finished rows (those with `done.json`) are skipped.
To run in shorter sessions, add `--max-rows N` (stop after N rows; a row
takes about 1.75 min, so 30 rows ≈ 50 min) and/or `--only TEXT` (only rows whose name contains TEXT):

```bash
.venv/bin/python -m collect.sweep run --plan collect/plans/saturday.json --only OFDM
.venv/bin/python -m collect.sweep run --plan collect/plans/saturday.json --max-rows 30
```

## Output (`data/radiohound/`, not committed)

One folder per plan row, containing:
- `off_00`: a recording with RF off, made just before the signal. It shows what was already on the air.
- `on_00` … `on_NN`: recordings with the signal on.

Each recording is a SigMF pair. `.sigmf-data` holds complex float32 samples.
`.sigmf-meta` holds the labels, which are exactly what the generator sent, plus
the server's fields.

`manifest.csv` has one line per recording, with these quality fields:
- `snr_db`: signal power above the RF-off recording.
- `peak`: the largest sample value.
- `clipped`: the HackRF's 8-bit receiver hit full scale. Lower the power or gain.

Notes:
- **Skip the first 262,144 samples of every recording.** The server returns 4 blocks of 131,072
  samples. Block 1 is left over from before the request: in the first RF-on recording of a row it
  still holds the RF-off noise. Block 2 holds a tuning transient whenever the frequency changed
  since the last request (every ambient recording). Blocks 3–4 (about 13 ms) are clean.
- The recordings have no physical unit. Compare only recordings made at the same `gain`.
- The HackRF puts a spike at the center of every recording, so signals are offset by ±3 MHz to avoid it.
