"""Collect the sealed weekly MOEX core-four option-state history source V3."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_options_surface_history_v2 as transport

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/moex_options_weekly_state_source_v3.yaml"
CONFIG_SHA256: Final[str] = "a1ec093e64f79f48371c60ec8c18abfbaece4e22a22bb60086c58ef594aac1f3"
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/options/moex-core4-options-weekly-2021-2025-v3"
)
MODULE_PATH: Final[Path] = Path(__file__).resolve()
TRANSPORT_SHA256: Final[str] = "acabc5f8de5e075d3d47acf58fab99095a279755cbf7faea9d7ef98941e7d24c"


def load_config() -> dict[str, Any]:
    actual = transport._sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("MOEX option weekly V3 config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_id") != "moex_options_weekly_state_source_v3"
        or config.get("live_trading_allowed") is not False
        or config["objective"]["signal_returns_targets_predictions_or_pnl_allowed"] is not False
        or config["objective"]["economic_rule_fixed_by_this_protocol"] is not False
        or config["decision_calendar"]["all_other_columns_forbidden"] is not True
    ):
        raise ValueError("MOEX option weekly V3 invariants drifted")
    if transport._sha_file(Path(transport.__file__)) != TRANSPORT_SHA256:
        raise ValueError("MOEX option weekly V3 transport dependency drifted")
    return config


def decision_dates(config: dict[str, Any]) -> list[date]:
    spec = config["decision_calendar"]
    path = PROJECT_ROOT / spec["artifact"]
    if transport._sha_file(path) != spec["sha256"]:
        raise ValueError("MOEX option weekly V3 decision calendar artifact drifted")
    frame = pd.read_parquet(path, columns=[spec["permitted_column"]])
    values = pd.to_datetime(frame[spec["permitted_column"]], errors="raise").dt.normalize()
    values = values[(values >= spec["start"]) & (values <= spec["end"])]
    unique = sorted({value.date() for value in values})
    if (
        len(unique) != int(spec["expected_unique_dates"])
        or unique[0].isoformat() != spec["expected_first_date"]
        or unique[-1].isoformat() != spec["expected_last_date"]
    ):
        raise ValueError("MOEX option weekly V3 decision calendar count drifted")
    return unique


def canonical_jobs(config: dict[str, Any]) -> list[tuple[date, str]]:
    jobs = [
        (value, asset) for value in decision_dates(config) for asset in config["source"]["assets"]
    ]
    if len(jobs) != 1044 or len(set(jobs)) != 1044:
        raise ValueError("MOEX option weekly V3 exact job grid drifted")
    return jobs


def collect(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    jobs: list[tuple[date, str]] | None = None,
    session: transport.SessionLike | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
    max_workers: int = 16,
) -> Path:
    config = load_config()
    canonical = jobs is None
    selected_jobs = canonical_jobs(config) if canonical else list(jobs or [])
    if not selected_jobs or len(set(selected_jobs)) != len(selected_jobs):
        raise ValueError("MOEX option weekly V3 jobs must be nonempty and unique")
    allowed_dates = set(decision_dates(config))
    allowed_assets = set(config["source"]["assets"])
    if any(
        value not in allowed_dates or asset not in allowed_assets for value, asset in selected_jobs
    ):
        raise ValueError("MOEX option weekly V3 job outside sealed grid")
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("MOEX option weekly V3 retrieval must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")

    results: dict[tuple[date, str], tuple[pd.DataFrame, list[dict[str, Any]]]] = {}
    workers = 1 if session is not None else max(1, int(max_workers))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(transport.fetch_job, value, asset, config, session): (value, asset)
            for value, asset in selected_jobs
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            results[futures[future]] = future.result()
            if canonical and completed % 25 == 0:
                print(
                    f"MOEX option weekly V3 progress {completed}/{len(selected_jobs)}", flush=True
                )

    frames = [results[job][0] for job in selected_jobs if len(results[job][0])]
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    normalized = transport.normalize(combined, retrieval, config)
    raw_pages = [page for job in selected_jobs for page in results[job][1]]

    output_root = output_root.resolve()
    if output_root.exists():
        raise FileExistsError(f"immutable MOEX option weekly V3 output exists: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_root.name}-", dir=output_root.parent))
    try:
        request_log: list[dict[str, Any]] = []
        raw_zip = temporary / "raw_responses.zip"
        with zipfile.ZipFile(raw_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for page in sorted(
                raw_pages,
                key=lambda item: (item["query_date"], item["server_assetcode"], int(item["start"])),
            ):
                member = (
                    f"raw/{page['query_date']}/{page['server_assetcode']}/"
                    f"{int(page['start']):06d}.json"
                )
                archive.writestr(member, page["raw"])
                request_log.append(
                    {
                        key: page[key]
                        for key in ("query_date", "server_assetcode", "start", "url", "rows")
                    }
                    | {
                        "zip_member": member,
                        "response_bytes": len(page["raw"]),
                        "response_sha256": transport._sha_bytes(page["raw"]),
                    }
                )
        transport._write_json(temporary / "requests.json", request_log)
        processed = temporary / "options_weekly_core4.parquet"
        normalized.to_parquet(processed, index=False)
        manifest = {
            "protocol_id": config["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": transport._sha_file(MODULE_PATH),
            "transport_implementation_sha256": TRANSPORT_SHA256,
            "decision_calendar_sha256": config["decision_calendar"]["sha256"],
            "retrieved_at_utc": retrieval.isoformat(),
            "canonical_source": canonical,
            "job_count": len(selected_jobs),
            "raw_page_count": len(request_log),
            "contains_returns_targets_predictions_or_pnl": False,
            "raw_zip": {
                "path": raw_zip.name,
                "bytes": raw_zip.stat().st_size,
                "sha256": transport._sha_file(raw_zip),
            },
            "requests": {
                "path": "requests.json",
                "bytes": (temporary / "requests.json").stat().st_size,
                "sha256": transport._sha_file(temporary / "requests.json"),
                "rows": len(request_log),
            },
            "processed": {
                "path": processed.name,
                "bytes": processed.stat().st_size,
                "sha256": transport._sha_file(processed),
                "rows": len(normalized),
                "minimum_tradedate": normalized["tradedate"].min().date().isoformat()
                if len(normalized)
                else None,
                "maximum_tradedate": normalized["tradedate"].max().date().isoformat()
                if len(normalized)
                else None,
            },
        }
        transport._write_json(temporary / "manifest.json", manifest)
        temporary.rename(output_root)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(output_root)
    transport._write_json(
        output_root / "audit.json", {"checks": checks, "all_true": all(checks.values())}
    )
    if not all(checks.values()):
        raise ValueError("MOEX option weekly V3 audit failed")
    return output_root


def audit(output_root: Path) -> dict[str, bool]:
    config = load_config()
    manifest = json.loads((output_root / "manifest.json").read_text(encoding="utf-8-sig"))
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    raw_zip = output_root / manifest["raw_zip"]["path"]
    requests_path = output_root / manifest["requests"]["path"]
    checks = {
        "protocol_exact": manifest["protocol_id"] == config["protocol_id"],
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"]
        == transport._sha_file(MODULE_PATH),
        "transport_exact": manifest["transport_implementation_sha256"] == TRANSPORT_SHA256,
        "decision_calendar_exact": manifest["decision_calendar_sha256"]
        == config["decision_calendar"]["sha256"],
        "target_free": manifest["contains_returns_targets_predictions_or_pnl"] is False,
        "raw_zip_exact": raw_zip.stat().st_size == manifest["raw_zip"]["bytes"]
        and transport._sha_file(raw_zip) == manifest["raw_zip"]["sha256"],
        "requests_exact": requests_path.stat().st_size == manifest["requests"]["bytes"]
        and transport._sha_file(requests_path) == manifest["requests"]["sha256"],
    }
    request_log = json.loads(requests_path.read_text(encoding="utf-8-sig"))
    rebuilt: list[pd.DataFrame] = []
    raw_exact = True
    with zipfile.ZipFile(raw_zip) as archive:
        for item in request_log:
            raw = archive.read(item["zip_member"])
            raw_exact &= (
                len(raw) == item["response_bytes"]
                and transport._sha_bytes(raw) == item["response_sha256"]
            )
            query_date = date.fromisoformat(item["query_date"])
            raw_exact &= item["url"] == transport.request_url(
                config, query_date, item["server_assetcode"], int(item["start"])
            )
            frame, index, _ = transport.parse_page(raw, query_date, config)
            raw_exact &= index == int(item["start"])
            if len(frame):
                frame["server_assetcode"] = item["server_assetcode"]
                rebuilt.append(frame)
    checks["all_raw_pages_exact"] = raw_exact
    replay = transport.normalize(
        pd.concat(rebuilt, ignore_index=True) if rebuilt else pd.DataFrame(), retrieval, config
    )
    processed_path = output_root / manifest["processed"]["path"]
    stored = pd.read_parquet(processed_path)
    try:
        pd.testing.assert_frame_equal(stored, replay, check_dtype=False)
        frame_exact = True
    except AssertionError:
        frame_exact = False
    checks["processed_exact"] = (
        processed_path.stat().st_size == manifest["processed"]["bytes"]
        and transport._sha_file(processed_path) == manifest["processed"]["sha256"]
        and len(stored) == manifest["processed"]["rows"]
        and frame_exact
    )
    if manifest["canonical_source"]:
        checks["canonical_grid_exact"] = (
            manifest["job_count"] == 1044 and len(decision_dates(config)) == 261
        )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--max-workers", type=int, default=16)
    args = parser.parse_args()
    if args.audit_only:
        checks = audit(args.output_root)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(collect(args.output_root, max_workers=args.max_workers))


if __name__ == "__main__":
    main()
