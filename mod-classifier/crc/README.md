# mod-classifier on CRC

Shell scripts to set up and check Notre Dame's CRC before any bulk data preparation. **None of these scripts has been run on CRC yet.** They were written without CRC access, checked with `bash -n`, and tried on a laptop only where that makes sense (the missing-command paths, the Zenodo speed test, and the array job with stand-in modules). Expect small fixes after the first real run.

There are no training jobs here yet; they are written later, on request.

| File | What it does |
| --- | --- |
| `common.sh` | Helpers the other scripts source: find and load a `python/3.12` module, activate the venv |
| `setup_env.sh` | Front end: load Python 3.12, create the venv, install `../requirements.txt`, print torch and CUDA status |
| `check_env.sh` | Front end, read-only: quota, groups, free space, modules, free GPUs, Zenodo download speed |
| `check_node.sh`, `check_node.job` | Compute node, read-only: `/tmp` size, CPUs, RAM, `nvidia-smi`, torch sees CUDA |
| `prepare_array.job` | Template array job: one raw file per task, fetch to node `/tmp`, preprocess, keep outputs, delete raw |
| `CI_PROPOSAL.md` | Draft: how the repo CI could also run `mod-classifier/tests` (needs Gabriel's agreement) |

## Settings

All scripts read these environment variables (all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `MCLS_VENV` | `$HOME/venvs/mcls` | Where the venv lives. Put it on `/groups/<PI netid>` if that exists and home is tight |
| `MCLS_PYTHON_MODULE` | newest `python/3.12*` | Module to load. `setup_env.sh` saves its choice in the venv, so jobs reuse it |
| `MCLS_TORCH_INDEX_URL` | none | Extra pip index for a specific torch CUDA build, e.g. `https://download.pytorch.org/whl/cu121` |

## Order to run

Log in to a front end (`ssh <netid>@crcfe01.crc.nd.edu`), clone the repo on the `feat/modulation-classifier` branch, then:

```bash
cd argus/mod-classifier
mkdir -p runs/crc_logs                                  # job logs land here (git-ignored)

# 1. What the account offers (about a minute, mostly the speed test)
bash crc/check_env.sh 2>&1 | tee runs/check_env.txt

# 2. Build the venv (several minutes; torch with CUDA is a few GB)
bash crc/setup_env.sh 2>&1 | tee runs/setup_env.txt

# 3. One GPU node and one CPU node (each a minute or less once it starts)
qsub -q gpu -l gpu_card=1 crc/check_node.job
qsub -q long crc/check_node.job
qstat -u $USER                                          # wait until both are gone
cat runs/crc_logs/check_node.o*
```

Run step 1 before step 2: if home is nearly full, set `MCLS_VENV` to a path on group storage first.

Step 4, `prepare_array.job`, waits until `mcls.acquire` (Engineer 2) and `mcls.preprocess` (front end, not written yet) exist and Odon approves the download. Until then it stops at once with exit code 3 and the message "python module mcls.acquire (or mcls.preprocess) does not exist yet", before it downloads anything.

## What each prints and how to read it

**`check_env.sh`**: one `===== heading =====` per check. A missing command prints `(command not found: ...)` and the script carries on.

- *quota*: used and limit for home (100 GB, fixed). If a `/groups/<name>` directory exists for one of your groups, it is listed with its quota and `df`. "none of your groups has a /groups/<name> directory" means no faculty-sponsored group storage, so everything (venv, prepared windows) must fit in 100 GB.
- *free space of $HOME*: the filesystem's free space; the quota above is the real limit.
- *module avail python / cuda / pytorch*: what the cluster provides. The last line says which `python/3.12` module `setup_env.sh` will pick; "none found" means setup will fail until a module is named with `MCLS_PYTHON_MODULE`.
- *free_gpus.sh @crc_gpu*: free GPU cards per node right now.
- *Zenodo speed test*: `RESULT 1 connection` and `RESULT 4 connections` in MB/s. From the laptop, one connection gave about 0.6 MB/s. If four connections give about four times one, the cap is per connection, as at home, and jobs should use 4 to 8 connections. Each part should say `http 206`. Any other code means the range request was refused.

**`setup_env.sh`**: ends with `torch <version> built for CUDA <version>` and `cuda available: False` on a front end (no GPU there; that is expected). Rerunning prints "exists, reusing" and "requirements.txt unchanged ..., skipping pip". `venv size` shows how much of the quota the venv uses.

**`check_node.job`** (log `runs/crc_logs/check_node.o<job id>`):

- *df -h /tmp*: node-local scratch. Its free space caps the largest raw file a task can fetch (NIST files are about 20 GB, some archives about 50 GB).
- *CPUs*: `nproc` is what the job may use, `nproc --all` the whole node.
- *RAM*: `free -g`.
- *nvidia-smi*: the GPU model, memory, and driver/CUDA version (GPU node only; "command not found" on a CPU node is normal).
- *torch inside the venv*: on the GPU node, `cuda available: True`, the device name and `matmul on GPU ok: True` mean training can run. `False` on the GPU node means the torch build and the driver do not match: rerun `setup_env.sh` with `MCLS_TORCH_INDEX_URL` set to the CUDA version `nvidia-smi` reports (`MCLS_FORCE_INSTALL=1`).

## `prepare_array.job` (template)

One task per raw file. Task N reads line N of a file list (blank lines and `#` comments skipped). For a Zenodo dataset the names come from `python -m mcls.fetch --zenodo <record> --list`. Each task then:

1. `python -m mcls.acquire --dataset D --only NAME --connections N` with `MCLS_RAW=/tmp/$USER/mcls_raw/<job>.<task>`
2. `python -m mcls.preprocess --dataset D --raw $MCLS_RAW --out <node scratch>` (placeholder interface, to align with the front end when it exists)
3. copies only the outputs to `$MCLS_OUT/<file name>/` and writes a `DONE` marker there
4. deletes the raw file and the scratch, also when the task fails

```bash
N=$(grep -cv -e '^#' -e '^[[:space:]]*$' files_tampere.txt)
qsub -t 1-$N -v MCLS_DATASET=tampere,MCLS_FILE_LIST=$PWD/files_tampere.txt crc/prepare_array.job
```

`MCLS_OUT` defaults to `$HOME/mcls_data/prepared/<dataset>`; `MCLS_CONNECTIONS` defaults to 1. `#$ -tc 8` lets at most 8 tasks run (and download from Zenodo) at once, so about 8 connections in total, the cap in PLAN.md. Keep tasks x connections near 8: if you raise `MCLS_CONNECTIONS`, lower `-tc` (for example `MCLS_CONNECTIONS=4` with `qsub -tc 2`). A rerun skips files whose output has a `DONE` marker. Set `MCLS_KEEP_FAILED=1` to keep a failed task's files in `/tmp` for debugging.

## What to send back to the orchestrator

Paste these in full. They hold no secrets, but replace your NetID with `<netid>` wherever it appears:

1. `runs/check_env.txt`: especially the quota lines, the `/groups` section, the module lists, and both `RESULT` speed lines.
2. The last 15 lines of `runs/setup_env.txt` (torch version, CUDA build, venv size), or the full error if it failed.
3. Both `runs/crc_logs/check_node.o*` logs, with the queue each came from (gpu or long), and how long each waited in `qstat` before starting.
4. Anything that did not work as this README says.
