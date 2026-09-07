"""Explicit opt-in root integration: benign transient service, no token or market IO."""

import configparser
import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix" or os.environ.get("TRADING_LAB_SYNTHETIC_SYSTEMD_TEST") != "1",
    reason="explicit server-only root sandbox probe",
)

PROBE = r"""
import errno, json, os, pathlib, subprocess, sys, time
from market_lab.futures import algopack_paper_runtime_v2
root = pathlib.Path(sys.argv[1])
code = ("import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('ready',flush=True); time.sleep(60)")
child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
assert child.stdout.readline().strip() == "ready"
denied = False
try:
    (root.parent / "outside_write_attempt").write_text("SYNTHETIC")
except OSError as error:
    denied = error.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
record = dict(uid=os.getuid(), parent=os.getpid(), child=child.pid,
    outside_write_denied=denied, runtime_imported=algopack_paper_runtime_v2.PROTOCOL,
    parent_cgroup=pathlib.Path('/proc/self/cgroup').read_text(),
    child_cgroup=pathlib.Path('/proc', str(child.pid), 'cgroup').read_text())
(root / "probe.json").write_text(json.dumps(record))
time.sleep(60)
"""


def test_template_sandbox_and_stubborn_child_cleanup():
    assert os.getuid() == 0
    project = Path(__file__).resolve().parents[1]
    assert project == Path("/opt/trading_lab")
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(project / "deploy/systemd/trading-lab-algopack-paper@.service")
    service = dict(parser["Service"])
    # Deliberately exclude production credential and activation/serve commands.
    for name in ("EnvironmentFile", "ExecStartPre", "ExecStart", "ReadWritePaths"):
        del service[name]
    outer = Path(tempfile.mkdtemp(prefix="paper-sandbox-", dir="/srv/trading_lab_data/runs"))
    os.chown(outer, 999, 989)
    inner = outer / "allowed"
    inner.mkdir(mode=0o700)
    os.chown(inner, 999, 989)
    unit = "trading-lab-synthetic-sandbox-" + uuid.uuid4().hex + ".service"
    command = ["systemd-run", "--quiet", "--unit=" + unit]
    for name, value in service.items():
        command.append("--property=" + name + "=" + value)
    command.extend(
        [
            "--property=ReadWritePaths=" + str(inner),
            "--property=RuntimeMaxSec=30s",  # Safety backstop for an interrupted test runner.
            str(project / ".venv/bin/python"),
            "-c",
            PROBE,
            str(inner),
        ]
    )
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=15)
        deadline = time.monotonic() + 15
        record = None
        while time.monotonic() < deadline:
            try:
                record = json.loads((inner / "probe.json").read_text())
                break
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.1)
        assert record is not None
        assert record["uid"] == 999 and record["outside_write_denied"]
        assert record["runtime_imported"] == "algopack_paper_runtime_v2"
        assert record["parent_cgroup"] == record["child_cgroup"]
        assert unit in record["parent_cgroup"]
        assert (inner / "probe.json").stat().st_mode & 0o777 == 0o600
        assert not (outer / "outside_write_attempt").exists()
        begin = time.monotonic()
        subprocess.run(["systemctl", "stop", unit], check=True, capture_output=True, timeout=25)
        stopped = time.monotonic() - begin
        state = subprocess.run(
            ["systemctl", "show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "Result"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        assert "ActiveState=failed" in state or "ActiveState=inactive" in state
        assert not Path("/proc", str(record["parent"])).exists()
        assert not Path("/proc", str(record["child"])).exists()
        group = record["parent_cgroup"].strip().split(":", 2)[2]
        procs = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
        assert not procs.exists() or not procs.read_text().strip()
        print(
            json.dumps(
                dict(
                    synthetic_only=True,
                    unit=unit,
                    artifacts=str(outer),
                    stop_seconds=stopped,
                    state=state.strip(),
                    cleanup_verified=True,
                )
            )
        )
    finally:
        subprocess.run(["systemctl", "stop", unit], capture_output=True, timeout=25)
