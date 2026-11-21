# Live demo plan (DIU, Dec 5)

## Goal

Show non-technical DIU staff that Argus can classify **real radio signals, live**.
We plug a HackRF into the laptop and press **Listen**. Argus records the room,
lists the signals it found ("FM radio", "Wi-Fi", ...), and the chat explains them
in plain words.

Perfect accuracy isn't the bar. Reasonable answers are fine, even with modest
confidence. When Argus isn't sure, it should say "unknown" rather than make a
confident wrong guess.

## How it works

```
HackRF ──► record ~0.1 s per frequency ──► detect_bursts ──► observation rows ──► /classify (Laya) ──► chat
```

Only the first step is new. `detect_bursts` (`pipeline/features.py`) already
turns raw I/Q into the observation rows that Laya classifies.

## Before this work starts

1. **Collect the RadioHound data:** `collect/`, about 4 sessions of about 50 minutes.
2. **Merge `feat/burst-features` into `main`.** The live input needs `detect_bursts`,
   and the merge also fixes the 3 tests failing on `main`.
3. **Train the new classifier** on the burst dataset plus the RadioHound recordings.

## Work

| # | Task | Done when |
|---|---|---|
| 1 | **Everyday classes.** Add FM broadcast, Wi-Fi, Bluetooth and cellular/LTE to the knowledge file and training data, so signals in a room have a right answer. Without them, Wi-Fi at 2.4 GHz is labeled "drone link". | Recordings of each class are classified correctly |
| 2 | **`pipeline/live.py`.** Record from a local HackRF (`hackrf_transfer`), at about 20 MS/s for about 0.1 s per frequency, and return observation rows. Options: RadioHound server as a backup source, and replay of saved files. | `python -m pipeline.live` prints rows from a real HackRF |
| 3 | **Frequencies to listen on.** FM 88–108 MHz (always present, strong), 433 / 915 MHz (key fobs, sensors), 2.44 GHz (Wi-Fi, Bluetooth), and one cellular band. Keep the list short: each one costs recording time. | Every band returns something in the lab |
| 4 | **`/live` endpoint.** Records, classifies, and stores the result like `/classify`, so the chat works unchanged. | Works from `curl` |
| 5 | **"Listen" button** in the frontend. Shows each signal with its frequency, its class, and its confidence. Low confidence shows as "unknown". | One click to a result on screen |
| 6 | **Replay backup.** Save a good recording of the venue in advance, so the demo can run from it if the hardware, room or laptop fails. | Demo runs with the HackRF unplugged |
| 7 | **Rehearse in the presentation room**, or a similar one. Check which bands have signals, and set the confidence threshold. | Two full run-throughs without surprises |

The sweep data from RadioHound can also train a small **modulation detector** to fill
the `modulation` field, which today is always "unknown". This is useful, but optional
for the demo.

## Timeline

| Dates | What |
|---|---|
| Nov 21–22 | RadioHound collection |
| Nov 23–25 | Merge `feat/burst-features`, add everyday classes (1), train |
| Nov 26–27 | Thanksgiving, slack |
| Nov 28–Dec 1 | Live input, endpoint and button (2–5) |
| Dec 2–3 | Replay backup (6), rehearsal (7) |
| Dec 4 | Freeze: no code changes, only rehearsal |
| **Dec 5** | **Presentation** |

## Setup on the demo laptop

- `sudo apt install hackrf`, plug in the HackRF, and check that `hackrf_info` finds it.
- Use the HackRF's antenna. **Receive only.** The demo never transmits.
- Bring a USB cable and the backup recording. Have the app running before going on stage.
  Laya and the chat model share the GPU, so the first run takes longer.

## Risks

| Risk | What we do |
|---|---|
| A signal type Argus has never seen gets a confident wrong label | Confidence threshold and "unknown"; add the everyday classes |
| A quiet room, or no Wi-Fi traffic at the moment | FM radio is always on; we can also make traffic with a phone (stream a video) |
| HackRF or USB failure on stage | Replay backup (6) |
| The 8-bit HackRF overloads near strong transmitters | Fixed, moderate gain chosen during rehearsal |
| Laya is slow on the first run | Warm it up before the talk |
