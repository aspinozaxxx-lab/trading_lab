"""One five-page source-only follow-up, selected before reading page contents."""

import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path("/srv/trading_lab_data/source_evidence/eia_consensus_tuesday_probe_20260916_v1")
CDX_SHA = "e0afb5e411833d4aae08a204b90d3d6cc711bfdfc6ac85c543f109c81786b0e2"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    raw_catalog = (ROOT / "cdx.json").read_bytes()
    assert sha(raw_catalog) == CDX_SHA
    catalog = json.loads(raw_catalog)
    assert catalog[0] == ["timestamp", "original", "statuscode", "mimetype", "digest"]
    rows = [dict(zip(catalog[0], r, strict=True)) for r in catalog[1:]]
    assert all("2021" <= r["timestamp"][:4] <= "2025" for r in rows)
    choices = []
    for year in range(2021, 2026):
        choices.append(min(
            (r for r in rows if int(r["timestamp"][:4]) == year
             and datetime.strptime(r["timestamp"], "%Y%m%d%H%M%S").weekday() == 1),
            key=lambda r: r["timestamp"],
        ))
    output = ROOT / "captures"
    output.mkdir(exist_ok=False)
    report = {"protocol": "eia_consensus_tuesday_feasibility_20260916_v1",
              "started_at_utc": datetime.now(UTC).isoformat(),
              "selection": "First Tuesday capture in each year 2021-2025",
              "cdx_sha256": CDX_SHA, "choices": choices, "attempts": [],
              "economic_admission": False, "strategy_results_computed": False}
    with (output / "declaration.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    for choice in choices:
        stamp, original = choice["timestamp"], choice["original"]
        assert original in {"https://www.forexfactory.com/calendar",
                            "https://www.forexfactory.com/calendar/",
                            "https://www.forexfactory.com/calendar?"}
        url = f"https://web.archive.org/web/{stamp}id_/{original}"
        headers_file = output / f"{stamp}.headers.txt"
        response = subprocess.run([
            "curl", "-q", "--http1.1", "-sS", "--connect-timeout", "10",
            "--max-time", "30", "--max-filesize", "8000000", "--proto", "=https",
            "--user-agent", "TradingLab private research source feasibility",
            "--dump-header", str(headers_file), "-w", "\n__STATUS__%{http_code}", url,
        ], capture_output=True, timeout=35, check=False)
        raw, marker, status = response.stdout.rpartition(b"\n__STATUS__")
        if not marker:
            raw, status = response.stdout, b"000"
        with (output / f"{stamp}.body").open("xb") as handle:
            handle.write(raw)
        headers = headers_file.read_bytes() if headers_file.exists() else b""
        dates = re.findall(rb"(?im)^memento-datetime:\s*([^\r\n]+)", headers)
        correct_stamp = bool(dates) and parsedate_to_datetime(dates[-1].decode()).strftime(
            "%Y%m%d%H%M%S") == stamp
        item = {"url": url, "received_at_utc": datetime.now(UTC).isoformat(),
                "curl_returncode": response.returncode, "http_status": status.decode(),
                "body_bytes": len(raw), "body_sha256": sha(raw),
                "headers_sha256": sha(headers), "exact_memento_timestamp": correct_stamp,
                "crude_inventory_label_count": raw.lower().count(b"crude oil inventories"),
                "stderr": response.stderr.decode(errors="replace")[:1000]}
        report["attempts"].append(item)
        print(json.dumps(item), flush=True)
        if status in (b"401", b"403", b"429"):
            report["stopped_after_access_refusal"] = True
            break
    report["completed_at_utc"] = datetime.now(UTC).isoformat()
    with (output / "report.json").open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({"report_path": str(output / "report.json"),
                      "report_sha256": sha((output / "report.json").read_bytes())}))


if __name__ == "__main__":
    main()
