"""Bounded one-shot GPR vintage source acquisition; metadata only, no market outcomes."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests
from pandas.io.stata import StataReader

PROTOCOL = "v80_gpr_vintages_source_v1"
REPO = Path(__file__).resolve().parents[3]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8-sig")


def write_new(path, obj):
    with path.open("xb") as stream:
        stream.write(encoded(obj))
        stream.flush()
        os.fsync(stream.fileno())


def verify(expected):
    path = REPO / f"configs/{PROTOCOL}.seal.json"
    if not re.fullmatch("[0-9a-f]{64}", expected) or sha(path.read_bytes()) != expected:
        raise ValueError("seal_changed")
    seal = json.loads(path.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        if sha((REPO / name).read_bytes()) != digest:
            raise ValueError("sealed_file_changed")
    cfg = json.loads((REPO / f"configs/{PROTOCOL}.json").read_text(encoding="utf-8-sig"))
    if cfg["protocol_id"] != PROTOCOL or cfg["source_only"] is not True:
        raise ValueError("scope_changed")
    return cfg


def plan():
    all_months = pd.period_range("2022-03", "2025-12", freq="M").strftime("%Y%m").tolist()
    pilots = ["202203", "202401", "202512"]
    return pilots + [month for month in all_months if month not in pilots]


def history_url(month):
    if month not in plan():
        raise ValueError("protected_or_unplanned_vintage")
    path = f"gpr_archive_files/data_gpr_export_{month}.dta"
    return ("https://api.github.com/repos/iacoviel/iacoviel.github.io/commits"
            f"?path={path}&per_page=100")


def raw_url(month, commit):
    history_url(month)
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ValueError("invalid_commit")
    return (f"https://raw.githubusercontent.com/iacoviel/iacoviel.github.io/{commit}/"
            f"gpr_archive_files/data_gpr_export_{month}.dta")


def get(session, url):
    for attempt, delay in enumerate((0, 5, 15)):
        time.sleep(delay + 0.5)
        try:
            with session.get(url, timeout=(15, 45), allow_redirects=False, stream=True,
                             headers={"User-Agent": "TradingLab-source-research/1.0"}) as response:
                if response.status_code != 200 or response.url != url:
                    raise ValueError(f"http_{response.status_code}")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise ValueError("response_cap")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                return raw, {"url": url, "status": 200,
                             "retrieved_at_utc": datetime.now(UTC).isoformat(),
                             "bytes": len(raw), "sha256": sha(raw), "attempt": attempt + 1}
        except requests.RequestException:
            if attempt == 2:
                raise ValueError("transport_exhausted") from None
    raise ValueError("unreachable")


def first_commit(raw):
    rows = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(rows, list) or not 0 < len(rows) < 100:
        raise ValueError("empty_or_unpaginated_commit_history")
    row = rows[-1]
    digest = row["sha"]
    if not re.fullmatch("[0-9a-f]{40}", digest):
        raise ValueError("invalid_commit")
    clocks = [pd.Timestamp(row["commit"][part]["date"]) for part in ("author", "committer")]
    if any(clock.tzinfo is None for clock in clocks):
        raise ValueError("untimed_commit")
    return {"commit": digest, "commit_timestamp_proxy": max(clocks).tz_convert("UTC").isoformat(),
            "history_entries": len(rows), "actual_public_push_time_verified": False}


def metadata(raw, month):
    history_url(month)
    with StataReader(io.BytesIO(raw)) as reader:
        labels = reader.variable_labels()
        if "month" not in labels:
            raise ValueError("missing_month_column")
        dates = reader.read(columns=["month"])["month"]
    if (not pd.api.types.is_datetime64_any_dtype(dates) or dates.isna().any()
            or not dates.is_monotonic_increasing or dates.duplicated().any()
            or dates.ge(pd.Timestamp("2026-01-01")).any()
            or dates.gt(pd.Timestamp(month + "01")).any()):
        raise ValueError("invalid_or_protected_source_months")
    recent = dates[dates.lt(pd.Timestamp(month + "01"))].tail(13)
    expected = pd.period_range(pd.Period(month, freq="M") - 13,
                               pd.Period(month, freq="M") - 1, freq="M")
    return {"columns": labels, "rows": len(dates),
            "minimum_month": str(dates.min().date()), "maximum_month": str(dates.max().date()),
            "complete_prior13_month_calendar": (
                recent.dt.to_period("M").tolist() == expected.tolist()),
            "russia_variable_candidates": [key for key, label in labels.items()
                                            if "russ" in label.lower()
                                            or key.upper().endswith("RUS")],
            "numeric_gpr_values_read_for_design": False,
            "contains_market_prices_returns_targets_or_pnl": False}


def run(expected, full=False):
    import fcntl

    cfg = verify(expected)
    if os.name != "posix" or os.getuid() != 999:
        raise ValueError("server_service_user_only")
    root = Path(cfg["root"])
    if root.resolve() != root.absolute() or not root.is_dir():
        raise ValueError("invalid_root")
    with (root / ".writer.lock").open("a+b") as lock, requests.Session() as session:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root / "manifest.json").exists():
            raise ValueError("already_complete")
        results = []
        for month in (plan() if full else plan()[:3]):
            destination = root / month
            if destination.exists():
                item = json.loads((destination / "manifest.json").read_text(encoding="utf-8-sig"))
                if item["source_seal_sha256"] != expected:
                    raise ValueError("old_job_identity_changed")
                for filename, name in (("commits.json", "history"), ("data.dta", "raw")):
                    if sha((destination / filename).read_bytes()) != item[name]["sha256"]:
                        raise ValueError("old_source_changed")
            else:
                history, evidence = get(session, history_url(month))
                commit = first_commit(history)
                raw, receipt = get(session, raw_url(month, commit["commit"]))
                info = metadata(raw, month)
                item = {"month": month, "source_seal_sha256": expected, "commit": commit,
                        "history": evidence, "raw": receipt, "metadata": info}
                temporary = Path(tempfile.mkdtemp(prefix=f".partial_{month}_", dir=root))
                for filename, content in (("commits.json", history), ("data.dta", raw)):
                    with (temporary / filename).open("xb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                write_new(temporary / "manifest.json", item)
                temporary.rename(destination)
                descriptor = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            results.append(item)
            print(json.dumps(item), flush=True)
        if full:
            verify(expected)
            write_new(root / "manifest.json", {"source_seal_sha256": expected,
                      "status": "SOURCE_METADATA_COMPLETE", "vintages": results,
                      "all_46_vintages": len(results) == 46, "economic_admission": False})
        return {"status": "SOURCE_METADATA_COMPLETE" if full else "PILOT_COMPLETE",
                "completed_vintages": len(results), "planned_vintages": 46}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal-sha256", required=True)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.seal_sha256, args.full)), flush=True)
    except Exception as error:
        print(json.dumps({"status": "STOPPED", "error_type": type(error).__name__,
                          "code": (str(error) if isinstance(error, ValueError)
                                   else "source_failure")}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
