# Site check data

Laya names each signal. The site check asks a second question: **is this signal normal here?** It compares every signal with the files in this folder and puts it in one of three groups, with a reason and what to check next.

| Group | When |
|---|---|
| **needs a closer look** | On the site's restricted list; any signal on GPS L1; or a drone-like link with no Remote ID heard (or not checked) |
| **unknown** | No band on the list covers it; its width or modulation does not fit the band it is in; a drone that *is* broadcasting Remote ID; or a band that is allowed but not normally seen at this site |
| **expected here** | It fits a band that is on the site's expected list |

The rules are in [pipeline/lookup.py](../../pipeline/lookup.py). They are plain rules, not a trained model, so anyone can read why a signal landed where it did, and changing the site file changes the answer without retraining.

Try it with no GPU, Laya or Ollama:

```bash
python -m pipeline.lookup data/observations-site-demo.jsonl
```

## Files

| File | What | Built from |
|---|---|---|
| `bands.csv` | 32 frequency bands between 88 MHz and 6 GHz: what normally uses each one, its usual width and modulation, whether it hops, whether it is a drone link, and whether it is a protected safety band | NTIA US Frequency Allocation Chart; FCC Part 15; Open Drone ID; drone recordings in the source log. Edited by hand |
| `ism_devices.csv` | 392 consumer device types (weather stations, tire sensors, meters, remotes) that transmit at 315, 433, 868 and 915 MHz | [rtl_433](https://github.com/merbanan/rtl_433) device list (GPL-2.0). Rebuild with `python -m context_sources.rtl433` |
| `remote_id.json` | Where drones broadcast Remote ID, and what each message carries | [Open Drone ID](https://github.com/opendroneid) (`opendroneid.h`), ASTM F3411 |
| `site.json` | The demo site: Notre Dame campus, its expected bands, restricted list and nearby features | Hand-written. Fill `nearby` from OpenStreetMap with `python -m context_sources.osm_site` |
| `site_example_overseas.json` | Illustration of swapping the frequency list for another area. Not real allocations | Hand-written |

## Optional fields in a data file

A signal row may carry two extra fields, which Laya ignores and the site check uses:

- `hopping`: `true` if the signal jumps between channels, `false` if it stays put.
- `remote_id`: `true` if a Remote ID broadcast was heard from it, `false` if one was listened for and not heard. Leave it out if nobody checked.

## Changing the data

- **Another site:** copy `site.json`, change the name, coordinates and `expected_bands`, then start the app with `ARGUS_SITE=data/context/your_site.json`. Run `python -m context_sources.osm_site --site data/context/your_site.json` once, with internet, to fill in nearby airports, towers and power stations. Argus itself never goes online.
- **A band:** edit a row in `bands.csv`. Widths are in kHz, frequencies in MHz, lists are separated by `;`. Run `python -m pytest tests/test_lookup.py` afterwards; it checks the table is consistent.
- **Accuracy:** `data/observations-site-demo.jsonl` has 17 hand-made signals across the three use cases, each with the group it should land in (`expected_triage`). The demo command above prints the agreement. These rows were written together with the rules, so they show the rules work as intended; they are not evidence of accuracy on real recordings.

## Tried on real recordings

The burst features on `main` (`pipeline/features.py`) give real measurements to test against:

| Data | Signals | Site check result | What it means |
|---|---|---|---|
| DroneRF (`data/train/dronerf.jsonl`), real Parrot and DJI drone bursts at 2.4 GHz | 695 | 692 expected here (as Wi-Fi or Bluetooth), 3 unknown | **The site check cannot tell a drone from Wi-Fi by frequency and width alone.** These rows carry no Remote ID field, and a drone video link looks like Wi-Fi. Catching these is the classifier's job, trained on the burst features; the site check adds Remote ID and the site context on top |
| NIST 3.5 GHz radar (`data/train/nist_radar.jsonl`), simulated radar pulses | 91 | 80 unknown, 11 expected here | A signal on less than 1% of the time with a steady pulse interval is read as pulsed radar, which is not expected on campus. The 11 are radar bursts long enough to pass as a CBRS network |

## Known limits

- Drone link widths and the 900 MHz and 5.8 GHz drone rows are typical values from public specs, marked "to verify" in `source`. Check them against real recordings.
- Barrage jamming across a whole band lands in **unknown**, not **needs a closer look**: the table can say it fits nothing, not that it is jamming.
- OpenSky and GPSJam are named as places to check GPS interference, not loaded: OpenSky's free live feed does not carry the navigation-accuracy fields, which need research access.
- Overture Maps overlaps OpenStreetMap for this purpose, so only OpenStreetMap is used.
