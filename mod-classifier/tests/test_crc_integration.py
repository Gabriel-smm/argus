"""The CRC prepare chain: file list -> array job -> merge, checked without CRC or network.

The array job runs here against stand-in mcls.acquire / mcls.preprocess modules in a
temporary copy, so nothing is downloaded. When the real modules exist, their --help is
checked for every flag the job passes.
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JOB = ROOT / "crc" / "prepare_array.job"
BASH = shutil.which("bash")
sys.path.insert(0, str(ROOT / "scripts"))
import make_file_list  # noqa: E402
import merge_shards  # noqa: E402

sys.path.pop(0)

needs_bash = pytest.mark.skipif(BASH is None, reason="bash not installed")

CATALOG = """
[datasets.demo]
access = "direct"
files_status = "complete"
[[datasets.demo.files]]
name = "a.bin"
url = "https://example.invalid/a.bin"
size = 10
checksum = "md5:00"
[[datasets.demo.files]]
name = "Group1/x.mat"
url = "https://example.invalid/g1x"
size = 10
checksum = "md5:00"
[[datasets.demo.files]]
name = "Group2/x.mat"
url = "https://example.invalid/g2x"
size = 10
checksum = "md5:00"
[[datasets.demo.files]]
name = "load_bin.py"
url = "https://example.invalid/l"
size = 1
checksum = "md5:00"

[datasets.roles]
access = "direct"
files_status = "complete"
[[datasets.roles.files]]
name = "notes.txt"
role = "data"
url = "https://example.invalid/n"
size = 1
checksum = "md5:00"
[[datasets.roles.files]]
name = "raw.bin"
role = "doc"
url = "https://example.invalid/r"
size = 1
checksum = "md5:00"

[datasets.login]
access = "ieee_login"
files_status = "complete"
[[datasets.login.files]]
name = "b.bin"
url = "https://example.invalid/b"
size = 1
checksum = "md5:00"

