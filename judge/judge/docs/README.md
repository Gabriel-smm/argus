# judge: is this signal normal here?

The classifier names a signal. The Judge decides what that means **at this site**: blue (expected here), white (unknown) or red (not expected here), with a one-line reason and a next step. It also checks the noise floor for possible jamming and puts each signal on a map when a GPS log exists.

This folder is self-contained. It needs Python 3.12 and nothing else, and it changes no other file in the repo. The architecture is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```
python -m pipeline.ingest capture.cs8 --sample-rate 20M --center-freq 2.437G \
    --classify --model mod-classifier/runs/crc/cnn2d_v1_w5 -o signals.jsonl

cd judge
python -m argus_judge ../signals.jsonl --site configs/site_campus.toml -o report.json --text
```

With a GPS log, add `--track walk.gpx --capture-start 2026-11-14T15:00:00Z` (and `--geojson verdicts.geojson` for a map). With no log, `--lat 41.705 --lon -86.235` gives every signal one fixed position. Sweep CSVs write local time with no zone, so also pass `--utc-offset-hours -5` (US Eastern standard time) when matching them to a GPX log.

## What is in here

| Path | What |
|---|---|
| `argus_judge/` | The code: `rules.py`, `profile.py`, `jamming.py`, `locate.py`, `report.py`, `__main__.py` |
| `configs/` | Site profiles: `site_campus.toml`, `site_power_plant.toml` (examples) |
| `schema/` | JSON Schemas for the input rows and the report |
| `docs/` | `ARCHITECTURE.md` and `judge-architecture.drawio` (open in draw.io) |
| `fixtures/` | A sample classified capture, a sample sweep with a noise rise, a sample GPS walk |
| `tests/` | 50 tests |

## What goes in and out

**In:** ingest rows (`pipeline/ingest.py`). Needed: `center_frequency_hz`, `bandwidth_hz`. Used when present: `signal_class`, `class_confidence`, `hopping`, `noise_floor_db`, `first_seen`, `start_s`. A row with no `signal_class` (an unclassified sweep) is judged white, never guessed.

**Out:** a report with counts, one verdict per signal, noise-floor checks and notes. `--text` prints the summary a chat model can be given: counts and reasons, never raw rows.

## The rules (`argus_judge/rules.py`, first match wins)

| # | If | Then |
|---|---|---|
| 1 | class is `background` | no verdict (counted as skipped) |
| 2 | no class | white, `not-classified` |
| 3 | class is `unknown` | white. The classifier already applied its calibrated threshold |
| 4 | class is in the site's `red_classes` and not under `[[expected]]` | **red** |
| 5 | class is `wifi` but the burst hops | white, `wifi-hopping` (Wi-Fi does not hop; could be a drone) |
| 6 | expected, but confidence is under the site's own bar | white |
| 7 | matches an `[[expected]]` entry (class, frequency range, bandwidth limit) | **blue** |
| 8 | anything else | white, `not-in-profile` |

An unlisted or unknown signal can never be blue (tested for every class). The blue/white line is the classifier's own calibrated `unknown` threshold, not a number invented here. `min_confidence_for_blue` in a profile adds an optional stricter bar and defaults to 0.

## Site profiles

A TOML file says what is normal: which classes are expected in which bands, which are red, how far the noise floor may rise, and the quiet baseline per band. Change the policy by editing the file.

**Both shipped profiles are examples.** Their values are not measured and have not been reviewed by the policy owner. Each says `status = "DRAFT..."` and the report repeats that.

## Location

A location is **where the sensor was**, not where the signal came from; one sensor cannot find an emitter. Each signal gets a position from a GPS log (GPX, or CSV with `time,lat,lon`) matched by time to the nearest fix, or from one manual position. A signal with no fix within `--max-gap-s` (default 30 s) gets none, never a guess. `--geojson` writes located signals as points a map can draw.

The app has no GPS input today, so someone must record a log during a walk (a phone app that exports GPX is enough) and note when the capture began.

## Jamming

Per baseline band, the median `noise_floor_db` of the signals found there is compared with the site's baseline. A rise of `noise_rise_db` or more is flagged, and the report says whether the classifier also saw a `gnss_jammer`. Sweep noise floors are in the radio's own dB, so the baseline must come from the same radio and gain.

## Known gaps

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#known-gaps). The main one: a sweep gives a noise floor but no class, and an IQ recording gives a class but no absolute noise floor, so one capture does not yet give both.

## Tests

```
cd judge && python -m pytest tests -q
```

`tests/test_schema.py` needs `jsonschema` and is skipped without it. CI runs `python -m pytest tests` at the repo root and does not see this folder; to include it, add `judge/tests` to that command in `.github/workflows/ci.yml`.
