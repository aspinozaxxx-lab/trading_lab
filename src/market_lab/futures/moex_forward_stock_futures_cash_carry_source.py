"""Collect immutable forward BID/OFFER snapshots for covered stock-futures carry."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Final
from typing import Protocol as TypingProtocol
from urllib.parse import quote, urlencode

import pandas as pd
import yaml

from market_lab.futures import iss
from market_lab.futures import moex_stock_futures_cash_carry_source as daily_source
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/moex_forward_stock_futures_cash_carry_source_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "b25fe86c1aaccb6e615647b3f84efb3c45df33185e71debee497702e5ac2c4c6"
)
DEFAULT_OUTPUT_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/forward/moex-stock-futures-cash-carry-v1"
)
MOSCOW_TZ: Final[str] = "Europe/Moscow"
STAGES: Final[tuple[str, ...]] = ("decision", "fill")
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "source_date",
    "stage",
    "logical_asset",
    "venue_kind",
    "secid",
    "board_id",
    "selected_contract_id",
    "expiry_reference_date",
    "days_to_expiry_reference",
    "lot_size_shares",
    "bid",
    "offer",
    "exchange_systime",
    "exchange_updatetime",
    "exchange_seqnum",
    "retrieved_at_utc",
    "access_mode",
    "valid",
    "invalid_reason",
)


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    output_root: Path


class JsonClient(TypingProtocol):
    def get_json(self, url: str) -> dict[str, Any]: ...


def _sha(path: Path) -> str:
    return daily_source.sha256_file(path)


def _safe_output_root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe forward cash-carry output path: {value}")
    if tuple(part.lower() for part in relative.parts[:2]) != ("data", "forward"):
        raise ValueError("forward cash-carry output must be under data/forward")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("forward cash-carry protocol must be an object")
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "moex_forward_stock_futures_cash_carry_source_v1"
        or payload.get("live_trading_allowed") is not False
        or tuple(payload["stages"]["allowed_stage_arguments"]) != STAGES
        or payload["collection"]["atomic_immutable_snapshot"] is not True
        or payload["collection"]["no_partial_valid_status_if_any_asset_pair_is_invalid"]
        is not True
        or int(payload["universe"]["required_futures_lot_size_shares"]) != 100
    ):
        raise ValueError("forward cash-carry protocol drifted")
    return Protocol(payload, actual, _safe_output_root(payload["output"]["root"]))


def _canonical_json_bytes(records: list[dict[str, Any]]) -> bytes:
    lines = [
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for item in records
    ]
    return daily_source._raw_bytes([json.loads(line) for line in lines])


def _series_url(asset: str) -> str:
    return iss.futures_series_url(daily_source.AssetSpec.from_symbol(asset))


def _description_url(secid: str) -> str:
    return f"https://iss.moex.com/iss/securities/{quote(secid, safe='')}.json?iss.meta=off"


def _market_url(kind: str, secid: str) -> str:
    if kind == "spot":
        engine, market, board = "stock", "shares", "TQBR"
    elif kind == "futures":
        engine, market, board = "futures", "forts", "RFUD"
    else:
        raise ValueError(f"unknown venue kind: {kind}")
    query_string = urlencode({"iss.meta": "off", "iss.only": "securities,marketdata"})
    return (
        f"https://iss.moex.com/iss/engines/{engine}/markets/{market}/boards/{board}/"
        f"securities/{quote(secid, safe='')}.json?{query_string}"
    )


def _source_context(
    protocol: Protocol,
    stage: str,
    retrieved_at: str | datetime | pd.Timestamp | None,
) -> tuple[date, pd.Timestamp]:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    retrieval = pd.Timestamp.now(tz="UTC") if retrieved_at is None else pd.Timestamp(retrieved_at)
    if retrieval.tzinfo is None:
        raise ValueError("retrieval timestamp must be timezone-aware")
    retrieval = retrieval.tz_convert("UTC")
    local = retrieval.tz_convert(MOSCOW_TZ)
    source_date = local.date()
    boundary = date.fromisoformat(protocol.payload["forward_boundary"]["earliest_source_date"])
    if source_date < boundary:
        raise ValueError("forward source date precedes sealed boundary")
    scheduled = time.fromisoformat(protocol.payload["stages"][stage]["scheduled_local_time"])
    if local.time().replace(tzinfo=None) < scheduled:
        raise ValueError(f"{stage} collection is earlier than sealed local schedule")
    return source_date, retrieval


def _description(payload: dict[str, Any], secid: str, asset: str) -> dict[str, Any]:
    frame = iss._parse_iss_block(payload, "description", frozenset({"name", "value"}))
    boards = iss._parse_iss_block(payload, "boards", frozenset({"secid", "boardid"}))
    values = dict(zip(frame["name"].astype(str), frame["value"], strict=True))
    board_ids = set(
        boards.loc[boards["secid"].astype(str).eq(secid), "boardid"].astype(str)
    )
    required = ("SECID", "ASSETCODE", "LOTSIZE", "TYPE", "LSTTRADE")
    if any(values.get(name) in (None, "") for name in required):
        raise ValueError(f"contract description is incomplete: {secid}")
    if (
        str(values["SECID"]) != secid
        or str(values["ASSETCODE"]) != asset
        or str(values["TYPE"]) != "futures"
        or "RFUD" not in board_ids
    ):
        raise ValueError(f"contract identity drifted: {secid}")
    return {
        "secid": secid,
        "last_date": pd.Timestamp(values["LSTTRADE"]).date(),
        "lot_size": int(float(values["LOTSIZE"])),
    }


def _select_contract(
    series_payload: dict[str, Any],
    descriptions: dict[str, dict[str, Any]],
    asset: str,
    source_date: date,
    protocol: Protocol,
) -> tuple[dict[str, Any] | None, str | None]:
    spec = daily_source.AssetSpec.from_symbol(asset)
    series = iss.parse_futures_series_payload(series_payload, spec)
    if series.empty:
        return None, "no_active_series_metadata"
    series = series.loc[series["is_traded"].astype(bool)].copy()
    # Description calls are limited by series expiry metadata only; no quote enters selection.
    series_days = (series["expiration_date"] - pd.Timestamp(source_date)).dt.days
    series = series.loc[series_days.between(20, 100)]
    candidates: list[dict[str, Any]] = []
    minimum = int(
        protocol.payload["contract_selection"]["eligible_calendar_days_to_last_trade"][
            "minimum"
        ]
    )
    maximum = int(
        protocol.payload["contract_selection"]["eligible_calendar_days_to_last_trade"][
            "maximum"
        ]
    )
    expected_lot = int(protocol.payload["universe"]["required_futures_lot_size_shares"])
    lot_mismatch = False
    for secid in sorted(series["secid"].astype(str)):
        item = _description(descriptions[secid], secid, asset)
        days = (item["last_date"] - source_date).days
        if minimum <= days <= maximum:
            if item["lot_size"] != expected_lot:
                lot_mismatch = True
                continue
            candidates.append({**item, "days": days})
    if not candidates:
        reason = "eligible_contract_lot_size_mismatch" if lot_mismatch else "no_eligible_contract"
        return None, reason
    selected = min(candidates, key=lambda item: (item["last_date"], item["secid"]))
    return selected, None


def _quote_row(
    payload: dict[str, Any],
    *,
    source_date: date,
    stage: str,
    asset: str,
    kind: str,
    secid: str,
    selected: dict[str, Any] | None,
    retrieval: pd.Timestamp,
    access_mode: str,
) -> dict[str, Any]:
    frame = iss._parse_iss_block(
        payload,
        "marketdata",
        frozenset({"secid", "boardid", "bid", "offer"}),
    )
    expected_board = "TQBR" if kind == "spot" else "RFUD"
    rows = frame.loc[
        frame["secid"].astype(str).eq(secid)
        & frame["boardid"].astype(str).eq(expected_board)
    ]
    invalid: list[str] = []
    if len(rows) != 1:
        values: dict[str, Any] = {}
        invalid.append("quote_identity_missing_or_duplicate")
    else:
        values = rows.iloc[0].to_dict()
    bid = pd.to_numeric(pd.Series([values.get("bid")]), errors="coerce").iloc[0]
    offer = pd.to_numeric(pd.Series([values.get("offer")]), errors="coerce").iloc[0]
    clocks = {
        name: values.get(name)
        for name in ("systime", "updatetime", "seqnum")
        if values.get(name) not in (None, "") and pd.notna(values.get(name))
    }
    if pd.isna(bid) or pd.isna(offer) or float(bid) <= 0 or float(offer) <= 0:
        invalid.append("positive_two_sided_quote_missing")
    elif float(offer) <= float(bid):
        invalid.append("crossed_or_locked_quote")
    if not clocks:
        invalid.append("exchange_clock_missing")
    return {
        "source_date": source_date.isoformat(),
        "stage": stage,
        "logical_asset": asset,
        "venue_kind": kind,
        "secid": secid,
        "board_id": expected_board,
        "selected_contract_id": selected["secid"] if selected else pd.NA,
        "expiry_reference_date": selected["last_date"].isoformat() if selected else pd.NA,
        "days_to_expiry_reference": selected["days"] if selected else pd.NA,
        "lot_size_shares": selected["lot_size"] if selected else pd.NA,
        "bid": float(bid) if pd.notna(bid) else pd.NA,
        "offer": float(offer) if pd.notna(offer) else pd.NA,
        "exchange_systime": values.get("systime", pd.NA),
        "exchange_updatetime": values.get("updatetime", pd.NA),
        "exchange_seqnum": values.get("seqnum", pd.NA),
        "retrieved_at_utc": retrieval.isoformat(),
        "access_mode": access_mode,
        "valid": not invalid,
        "invalid_reason": "|".join(invalid) if invalid else pd.NA,
    }


def _sleep_row(
    *,
    source_date: date,
    stage: str,
    asset: str,
    reason: str,
    retrieval: pd.Timestamp,
    access_mode: str,
) -> dict[str, Any]:
    row = {column: pd.NA for column in OUTPUT_COLUMNS}
    row.update(
        {
            "source_date": source_date.isoformat(),
            "stage": stage,
            "logical_asset": asset,
            "venue_kind": "futures",
            "board_id": "RFUD",
            "retrieved_at_utc": retrieval.isoformat(),
            "access_mode": access_mode,
            "valid": False,
            "invalid_reason": reason,
        }
    )
    return row


def _forbidden_columns(frame: pd.DataFrame, protocol: Protocol) -> bool:
    fragments = tuple(str(item).lower() for item in protocol.payload["forbidden_outputs"])
    return any(any(fragment in str(column).lower() for fragment in fragments) for column in frame)


def _build_from_raw(
    raw: list[dict[str, Any]],
    protocol: Protocol,
    stage: str,
    source_date: date,
    retrieval: pd.Timestamp,
) -> tuple[pd.DataFrame, str]:
    by_key = {(item["kind"], item["logical_asset"], item.get("secid")): item for item in raw}
    access_mode = protocol.payload["official_sources"]["access_mode"]
    rows: list[dict[str, Any]] = []
    sleeping = False
    for asset in protocol.payload["universe"]["logical_assets"]:
        series_item = by_key[("series", asset, None)]
        series = iss.parse_futures_series_payload(
            series_item["payload"], daily_source.AssetSpec.from_symbol(asset)
        )
        if series.empty:
            pre_candidates = series
        else:
            series_days = (series["expiration_date"] - pd.Timestamp(source_date)).dt.days
            pre_candidates = series.loc[
                series["is_traded"].astype(bool) & series_days.between(20, 100)
            ]
        descriptions = {
            secid: by_key[("description", asset, secid)]["payload"]
            for secid in sorted(pre_candidates["secid"].astype(str))
        }
        selected, sleep_reason = _select_contract(
            series_item["payload"], descriptions, asset, source_date, protocol
        )
        spot = str(protocol.payload["universe"]["spot_secids"][asset])
        rows.append(
            _quote_row(
                by_key[("marketdata_spot", asset, spot)]["payload"],
                source_date=source_date,
                stage=stage,
                asset=asset,
                kind="spot",
                secid=spot,
                selected=selected,
                retrieval=retrieval,
                access_mode=access_mode,
            )
        )
        if selected is None:
            sleeping = True
            rows.append(
                _sleep_row(
                    source_date=source_date,
                    stage=stage,
                    asset=asset,
                    reason=str(sleep_reason),
                    retrieval=retrieval,
                    access_mode=access_mode,
                )
            )
        else:
            secid = str(selected["secid"])
            rows.append(
                _quote_row(
                    by_key[("marketdata_futures", asset, secid)]["payload"],
                    source_date=source_date,
                    stage=stage,
                    asset=asset,
                    kind="futures",
                    secid=secid,
                    selected=selected,
                    retrieval=retrieval,
                    access_mode=access_mode,
                )
            )
    frame = pd.DataFrame(rows, columns=OUTPUT_COLUMNS).sort_values(
        ["logical_asset", "venue_kind"], ignore_index=True
    )
    if _forbidden_columns(frame, protocol):
        raise ValueError("forward cash-carry source leaked a forbidden output column")
    if frame.duplicated(["logical_asset", "venue_kind"]).any() or len(frame) != 10:
        raise ValueError("forward cash-carry pair identity drifted")
    invalid_reasons = set(frame.loc[~frame["valid"], "invalid_reason"].dropna().astype(str))
    sleep_reasons = {"no_active_series_metadata", "no_eligible_contract"}
    if not bool(frame["valid"].all()):
        status = (
            "sleeping_no_eligible_contract"
            if sleeping and invalid_reasons <= sleep_reasons
            else "invalid"
        )
    else:
        status = "complete_valid"
    return frame, status


def collect(
    stage: str,
    output_root: Path | None = None,
    *,
    client: JsonClient | None = None,
    retrieved_at: str | datetime | pd.Timestamp | None = None,
) -> Path:
    protocol = load_protocol()
    source_date, retrieval = _source_context(protocol, stage, retrieved_at)
    root = (output_root or protocol.output_root).resolve()
    final = root / f"snapshot_{source_date:%Y%m%d}_{stage}"
    if final.exists():
        raise FileExistsError(f"duplicate forward cash-carry stage/date: {final}")
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=root))
    active = client or daily_source.shared.OfficialMoexClient()
    own_client = client is None
    raw: list[dict[str, Any]] = []
    try:
        for asset in protocol.payload["universe"]["logical_assets"]:
            series_url = _series_url(asset)
            series_payload = active.get_json(series_url)
            raw.append(
                {
                    "kind": "series",
                    "logical_asset": asset,
                    "url": series_url,
                    "payload": series_payload,
                }
            )
            series = iss.parse_futures_series_payload(
                series_payload, daily_source.AssetSpec.from_symbol(asset)
            )
            if series.empty:
                candidates = series
            else:
                series_days = (
                    series["expiration_date"] - pd.Timestamp(source_date)
                ).dt.days
                candidates = series.loc[
                    series["is_traded"].astype(bool) & series_days.between(20, 100)
                ]
            descriptions: dict[str, dict[str, Any]] = {}
            for secid in sorted(candidates["secid"].astype(str)):
                url = _description_url(secid)
                payload = active.get_json(url)
                descriptions[secid] = payload
                raw.append(
                    {
                        "kind": "description",
                        "logical_asset": asset,
                        "secid": secid,
                        "url": url,
                        "payload": payload,
                    }
                )
            selected, _ = _select_contract(
                series_payload, descriptions, asset, source_date, protocol
            )
            spot = str(protocol.payload["universe"]["spot_secids"][asset])
            spot_url = _market_url("spot", spot)
            raw.append(
                {
                    "kind": "marketdata_spot",
                    "logical_asset": asset,
                    "secid": spot,
                    "url": spot_url,
                    "payload": active.get_json(spot_url),
                }
            )
            if selected is not None:
                secid = str(selected["secid"])
                future_url = _market_url("futures", secid)
                raw.append(
                    {
                        "kind": "marketdata_futures",
                        "logical_asset": asset,
                        "secid": secid,
                        "url": future_url,
                        "payload": active.get_json(future_url),
                    }
                )
        frame, status = _build_from_raw(raw, protocol, stage, source_date, retrieval)
        raw_path = temporary / "official_moex_forward_responses.jsonl.gz"
        processed_path = temporary / "quotes.parquet"
        atomic_write_bytes(raw_path, _canonical_json_bytes(raw))
        daily_source._write_parquet(processed_path, frame)
        manifest = {
            "protocol_id": protocol.payload["protocol_id"],
            "protocol_sha256": protocol.config_sha256,
            "implementation_sha256": _sha(Path(__file__)),
            "source_date": source_date.isoformat(),
            "stage": stage,
            "retrieved_at_utc": retrieval.isoformat(),
            "status": status,
            "source_only": True,
            "contains_forbidden_derived_outputs": False,
            "live_trading_allowed": False,
            "counts": {
                "rows": len(frame),
                "valid_rows": int(frame["valid"].sum()),
                "invalid_rows": int((~frame["valid"]).sum()),
                "raw_responses": len(raw),
                "assets": int(frame["logical_asset"].nunique()),
            },
            "artifacts": {
                "quotes": daily_source._artifact(processed_path, len(frame)),
                "raw": daily_source._artifact(raw_path, len(raw)),
            },
            "limitations": protocol.payload["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active.close()  # type: ignore[attr-defined]
    checks = audit(final)
    write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("forward cash-carry snapshot audit failed")
    return final


def audit(snapshot: Path) -> dict[str, bool]:
    protocol = load_protocol()
    root = snapshot.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    source_date = date.fromisoformat(manifest["source_date"])
    retrieval = pd.Timestamp(manifest["retrieved_at_utc"])
    raw_path = root / manifest["artifacts"]["raw"]["file"]
    raw = daily_source._read_raw(raw_path)
    rebuilt, status = _build_from_raw(
        raw, protocol, str(manifest["stage"]), source_date, retrieval
    )
    quotes_path = root / manifest["artifacts"]["quotes"]["file"]
    stored = pd.read_parquet(quotes_path)
    try:
        stored_comparable = stored.astype(object).where(stored.notna(), None)
        rebuilt_comparable = rebuilt.astype(object).where(rebuilt.notna(), None)
        pd.testing.assert_frame_equal(
            stored_comparable,
            rebuilt_comparable,
            check_dtype=False,
        )
        replay_exact = True
    except AssertionError:
        replay_exact = False
    boundary = date.fromisoformat(protocol.payload["forward_boundary"]["earliest_source_date"])
    local_date = retrieval.tz_convert(MOSCOW_TZ).date()
    checks = {
        "manifest_sha_exact": (root / "manifest.sha256").read_text(
            encoding="utf-8-sig"
        ).split()[0]
        == _sha(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == protocol.config_sha256,
        "implementation_sha_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "source_only": manifest["source_only"] is True,
        "derived_outputs_absent": manifest["contains_forbidden_derived_outputs"] is False
        and not _forbidden_columns(stored, protocol),
        "live_forbidden": manifest["live_trading_allowed"] is False,
        "source_date_forward_exact": source_date >= boundary and source_date == local_date,
        "stage_exact": manifest["stage"] in STAGES,
        "status_exact": manifest["status"] == status,
        "quotes_sha_exact": _sha(quotes_path) == manifest["artifacts"]["quotes"]["sha256"],
        "raw_sha_exact": _sha(raw_path) == manifest["artifacts"]["raw"]["sha256"],
        "row_count_exact": len(stored) == int(manifest["counts"]["rows"]),
        "raw_count_exact": len(raw) == int(manifest["counts"]["raw_responses"]),
        "raw_replay_exact": replay_exact,
        "pair_identity_exact": len(stored) == 10
        and not stored.duplicated(["logical_asset", "venue_kind"]).any(),
    }
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        if args.stage is None:
            parser.error("--stage is required when collecting")
        print(collect(args.stage, args.output_root))


if __name__ == "__main__":
    main()
