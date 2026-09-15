"""GPR vintage metadata V2: preserve raw undated rows, use dated calendar only."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import tempfile
from pathlib import Path

import pandas as pd
import requests
from pandas.io.stata import StataReader

from market_lab.futures import gpr_vintages_source_v1 as parent

PROTOCOL = "v80_gpr_vintages_source_v2"
REPO = parent.REPO
PARENT_SEAL = "b6d521960cd39f2125802c034744d96227a8468895b4ccd7dce139995028f253"
sha, encoded, write_new = parent.sha, parent.encoded, parent.write_new
plan, get, first_commit = parent.plan, parent.get, parent.first_commit
history_url, raw_url = parent.history_url, parent.raw_url


def verify(expected):
    path = REPO / f"configs/{PROTOCOL}.seal.json"
    if not re.fullmatch("[0-9a-f]{64}", expected) or sha(path.read_bytes()) != expected:
        raise ValueError("seal_changed")
    seal = json.loads(path.read_text(encoding="utf-8-sig"))
    for name, digest in seal["files"].items():
        if sha((REPO / name).read_bytes()) != digest:
            raise ValueError("sealed_file_changed")
    parent.verify(PARENT_SEAL)
    cfg = json.loads((REPO / f"configs/{PROTOCOL}.json").read_text(encoding="utf-8-sig"))
    if cfg["protocol_id"] != PROTOCOL or cfg["source_only"] is not True:
        raise ValueError("scope_changed")
    return cfg


def metadata(raw, month):
    history_url(month)
    with StataReader(io.BytesIO(raw)) as reader:
        labels = reader.variable_labels()
        if "month" not in labels:
            raise ValueError("missing_month_column")
        dates = reader.read(columns=["month"])["month"]
    if not pd.api.types.is_datetime64_any_dtype(dates):
        raise ValueError("invalid_month_dtype")
    valid = dates.dropna()
    if (valid.empty or not valid.is_monotonic_increasing or valid.duplicated().any()
            or valid.ge(pd.Timestamp("2026-01-01")).any()
            or valid.gt(pd.Timestamp(month + "01")).any()):
        raise ValueError("invalid_or_protected_source_months")
    recent = valid[valid.lt(pd.Timestamp(month + "01"))].tail(13)
    expected = pd.period_range(pd.Period(month, freq="M") - 13,
                               pd.Period(month, freq="M") - 1, freq="M")
    return {"columns": labels, "rows": len(dates), "dated_rows": len(valid),
            "undated_rows_preserved_not_used": int(dates.isna().sum()),
            "minimum_month": str(valid.min().date()), "maximum_month": str(valid.max().date()),
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
