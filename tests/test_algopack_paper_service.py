"""Static deployment contract; not a claim that the production service was started."""

import configparser
from pathlib import Path

UNIT = Path(__file__).resolve().parents[1] / "deploy/systemd/trading-lab-algopack-paper@.service"


def unit():
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(UNIT.read_text(encoding="utf-8"))
    return parser


def test_explicit_sealed_instance_only():
    parsed = unit()
    service = parsed["Service"]
    command = (
        "/opt/trading_lab/.venv/bin/python -m "
        "market_lab.futures.algopack_paper_runtime_v2 --activation-sha256 %i"
    )
    assert service["ExecStartPre"] == command + " --check"
    assert service["ExecStart"] == command + " --serve"
    assert "--initialize" not in UNIT.read_text()
    assert "Install" not in parsed  # No automatic boot admission before seal/genesis.
    assert service["Restart"] == "no"


def test_entire_worker_group_stopped():
    service = unit()["Service"]
    assert service["Type"] == "exec"
    assert service["KillMode"] == "control-group"
    assert service["KillSignal"] == "SIGTERM"
    assert service["SendSIGKILL"] == "yes"
    assert service["TimeoutStopSec"] == "15s"


def test_private_instance_writes_and_server_secret_only():
    service = unit()["Service"]
    assert service["User"] == service["Group"] == "trading-lab"
    assert service["EnvironmentFile"] == "/etc/trading-lab/collector.env"
    assert service["ProtectSystem"] == "strict"
    assert service["ReadWritePaths"] == (
        "/srv/trading_lab_data/data/forward/algopack-paper-v1/%i"
    )
    assert service["UMask"] == "0077"
    assert service["NoNewPrivileges"] == "true"
    assert service["PrivateTmp"] == "true"
    assert service["StandardOutput"] == service["StandardError"] == "journal"
