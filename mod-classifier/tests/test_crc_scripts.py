"""Static checks on the CRC and helper shell scripts (nothing here runs on CRC)."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted(
    p
    for folder in ("crc", "scripts")
    for pattern in ("*.sh", "*.job")
    for p in (ROOT / folder).glob(pattern)
)
BASH = shutil.which("bash")


def _id(path):
    return f"{path.parent.name}/{path.name}"


def test_scripts_found():
    names = {p.name for p in SCRIPTS}
    for expected in (
        "common.sh",
        "setup_env.sh",
        "check_env.sh",
        "check_node.sh",
        "check_node.job",
        "prepare_array.job",
        "run_tests.sh",
    ):
        assert expected in names


@pytest.mark.skipif(BASH is None, reason="bash not installed")
@pytest.mark.parametrize("script", SCRIPTS, ids=_id)
def test_bash_syntax(script):
    result = subprocess.run([BASH, "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", SCRIPTS, ids=_id)
def test_shebang_and_strict_mode(script):
    text = script.read_text()
    assert text.startswith("#!/bin/bash\n")
    if script.name != "common.sh":  # sourced, so it inherits the caller's mode
        assert "set -euo pipefail" in text


def test_array_job_caps_concurrent_downloads():
    text = (ROOT / "crc" / "prepare_array.job").read_text()
    assert "#$ -tc 8" in text
    assert "/tmp/$USER/mcls_raw" in text
    assert "--only" in text and "--connections" in text


def test_no_training_job_yet():
    # Training jobs are written later, on request.
    assert not [p for p in SCRIPTS if "train" in p.name]
