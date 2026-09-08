"""One-time operational scheduling does not change sealed economic/runtime code."""

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "trading-lab-paper-bootstrap-20260909"
IDENTITY = "f51c02902825f61ba74cfbbcdd719d7233bc1839f1a152d9289e35e9ea3624e0"


def test_start_after_published_boundary_only():
    timer = (ROOT / "deploy/systemd" / (NAME + ".timer")).read_text()
    date = next(row.split("=", 1)[1] for row in timer.splitlines() if row.startswith("OnCalendar="))
    at = datetime.strptime(date, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    activation = json.loads(
        (ROOT / "configs/algopack_paper_forward_v1.activation.json").read_bytes()
    )
    assert at > datetime.fromisoformat(activation["future_start"])
    assert "Persistent=false" in timer and "RandomizedDelaySec=0" in timer
    assert "Unit=" + NAME + ".service" in timer


def test_no_reset_overwrite_secret_or_implicit_recovery():
    unit = (ROOT / "deploy/systemd" / (NAME + ".service")).read_text()
    assert (
        "ConditionPathExists=!/srv/trading_lab_data/data/forward/algopack-paper-v1/" + IDENTITY
        in unit
    )
    commands = [row.split("=", 1)[1] for row in unit.splitlines() if row.startswith("ExecStart=")]
    assert len(commands) == 6
    for command, mode in zip(commands[:2], ("--check", "--initialize"), strict=True):
        assert command.startswith("/usr/sbin/runuser -u trading-lab -- ")
        assert command.endswith("--activation-sha256 " + IDENTITY + " " + mode)
    assert commands[2].startswith("/usr/bin/cp --no-clobber ")
    assert commands[3].startswith("/usr/bin/cmp --silent ")
    assert commands[4] == "/usr/bin/systemctl daemon-reload"
    assert (
        commands[5]
        == "/usr/bin/systemctl start trading-lab-algopack-paper@" + IDENTITY + ".service"
    )
    assert "EnvironmentFile" not in unit and "Restart=no" in unit
