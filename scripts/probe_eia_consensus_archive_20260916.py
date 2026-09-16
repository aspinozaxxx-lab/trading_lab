"""Bounded source feasibility only; no market inputs, model, targets or PnL.

Fetch the first two previously observed pre-Wednesday calendar captures. Do not
follow redirects, execute embedded scripts, substitute today's page or retry.
The output is private source evidence outside Git, NOT an admitted feature set.
"""

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

STAMPS = ("20210104164842", "20210110095453")
ORIGINAL = "https://www.forexfactory.com/calendar"
ROOT = Path("/srv/trading_lab_data/source_evidence/eia_consensus_probe_20260916_v1")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def probe() -> None:
    ROOT.mkdir(exist_ok=False)
    report = {
        "protocol": "eia_consensus_archive_feasibility_20260916_v1",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "selection": "First two observed 2021 Monday/Sunday captures; no value selection",
        "archive_stamps": STAMPS,
        "original_url": ORIGINAL,
        "follow_redirects": False,
        "economic_admission": False,
        "source_coverage_verified": False,
        "market_values_read": False,
        "strategy_results_computed": False,
        "attempts": [],
    }
    with (ROOT / "declaration.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    for stamp in STAMPS:
        assert re.fullmatch(r"202[0-5][0-9]{10}", stamp)
        url = f"https://web.archive.org/web/{stamp}id_/{ORIGINAL}"
        header_path = ROOT / f"{stamp}.headers.txt"
        # No -L, credentials, cookies, retry, JS execution or live-site fallback.
        response = subprocess.run(
            [
                "curl", "-q", "--http1.1", "--silent", "--show-error",
                "--connect-timeout", "10", "--max-time", "30",
                "--max-filesize", "8000000", "--proto", "=https",
                "--user-agent", "TradingLab private research source feasibility",
                "--dump-header", str(header_path),
                "--write-out", "\n__HTTP_STATUS__%{http_code}", url,
            ],
            capture_output=True, timeout=35, check=False,
        )
        raw, marker, status = response.stdout.rpartition(b"\n__HTTP_STATUS__")
        if not marker:
            raw, status = response.stdout, b"000"
        raw_path = ROOT / f"{stamp}.body"
        with raw_path.open("xb") as handle:
            handle.write(raw)
        headers = header_path.read_bytes() if header_path.exists() else b""
        # Presence only, not a forecast parser or an availability assertion.
        row = {
            "requested_url": url,
            "archive_timestamp": stamp,
            "received_at_utc": datetime.now(UTC).isoformat(),
            "curl_returncode": response.returncode,
            "http_status": status.decode("ascii", errors="replace"),
            "body_file": raw_path.name,
            "body_bytes": len(raw),
            "body_sha256": sha(raw),
            "headers_file": header_path.name,
            "headers_sha256": sha(headers),
            "crude_inventory_label_count": raw.lower().count(b"crude oil inventories"),
            "forecast_label_count": raw.lower().count(b"forecast"),
            "stderr": response.stderr.decode("utf-8", errors="replace")[:1000],
        }
        report["attempts"].append(row)
        print(json.dumps(row), flush=True)
        # Authentication/rate/access refusal is terminal; do not probe around it.
        if status in (b"401", b"403", b"429"):
            report["stopped_after_access_refusal"] = True
            break
    report["completed_at_utc"] = datetime.now(UTC).isoformat()
    with (ROOT / "report.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({"report_path": str(ROOT / "report.json"),
                      "report_sha256": sha((ROOT / "report.json").read_bytes())}))


if __name__ == "__main__":
    probe()
