# Handoff: where the mod-classifier work stopped

**Frozen:** Nov 11, 2026, about 23:55, at Odon's request, to continue under a Paseo orchestrator.
**Repo:** `Gabriel-smm/argus`, local checkout `/Users/odon/Desktop/DIU Project/argus`.
**Integration branch:** `feat/modulation-classifier` (local only, never pushed). Head before this file: `d132fde`.

Read in this order: this file, then [PLAN.md](PLAN.md) (the full design), then [README.md](README.md), then `mcls/contracts.py`.

---

## 1. Rules Odon set (keep them)

- **The laptop builds and tests the pipeline; it never trains.** No PyTorch on the laptop. All training, baselines included, runs on Notre Dame's CRC through shell scripts that Odon will ask for separately. Do not write training job scripts until he asks.
- **No radio captures.** Nothing is recorded with the team's RTL-SDRs or HackRF. Tests are held-out public recordings plus a cross-dataset test (PLAN.md 3.2).
- **Odon has a CRC account.** Quota and GPU access are not yet checked.
- **No large downloads on the laptop.** Keep raw data under about 1 GB. Every download needs Odon's approval, with filename, source and size stated first.
- **Never push, never touch `main`, never open a PR without Odon's say-so.** Commit locally on branches. Repo convention: `feat/<name>` branches, short imperative commit subjects (see the repo's CLAUDE.md).
- **"Demodulation" is the wrong word:** the model classifies signals and never decodes content (SRS NFR-7).
- **Do not claim anything as fact without a source you opened.**
- **The plan's "section 14 decisions" are closed;** defaults stand.

## 2. Done and committed on `feat/modulation-classifier`

| Commit | What |
| --- | --- |
| `8b789d7` | `PLAN.md`: full build plan, `.gitignore` for `mod-classifier/data/` and `runs/` |
| `560beab` | Plan: Zenodo download cap |
| `d132fde` | **Wave 0** (orchestrator): contracts, taxonomy, manifest and splits, checked TOML configs, reference Tampere loader, `mcls.fetch` downloader, CRC `requirements.txt`, README, 42 tests |

Tests on this branch: `cd mod-classifier && ../.venv/bin/python -m pytest tests -q` gives 42 passed. The repo's own `python -m pytest tests` (123) is unaffected.

## 3. Data on the laptop (git-ignored)