[datasets.partial]
access = "direct"
files_status = "unknown"
files_note = "list not published"
[[datasets.partial.files]]
name = "c.bin"
url = "https://example.invalid/c"
size = 1
checksum = "md5:00"
"""


def _job_text():
    return JOB.read_text()


def _directive(name):
    match = re.search(rf"^#\$ -{name} (\S+)$", _job_text(), re.M)
    assert match, f"#$ -{name} missing"
    return match.group(1)


# ---- connection cap --------------------------------------------------------


def test_default_tasks_times_connections_at_most_8():
    tasks = int(_directive("tc"))
    connections = int(re.search(r'CONNECTIONS="\$\{MCLS_CONNECTIONS:-(\d+)\}"', _job_text()).group(1))
    assert tasks * connections <= 8


def test_job_refuses_more_than_8_connections():
    assert '[ "$CONNECTIONS" -le 8 ]' in _job_text()


# ---- the calls match the upstream CLIs -------------------------------------


def _calls(module):
    """Flags the job passes to `python -m <module>`."""
    text = _job_text()
    lines = [line for line in text.splitlines() if f"-m {module} " in line and not line.lstrip().startswith("#")]
    assert lines, f"job never calls {module}"
    flags = set()
    for line in lines:
        flags |= set(re.findall(r"(--[a-z][a-z-]*)", line))
    if module == "mcls.acquire":
        flags |= set(re.findall(r"ACQUIRE\+=\((--[a-z-]+)", text))
    return flags


def test_acquire_and_preprocess_flags():
    assert _calls("mcls.acquire") == {"--dataset", "--only", "--connections", "--max-gb"}
    assert _calls("mcls.preprocess") == {"--dataset", "--raw", "--out"}


def test_job_checks_both_modules_before_downloading():
    text = _job_text()
    assert "for mod in mcls.acquire mcls.preprocess; do" in text
    assert text.index("find_spec") < text.index('"${ACQUIRE[@]}"')


@pytest.mark.parametrize("module", ["mcls.acquire", "mcls.preprocess"])
def test_real_cli_accepts_the_flags(module):
    sys.path.insert(0, str(ROOT))
    try:
        found = importlib.util.find_spec(module) is not None
    finally:
        sys.path.pop(0)
    if not found:
        pytest.skip(f"{module} not merged yet")
    result = subprocess.run([sys.executable, "-m", module, "--help"], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    for flag in _calls(module):
        assert flag in result.stdout, f"{module} --help does not list {flag}"


# ---- make_file_list --------------------------------------------------------


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "catalog.toml"
    path.write_text(CATALOG)
    return path


def test_file_list_written_in_catalog_order(catalog, tmp_path, capsys):
    out = tmp_path / "lists" / "files_demo.txt"
    assert make_file_list.main(["demo", "--catalog", str(catalog), "--out", str(out)]) == 0
    assert out.read_text() == "a.bin\nGroup1/x.mat\nGroup2/x.mat\n"
    assert capsys.readouterr().out.strip() == "3"


def test_doc_files_left_out_unless_keep_all(catalog, tmp_path, capsys):
    out = tmp_path / "l.txt"
    assert make_file_list.main(["demo", "--catalog", str(catalog), "--out", str(out)]) == 0
    assert "load_bin.py" not in out.read_text()
    assert "left out (documentation): load_bin.py" in capsys.readouterr().err
    assert make_file_list.main(["demo", "--catalog", str(catalog), "--out", str(out), "--keep-all"]) == 0
    assert out.read_text().splitlines()[-1] == "load_bin.py"


def test_catalog_role_overrides_the_suffix_rule(catalog, tmp_path):
    out = tmp_path / "l.txt"
    assert make_file_list.main(["roles", "--catalog", str(catalog), "--out", str(out)]) == 0
    assert out.read_text() == "notes.txt\n"


def test_file_list_match(catalog, tmp_path):
    out = tmp_path / "l.txt"
    assert make_file_list.main(["demo", "--catalog", str(catalog), "--out", str(out), "--match", "Group2/"]) == 0
    assert out.read_text() == "Group2/x.mat\n"


@pytest.mark.parametrize("dataset", ["nope", "login", "partial"])
def test_file_list_refuses(catalog, tmp_path, dataset):
    out = tmp_path / "l.txt"
    assert make_file_list.main([dataset, "--catalog", str(catalog), "--out", str(out)]) == 2
    assert not out.exists()


def test_file_list_incomplete_allowed_on_request(catalog, tmp_path):
    out = tmp_path / "l.txt"
    args = ["partial", "--catalog", str(catalog), "--out", str(out), "--allow-incomplete"]
    assert make_file_list.main(args) == 0
    assert out.read_text() == "c.bin\n"


def test_real_catalog_lists_if_present():
    path = make_file_list.DEFAULT_CATALOG
    if not path.is_file():
        pytest.skip("configs/catalog.toml not merged yet")
    catalog = make_file_list.load_catalog(path)
    usable = [d for d, e in catalog["datasets"].items()
              if e.get("access") == "direct" and e.get("files_status") == "complete" and e.get("files")]
    assert usable, "no directly fetchable dataset with a complete file list"
    for dataset in usable:
        names = make_file_list.file_names(catalog, dataset)
        assert len({merge_shards.key_for(n) for n in names}) == len(names), f"{dataset}: output keys collide"


# ---- merge_shards ----------------------------------------------------------


def _finished(prepared, key, body="row"):
    folder = prepared / key
    (folder / "shards").mkdir(parents=True)
    (folder / "rows.jsonl").write_text(f'{{"shard": "shards/s.npy", "x": "{body}"}}\n')
    (folder / "shards" / "s.npy").write_bytes(b"\x00" * 8)
    (folder / "DONE").write_text("t\n")
    return folder


def test_merge_takes_only_finished_folders(tmp_path, capsys):
    prepared = tmp_path / "prepared" / "demo"
    _finished(prepared, "a.bin")
    _finished(prepared, "Group1__x.mat")
    (prepared / "Group2__x.mat").mkdir()  # failed: no DONE
    stage = prepared / ".a.bin.partial.7.1"
    stage.mkdir()
    (stage / "rows.jsonl").write_text("{}\n")
    lst = tmp_path / "files.txt"
    lst.write_text("# demo\na.bin\nGroup1/x.mat\nGroup2/x.mat\n\n")
    dest = tmp_path / "shards"

    rc = merge_shards.main(["--prepared", str(prepared), "--dest", str(dest), "--file-list", str(lst)])
    out = capsys.readouterr().out
    assert rc == 1 and "missing: Group2/x.mat" in out and "unfinished" in out
    assert sorted(p.name for p in (dest / "demo").iterdir()) == ["Group1__x.mat", "a.bin"]
    assert not list(dest.rglob(".*"))
    merged = dest / "demo" / "a.bin" / "shards" / "s.npy"
    assert os.stat(merged).st_ino == os.stat(prepared / "a.bin" / "shards" / "s.npy").st_ino  # hard link

    # rerun is a no-op; --allow-missing turns the gap into a warning only
    rc = merge_shards.main(["--prepared", str(prepared), "--dest", str(dest), "--file-list", str(lst),
                            "--allow-missing"])
    assert rc == 0 and "merged 0, already there 2" in capsys.readouterr().out


def test_merge_refuses_a_conflicting_folder(tmp_path):
    prepared = tmp_path / "p" / "demo"
    _finished(prepared, "a.bin", body="new")
    other = tmp_path / "shards" / "demo"
    _finished(other, "a.bin", body="old")
    assert merge_shards.main(["--prepared", str(prepared), "--dest", str(tmp_path / "shards")]) == 2


def test_merge_move(tmp_path):
    prepared = tmp_path / "p" / "demo"
    _finished(prepared, "a.bin")
    assert merge_shards.main(["--prepared", str(prepared), "--dest", str(tmp_path / "s"), "--move"]) == 0
    assert (tmp_path / "s" / "demo" / "a.bin" / "rows.jsonl").is_file()
    assert not (prepared / "a.bin").exists()


@needs_bash
def test_key_matches_the_job():
    names = ["a.bin", "SimulatedRadarWaveforms/Group1/x.mat", "dir/sub dir/f.bin"]
    script = 'while IFS= read -r NAME; do KEY="${NAME//\\//__}"; printf "%s\\n" "$KEY"; done'
    assert "KEY=\"${NAME//\\//__}\"" in _job_text()
    result = subprocess.run([BASH, "-c", script], input="\n".join(names) + "\n",
                            capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [merge_shards.key_for(n) for n in names]


# ---- the whole chain, locally, with stand-in modules -----------------------

FAKE_ACQUIRE = '''
import argparse, os, pathlib
p = argparse.ArgumentParser()
p.add_argument("--dataset"); p.add_argument("--only", action="append")
p.add_argument("--connections", type=int); p.add_argument("--max-gb", type=float)
a = p.parse_args()
assert a.connections == 1, a.connections
for name in a.only:
    dest = pathlib.Path(os.environ["MCLS_RAW"]) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"raw")
'''

FAKE_SOURCES = '''
import os
def get(name, root=None):
    if name != "demo":
        raise KeyError(name)
    assert not any(os.scandir(root)), "loader check must run before the download"
'''

FAKE_PREPROCESS = '''
import argparse, json, pathlib
p = argparse.ArgumentParser()
p.add_argument("--dataset"); p.add_argument("--raw", type=pathlib.Path); p.add_argument("--out", type=pathlib.Path)
a = p.parse_args()
raws = sorted(f for f in a.raw.rglob("*") if f.is_file())
assert raws, "no raw file"
(a.out / "shards").mkdir(parents=True, exist_ok=True)
(a.out / "shards" / "w.npy").write_bytes(b"w")
(a.out / "rows.jsonl").write_text(json.dumps({"shard": "shards/w.npy", "src": str(raws[0].relative_to(a.raw))}) + "\\n")
'''


STUB = "module() { return 0; }; export -f module; exec bash crc/prepare_array.job"


def _sandbox(tmp_path, names, acquire=FAKE_ACQUIRE):
    """A copy of the job with stand-in modules, a fake venv and module command. Returns (cwd, env)."""
    work = tmp_path / "mc"
    (work / "crc").mkdir(parents=True)
    shutil.copy(JOB, work / "crc")
    shutil.copy(ROOT / "crc" / "common.sh", work / "crc")
    (work / "mcls" / "sources").mkdir(parents=True)
    (work / "mcls" / "__init__.py").write_text("")
    (work / "mcls" / "sources" / "__init__.py").write_text(FAKE_SOURCES)
    (work / "mcls" / "acquire.py").write_text(acquire)
    (work / "mcls" / "preprocess.py").write_text(FAKE_PREPROCESS)
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "activate").write_text(f'export PATH="{venv / "bin"}:$PATH"\n')
    (venv / "bin" / "python").symlink_to(sys.executable)
    lst = tmp_path / "files.txt"
    lst.write_text("".join(f"{n}\n" for n in names))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MCLS_", "SGE_", "JOB_"))}
    env.update(MCLS_DATASET="demo", MCLS_FILE_LIST=str(lst), MCLS_OUT=str(tmp_path / "prepared" / "demo"),
               MCLS_VENV=str(venv), MCLS_PYTHON_MODULE="python/3.12", MCLS_NODE_TMP=str(tmp_path / "node"),
               JOB_ID="7", USER="tester")
    return work, env


def _task(work, env, task):
    env = dict(env, SGE_TASK_ID=str(task))
    return subprocess.run([BASH, "-c", STUB], cwd=work, env=env, capture_output=True, text=True, timeout=60)


@needs_bash
def test_job_then_merge_end_to_end(tmp_path):
    work, env = _sandbox(tmp_path, ["a.bin", "Group1/x.mat", "Group2/x.mat"])
    lst = Path(env["MCLS_FILE_LIST"])
    out = Path(env["MCLS_OUT"])
    node = Path(env["MCLS_NODE_TMP"])
    for task in (1, 2, 3, 2):  # the repeated task must be skipped
        result = _task(work, env, task)
        assert result.returncode == 0, result.stdout + result.stderr
    assert "already done" in result.stdout
    assert sorted(p.name for p in out.iterdir()) == ["Group1__x.mat", "Group2__x.mat", "a.bin"]
    assert '"src": "Group2/x.mat"' in (out / "Group2__x.mat" / "rows.jsonl").read_text()
    assert not [p for p in node.rglob("*") if p.is_file()], "raw or scratch left on the node"

    dest = tmp_path / "shards"
    rc = merge_shards.main(["--prepared", str(out), "--dest", str(dest), "--file-list", str(lst)])
    assert rc == 0
    assert len(list(dest.rglob("*.jsonl"))) == 3

    # a task past the end of the list fails clearly
    result = _task(work, env, 4)
    assert result.returncode != 0 and "no line 4" in result.stderr


@needs_bash
def test_job_stops_before_download_without_a_loader(tmp_path):
    work, env = _sandbox(tmp_path, ["a.bin"], acquire="raise SystemExit('acquire must not run')")
    result = _task(work, dict(env, MCLS_DATASET="nope"), 1)
    assert result.returncode == 3 and "nothing was downloaded" in result.stderr


ZIP_ACQUIRE = '''
import argparse, os, pathlib, zipfile
p = argparse.ArgumentParser()
p.add_argument("--dataset"); p.add_argument("--only", action="append")
p.add_argument("--connections", type=int); p.add_argument("--max-gb", type=float)
a = p.parse_args()
with zipfile.ZipFile(pathlib.Path(os.environ["MCLS_RAW"]) / a.only[0], "w") as z:
    z.writestr("rawdata/GPSL1@20MSps.bin", b"iq")
'''


@needs_bash
def test_job_unpacks_an_archive_on_request(tmp_path):
    work, env = _sandbox(tmp_path, ["rawdata.zip"], acquire=ZIP_ACQUIRE)
    result = _task(work, dict(env, MCLS_UNPACK="1"), 1)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = (Path(env["MCLS_OUT"]) / "rawdata.zip" / "rows.jsonl").read_text()
    assert '"src": "rawdata/GPSL1@20MSps.bin"' in rows  # preprocess saw the contents, not the zip