`mod-classifier/data/raw/tampere/`: `DJI_mavic_mini_2G.bin` (480 MB, 2.44 GHz, 120 MS/s), `DJI_inspire_2_5G_1of2.bin` (400 MB, 5.8 GHz, 200 MS/s), `load_bin.py` (the dataset's reader, read but never run). All three md5-verified against Zenodo. The Tampere loader matches the dataset's own reader exactly on both files. Drone-only: no background class on the laptop.

## 4. Wave 1: four engineers launched, then frozen

Each worked in its own git worktree under `/Users/odon/Desktop/DIU Project/argus/.claude/worktrees/`. **None of their branches has been reviewed or merged into `feat/modulation-classifier`.**

### Engineer 9: CRC infrastructure: finished, reviewed partly, not merged
- **Branch:** `worktree-agent-abb8fc49999078f4f`, head `b1848ad` (5 commits on `d132fde`). Worktree `agent-abb8fc49999078f4f`.
- **Delivered:** `mod-classifier/crc/` with `common.sh`, `setup_env.sh`, `check_env.sh`, `check_node.sh` and `check_node.job`, `prepare_array.job` (data-prep array job template, no training), `README.md` (run order on CRC), `CI_PROPOSAL.md` (draft for Gabriel, CI not edited); `scripts/run_tests.sh`; `tests/test_crc_scripts.py`.
- **Checked by the orchestrator:** 58 passed, 1 skipped; `bash -n` clean; no personal details in files. **Nothing has run on CRC.**
- **Fix before merging:** `prepare_array.job` allows `-tc 8` tasks at `MCLS_CONNECTIONS=4` each, so up to **32 connections to Zenodo at once**. The plan caps it at about 8 per host. Set the default so tasks x connections is about 8 (for example `MCLS_CONNECTIONS=1` with `-tc 8`).
- **Interfaces it guessed** (reconcile with engineer 2 and the front end): `python -m mcls.acquire --dataset D --only NAME --connections N` writing into `$MCLS_RAW`; `python -m mcls.preprocess --dataset D --raw DIR --out DIR`.
- It reported that its worktree branch had started at `main`, and it reset it to `feat/modulation-classifier` before working.

### Engineer 3: dataset loaders: stopped mid-task
- **Branch:** `feat/mcls-dataset-loaders`, head `75bbd4d`. Worktree `agent-a75d0b155015ca932`.
- **Committed:** `2733fdc` DroneRF loader plus shared helpers (`mcls/sources/_common.py`), `cb90130` NIST Wi-Fi/Bluetooth HDF5 loader.
- **`75bbd4d` is a WIP commit made by the orchestrator at the freeze:** SigMF loader and its test, plus a change to `mcls/sources/base.py`, saved as left. **One test fails:** `tests/test_source_sigmf.py::test_eight_bit_types` (78 passed, 1 failed, 1 skipped).
- **Not started:** GATEMAN (big-endian int16), triangular L1 (gzip int8), Drexel radar (.mat in tar), ADS-B 24 h. Its last note said it was about to write the DroneRF test.
- Not reviewed: verify against the task in section 6 before merging.

### Engineer 1: taxonomy and licences: stopped before committing anything
- **Branch:** `worktree-agent-a406248e6aa4e5a32`, head `d132fde` (no changes). Its research was not saved.
- **Still to do:** with sources, decide each drone's physical link (Wi-Fi, Bluetooth/BLE, proprietary). Fill `configs/taxonomy.toml` for every dataset in PLAN 3.1. Write `LICENCES.md`.

### Engineer 2: data acquisition: stopped before committing anything
- **Branch:** `feat/mcls-data-acquisition`, head `d132fde` (no changes). Research not saved, except one finding from its last message: **Fairdata (FGI Jammer Test 2023) ignores HTTP Range requests and its download tokens are single-use**, so `mcls.fetch`'s parallel ranges will not work there. That dataset needs a single-connection download, or a token flow handled per request.
- **Still to do:** `configs/catalog.toml` (every file: URL, size, checksum, access); sha256 support in `mcls/fetch.py`; `mcls/acquire.py` CLI with `--list`, `--only`, `--connections`, `--max-gb`, dry run; measured speeds per host in `DATA_ACQUISITION.md`. DroneRF's Mendeley file list is still unknown (the public API returned an empty list).

Stale branch names from worktree creation also exist and hold nothing: `worktree-agent-a15334c772d4ff348`, `worktree-agent-a75d0b155015ca932`.

## 5. Next steps, in order

1. **Review and merge Engineer 9** into `feat/modulation-classifier` after the connection-cap fix.
2. **Finish Engineer 3:** fix the 8-bit SigMF test, write the DroneRF test, then the GATEMAN, triangular, Drexel and ADS-B loaders. Review, merge.
3. **Rerun Engineers 1 and 2 from scratch:** their prompts are in section 6. Give engineer 2 the Fairdata finding.
4. **Reconcile interfaces:** `mcls.acquire` flags (engineer 2) against `prepare_array.job` (engineer 9).
5. **Wave 2,** only after Odon approves: the DSP front end (engineer 4: resample to 20 MS/s, burst windows via the repo's `pipeline/features.py`, shards plus manifest, `python -m mcls.preprocess`) and the data pipeline (engineer 5: torch Dataset, samplers, augmentation). Waves 3 and 4 follow PLAN.md section 9.
6. **CRC training scripts:** only when Odon asks.

## 6. The Wave 1 task briefs (as given)

All four had the same rules: work only in your worktree; edit only the files you own; no dataset downloads over 50 MB; no PyTorch; tests must pass with the repo's `.venv` Python; commit small with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; never push; no personal details in files or requests; no unsourced claims.

- **Engineer 1, taxonomy and licences.** Owns `configs/taxonomy.toml`, `mcls/taxonomy.py`, `LICENCES.md`, `tests/test_taxonomy_*.py`. Decide, with opened sources, each drone's physical link:
  - Tampere: DJI Inspire 2, Matrice 100, Matrice 210, Mavic Mini, Mavic Pro, Phantom 4, Phantom 4 Pro Plus, Parrot Disco, Parrot Mambo, Yuneec Typhoon H.
  - DroneRF: Parrot Bebop, Parrot AR Drone, DJI Phantom 3.
  - DroneDetect: Mavic 2 Air S, Mavic Pro, Mavic Pro 2, Inspire 2, Mavic Mini, Phantom 4, Parrot Disco.
  A drone on Wi-Fi gets `wifi`, on BLE `bluetooth`, each with `emitter_id`; proprietary links stay `drone_link`. Fill every dataset's taxonomy entry. Write the licence register, with excluded sets and the reason.
- **Engineer 2, data acquisition.** Owns `configs/catalog.toml`, `mcls/fetch.py`, `mcls/acquire.py`, `DATA_ACQUISITION.md`, `tests/test_acquire_*.py`. Build the catalog from each source's API or page, add sha256, write the acquire CLI, measure 10 MB range speeds per host on 1 and 4 connections.
- **Engineer 3, dataset loaders.** Owns `mcls/sources/` (not `tampere.py`), `conftest.py` (repo root on sys.path only), `tests/test_source_*.py`. Write one loader per dataset, following `tampere.py`, each with byte-format fixtures that fail on wrong endianness or I/Q order. Pass a test-built `Taxonomy` object, since engineer 1 owns the TOML. It may import `pipeline.features.real_to_iq` from the repo root.
- **Engineer 9, CRC infrastructure.** Owns `crc/`, `scripts/`, `tests/test_crc_*.py`. No training scripts.

## 7. Key facts the next orchestrator needs

- **Zenodo caps each connection at about 0.6 MB/s;** 4 parallel ranges gave 2.4 MB/s (measured from the laptop). Keep about 8 connections per host at most.
- **CRC storage:** home `/users/<netid>` 100 GB fixed; `/groups/<PI>` 5 TB only with a faculty sponsor (unknown whether one exists); `/goldfs` and `/bluefs` cannot be mounted for jobs; node `/tmp` size undocumented. Raw data must be streamed and deleted; windows are 32 KB each (about 1 GB per class at 30,000 windows).
- **Datasets, licences and sizes:** `PLAN.md` section 3.1 and the Word doc `../../Argus-Datasets.docx` (in the `DIU Project` folder, outside the repo).
- **Byte-order traps:** Tampere int16 little-endian; GATEMAN int16 big-endian; triangular L1 gzip int8; DroneRF real floats in CSV inside RAR.
- **Open label question:** some Parrot drones may physically be Wi-Fi or Bluetooth (engineer 1's job).
