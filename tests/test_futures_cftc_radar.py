"""Testy causal CFTC COT foundation bez seti, price, returns i holdout I/O."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.cftc_radar import (
    CFTC_AVAILABILITY_RULE,
    CFTC_CHANNEL_COMPONENTS,
    CFTC_DEVELOPMENT_RELEASE_SOURCE_URLS,
    CFTC_DISAGGREGATED_FUTURES_ONLY,
    CFTC_EXACT_RELEASE_REQUIRED_DATES,
    CFTC_MARKETS,
    CFTC_TFF_FUTURES_ONLY,
    assert_append_only_cftc_history,
    attach_cftc_availability,
    build_causal_cftc_asset_scores,
    build_causal_cftc_features,
    build_cftc_position_history,
    cftc_bulk_url,
    nominal_cftc_release_at,
    official_2025_shutdown_release_overrides,
    official_development_release_overrides,
    parse_cftc_archive,
    persist_cftc_snapshot,
)
from market_lab.futures.session_timing import legacy_forts_decision_calendar

FIXED_FETCHED_AT = datetime(2025, 12, 31, 18, 0, tzinfo=UTC)  # Audit clock fixture.
REPORT_DATES = (date(2024, 1, 2), date(2024, 1, 9))  # Dve official Tuesday dates.
DISAGG_HEADERS = (  # Minimal'nye documented static Disaggregated CSV headers.
    "Market_and_Exchange_Names",
    "As_of_Date_In_Form_YYMMDD",
    "As_of_Date_Form_YYYY-MM-DD",
    "CFTC_Contract_Market_Code",
    "Open_Interest_All",
    "Prod_Merc_Positions_Long_All",
    "Prod_Merc_Positions_Short_All",
    "Swap_Positions_Long_All",
    "Swap__Positions_Short_All",
    "M_Money_Positions_Long_All",
    "M_Money_Positions_Short_All",
    "Other_Rept_Positions_Long_All",
    "Other_Rept_Positions_Short_All",
    "FutOnly_or_Combined",
)
TFF_HEADERS = (  # Minimal'nye documented static TFF CSV headers.
    "Market_and_Exchange_Names",
    "As_of_Date_In_Form_YYMMDD",
    "Report_Date_as_MM_DD_YYYY",
    "CFTC_Contract_Market_Code",
    "Open_Interest_All",
    "Dealer_Positions_Long_All",
    "Dealer_Positions_Short_All",
    "Asset_Mgr_Positions_Long_All",
    "Asset_Mgr_Positions_Short_All",
    "Lev_Money_Positions_Long_All",
    "Lev_Money_Positions_Short_All",
    "Other_Rept_Positions_Long_All",
    "Other_Rept_Positions_Short_All",
    "FutOnly_or_Combined",
)


def _zip_csv(headers: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    """Stroit malyi official-shaped annual ZIP tol'ko v pamyati."""
    text_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(text_buffer, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows([{header: row.get(header, "") for header in headers} for row in rows])
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("annual.txt", text_buffer.getvalue().encode("utf-8"))
    return archive_buffer.getvalue()


def _date_fields(report_date: date) -> dict[str, str]:
    """Vozvrashchaet tri documented predstavleniya odnoi report date."""
    return {
        "As_of_Date_In_Form_YYMMDD": report_date.strftime("%y%m%d"),
        "As_of_Date_Form_YYYY-MM-DD": report_date.isoformat(),
        "Report_Date_as_MM_DD_YYYY": report_date.strftime("%m/%d/%Y"),
    }


def _disaggregated_rows() -> list[dict[str, object]]:
    """Stroit WTI/Brent category positions s izvestnymi net/OI."""
    rows: list[dict[str, object]] = []
    markets = (
        (
            "067651",
            "WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE",
            ((300, 100), (350, 100)),
        ),
        (
            "06765T",
            "BRENT LAST DAY - NEW YORK MERCANTILE EXCHANGE",
            ((200, 100), (240, 100)),
        ),
    )
    for code, name, managed_values in markets:
        for index, report_date in enumerate(REPORT_DATES):
            managed_long, managed_short = managed_values[index]
            rows.append(
                {
                    **_date_fields(report_date),
                    "Market_and_Exchange_Names": name,
                    "CFTC_Contract_Market_Code": code,
                    "Open_Interest_All": 1000,
                    "Prod_Merc_Positions_Long_All": 100,
                    "Prod_Merc_Positions_Short_All": 150,
                    "Swap_Positions_Long_All": 200,
                    "Swap__Positions_Short_All": 250,
                    "M_Money_Positions_Long_All": managed_long,
                    "M_Money_Positions_Short_All": managed_short,
                    "Other_Rept_Positions_Long_All": 50,
                    "Other_Rept_Positions_Short_All": 60,
                    "FutOnly_or_Combined": "FutOnly",
                }
            )
    return rows


def _tff_rows() -> list[dict[str, object]]:
    """Stroit DXY/ES/NQ category positions s izvestnymi net/OI."""
    rows: list[dict[str, object]] = []
    markets = (
        (
            "098662",
            "USD INDEX - ICE FUTURES U.S.",
            ((200, 100), (300, 100)),
        ),
        (
            "13874A",
            "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
            ((400, 200), (500, 200)),
        ),
        (
            "209742",
            "NASDAQ MINI - CHICAGO MERCANTILE EXCHANGE",
            ((500, 100), (300, 100)),
        ),
    )
    for code, name, leveraged_values in markets:
        for index, report_date in enumerate(REPORT_DATES):
            leveraged_long, leveraged_short = leveraged_values[index]
            rows.append(
                {
                    **_date_fields(report_date),
                    "Market_and_Exchange_Names": name,
                    "CFTC_Contract_Market_Code": code,
                    "Open_Interest_All": 1000,
                    "Dealer_Positions_Long_All": 100,
                    "Dealer_Positions_Short_All": 120,
                    "Asset_Mgr_Positions_Long_All": 300,
                    "Asset_Mgr_Positions_Short_All": 100,
                    "Lev_Money_Positions_Long_All": leveraged_long,
                    "Lev_Money_Positions_Short_All": leveraged_short,
                    "Other_Rept_Positions_Long_All": 60,
                    "Other_Rept_Positions_Short_All": 50,
                    "FutOnly_or_Combined": "FutOnly",
                }
            )
    return rows


def _parse_pair(
    disaggregated_rows: list[dict[str, object]] | None = None,
    tff_rows: list[dict[str, object]] | None = None,
) -> tuple[object, object]:
    """Parsit dva synthetic official annual arhiva s fixed provenance clock."""
    disaggregated = parse_cftc_archive(
        _zip_csv(DISAGG_HEADERS, disaggregated_rows or _disaggregated_rows()),
        year=2024,
        report_kind=CFTC_DISAGGREGATED_FUTURES_ONLY,
        fetched_at=FIXED_FETCHED_AT,
    )
    tff = parse_cftc_archive(
        _zip_csv(TFF_HEADERS, tff_rows or _tff_rows()),
        year=2024,
        report_kind=CFTC_TFF_FUTURES_ONLY,
        fetched_at=FIXED_FETCHED_AT,
    )
    return disaggregated, tff


def _history() -> pd.DataFrame:
    """Stroit polnuyu synthetic history iz pyati allowlisted markets."""
    disaggregated, tff = _parse_pair()
    return build_cftc_position_history([disaggregated.records, tff.records])


def _decision_calendar() -> pd.DatetimeIndex:
    """Stroit factual RFUD close decisions D 18:50 MSK v UTC."""
    return pd.DatetimeIndex(
        [
            "2024-01-05T15:50:00Z",
            "2024-01-08T15:50:00Z",
            "2024-01-09T15:50:00Z",
            "2024-01-12T15:50:00Z",
            "2024-01-15T15:50:00Z",
        ]
    )


def test_official_bulk_urls_and_strict_three_channel_allowlist() -> None:
    """Fiksiruet official URL pattern, five codes i rovno tri economic channel."""
    assert cftc_bulk_url(2018, CFTC_DISAGGREGATED_FUTURES_ONLY).endswith(
        "/fut_disagg_txt_2018.zip"
    )
    assert cftc_bulk_url(2025, CFTC_TFF_FUTURES_ONLY).endswith(
        "/fut_fin_txt_2025.zip"
    )
    assert {spec.contract_code for spec in CFTC_MARKETS} == {
        "067651",
        "06765T",
        "098662",
        "13874A",
        "209742",
    }
    assert set(CFTC_CHANNEL_COMPONENTS) == {
        "energy_positioning",
        "usd_positioning",
        "equity_risk_positioning",
    }


def test_parser_filters_unknown_and_preserves_hash_revision_provenance() -> None:
    """Ignoriruet neallowlisted bulk row i sohranyaet oba SHA/revision."""
    rows = _disaggregated_rows()
    rows.append(
        {
            **rows[0],
            "CFTC_Contract_Market_Code": "999999",
            "Market_and_Exchange_Names": "UNRELATED OFFICIAL BULK MARKET",
        }
    )
    archive_bytes = _zip_csv(DISAGG_HEADERS, rows)
    parsed = parse_cftc_archive(
        archive_bytes,
        year=2024,
        report_kind=CFTC_DISAGGREGATED_FUTURES_ONLY,
        fetched_at=FIXED_FETCHED_AT,
        http_etag='"fixture-etag"',
    )
    assert len(parsed.records) == 2 * 2 * 4
    assert set(parsed.records["contract_code"]) == {"067651", "06765T"}
    assert len(parsed.provenance.archive_sha256) == 64
    assert len(parsed.provenance.csv_sha256) == 64
    assert len(parsed.provenance.revision_id) == 64
    changed_rows = _disaggregated_rows()
    changed_rows[0]["M_Money_Positions_Long_All"] = 301
    revised = parse_cftc_archive(
        _zip_csv(DISAGG_HEADERS, changed_rows),
        year=2024,
        report_kind=CFTC_DISAGGREGATED_FUTURES_ONLY,
        fetched_at=FIXED_FETCHED_AT,
    )
    assert revised.provenance.revision_id != parsed.provenance.revision_id


def test_code_name_drift_missing_market_and_missing_field_fail_closed() -> None:
    """Otkazyvaetsya ot alias drift, nepolnogo allowlist i schema propuska."""
    drifted = _disaggregated_rows()
    drifted[0]["Market_and_Exchange_Names"] = "NEW WTI NAME - UNKNOWN EXCHANGE"
    with pytest.raises(ValueError, match="neallowlisted"):
        parse_cftc_archive(
            _zip_csv(DISAGG_HEADERS, drifted),
            year=2024,
            report_kind=CFTC_DISAGGREGATED_FUTURES_ONLY,
            fetched_at=FIXED_FETCHED_AT,
        )
    missing_brent = [
        row for row in _disaggregated_rows() if row["CFTC_Contract_Market_Code"] != "06765T"
    ]
    with pytest.raises(ValueError, match="allowlisted codes"):
        parse_cftc_archive(
            _zip_csv(DISAGG_HEADERS, missing_brent),
            year=2024,
            report_kind=CFTC_DISAGGREGATED_FUTURES_ONLY,
            fetched_at=FIXED_FETCHED_AT,
        )
    missing_header = tuple(
        header for header in DISAGG_HEADERS if header != "M_Money_Positions_Short_All"
    )
    with pytest.raises(ValueError, match="category kolonok"):
        parse_cftc_archive(
            _zip_csv(missing_header, _disaggregated_rows()),
            year=2024,
            report_kind=CFTC_DISAGGREGATED_FUTURES_ONLY,
            fetched_at=FIXED_FETCHED_AT,
        )
    combined = _disaggregated_rows()
    combined[0]["FutOnly_or_Combined"] = "Combined"
    with pytest.raises(ValueError, match="Futures Only"):
        parse_cftc_archive(
            _zip_csv(DISAGG_HEADERS, combined),
            year=2024,
            report_kind=CFTC_DISAGGREGATED_FUTURES_ONLY,
            fetched_at=FIXED_FETCHED_AT,
        )


def test_release_is_dst_aware_and_maps_to_factual_rfud_close_decision() -> None:
    """Dokazyvaet Friday release posle open i dostupnost' na Monday close decision."""
    assert nominal_cftc_release_at(date(2024, 1, 2)) == pd.Timestamp(
        "2024-01-05T20:30:00Z"
    )
    assert nominal_cftc_release_at(date(2024, 6, 4)) == pd.Timestamp(
        "2024-06-07T19:30:00Z"
    )
    available = attach_cftc_availability(_history(), _decision_calendar())
    first = available[available["report_date"] == pd.Timestamp("2024-01-02")]
    assert set(first["release_at"]) == {pd.Timestamp("2024-01-05T20:30:00Z")}
    assert set(first["available_at"]) == {pd.Timestamp("2024-01-08T15:50:00Z")}
    assert (first["available_at"] > first["report_date"].dt.tz_localize("UTC")).all()
    assert set(first["availability_rule"]) == {CFTC_AVAILABILITY_RULE}
    assert not first["release_timing_exact"].any()
    assert not first["holiday_or_timezone_ambiguous"].any()
    assert set(first["conservative_lag_sessions"]) == {0}
    conservative = attach_cftc_availability(
        _history(),
        _decision_calendar(),
        ambiguous_report_dates=[date(2024, 1, 2)],
    )
    first_conservative = conservative[
        conservative["report_date"] == pd.Timestamp("2024-01-02")
    ]
    assert set(first_conservative["available_at"]) == {
        pd.Timestamp("2024-01-09T15:50:00Z")
    }
    nonstandard = _history().copy()
    first_date = nonstandard["report_date"] == pd.Timestamp("2024-01-02")
    nonstandard.loc[first_date, "report_date"] = pd.Timestamp("2024-01-03")
    with pytest.raises(ValueError, match="exact release override"):
        attach_cftc_availability(nonstandard, _decision_calendar())
    overridden = attach_cftc_availability(
        nonstandard,
        _decision_calendar(),
        release_overrides={date(2024, 1, 3): "2024-01-05T20:30:00Z"},
    )
    exact = overridden[overridden["report_date"] == pd.Timestamp("2024-01-03")]
    assert exact["release_timing_exact"].all()
    assert set(exact["release_timestamp_source"]) == {"exact_official_override"}


def test_known_shutdown_dates_require_official_exact_release_override() -> None:
    """Blokiruet nominal Friday dlya backlog i prinimaet final official schedule."""
    assert len(official_2025_shutdown_release_overrides()) == 13
    assert date(2025, 9, 30) in CFTC_EXACT_RELEASE_REQUIRED_DATES
    history = _history()
    first_week = history[history["report_date"] == pd.Timestamp("2024-01-02")].copy()
    first_week["report_date"] = pd.Timestamp("2025-09-30")
    decisions = pd.DatetimeIndex(
        ["2025-11-19T15:50:00Z", "2025-11-20T15:50:00Z"]
    )
    with pytest.raises(ValueError, match="exact official overrides"):
        attach_cftc_availability(first_week, decisions)
    available = attach_cftc_availability(
        first_week,
        decisions,
        release_overrides={
            date(2025, 9, 30): official_2025_shutdown_release_overrides()[
                date(2025, 9, 30)
            ]
        },
    )
    assert set(available["release_at"]) == {pd.Timestamp("2025-11-19T20:30:00Z")}
    assert set(available["available_at"]) == {pd.Timestamp("2025-11-20T15:50:00Z")}
    assert set(available["release_source_url"]) == {
        CFTC_DEVELOPMENT_RELEASE_SOURCE_URLS[date(2025, 9, 30)]
    }


def test_all_frozen_development_overrides_have_exact_official_provenance() -> None:
    """Fiksiruet polnuyu kartu special dates, timestamps i per-date official URL."""
    overrides = official_development_release_overrides()
    assert set(overrides) == CFTC_EXACT_RELEASE_REQUIRED_DATES
    assert set(CFTC_DEVELOPMENT_RELEASE_SOURCE_URLS) == CFTC_EXACT_RELEASE_REQUIRED_DATES
    assert len(overrides) == 34
    assert overrides[date(2018, 12, 24)] == pd.Timestamp("2019-02-01T20:30:00Z")
    assert overrides[date(2019, 2, 26)] == pd.Timestamp("2019-03-05T20:30:00Z")
    assert overrides[date(2023, 2, 14)] == pd.Timestamp("2023-03-08T20:30:00Z")
    assert overrides[date(2023, 7, 3)] == pd.Timestamp("2023-07-07T19:30:00Z")
    assert overrides[date(2025, 1, 7)] == pd.Timestamp("2025-01-13T20:30:00Z")
    assert all(
        url.startswith("https://www.cftc.gov/")
        for url in CFTC_DEVELOPMENT_RELEASE_SOURCE_URLS.values()
    )


def test_rfud_friday_release_enters_monday_decision_and_tuesday_trade_open() -> None:
    """Dokazyvaet release -> strogo pozdnee close decision -> next factual open."""
    timing = legacy_forts_decision_calendar(
        [date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9)]
    )
    history = _history()
    first_week = history[history["report_date"] == pd.Timestamp("2024-01-02")]
    available = attach_cftc_availability(first_week, timing["decision_at"])
    assert set(available["release_at"]) == {pd.Timestamp("2024-01-05T20:30:00Z")}
    assert set(available["available_at"]) == {pd.Timestamp("2024-01-08T15:50:00Z")}
    monday = timing[timing["trade_date"] == pd.Timestamp("2024-01-08")].iloc[0]
    assert monday["decision_at"] == pd.Timestamp("2024-01-08T15:50:00Z")
    assert monday["effective_date"] == pd.Timestamp("2024-01-09")
    assert monday["conservative_open_at"] == pd.Timestamp("2024-01-08T16:00:00Z")
    assert monday["decision_at"] < monday["conservative_open_at"]


def test_category_net_oi_changes_and_three_causal_channel_features() -> None:
    """Proveryaet normalized net/OI, change i otsutstvie Friday same-decision leak."""
    history = _history()
    wti = history[
        (history["market_id"] == "wti") & (history["category"] == "managed_money")
    ]
    assert wti["net_share_oi"].tolist() == pytest.approx([0.20, 0.25])
    assert np.isnan(wti.iloc[0]["net_share_oi_change"])
    assert wti.iloc[1]["net_share_oi_change"] == pytest.approx(0.05)
    features = build_causal_cftc_features(history, _decision_calendar())
    assert np.isnan(features.iloc[0]["cftc_energy_positioning_net_oi"])
    assert features.iloc[1]["cftc_energy_positioning_net_oi"] == pytest.approx(0.15)
    assert np.isnan(features.iloc[3]["cftc_energy_positioning_change"])
    assert features.iloc[4]["cftc_energy_positioning_net_oi"] == pytest.approx(0.195)
    assert features.iloc[4]["cftc_energy_positioning_change"] == pytest.approx(0.045)
    assert features.iloc[4]["cftc_usd_positioning_net_oi"] == pytest.approx(0.20)
    assert features.iloc[4]["cftc_equity_risk_positioning_net_oi"] == pytest.approx(0.25)
    assert features.iloc[4]["cftc_equity_risk_positioning_change"] == pytest.approx(-0.05)


def test_future_mutation_and_partial_channel_cannot_change_past_or_mix_weeks() -> None:
    """Mutaciya budushchego ne menyaet past, a partial week ne smeshivaetsya s old."""
    history = _history()
    decisions = _decision_calendar()[:2]
    baseline = build_causal_cftc_features(history, decisions)
    mutated = history.copy()
    future_mask = mutated["report_date"] == pd.Timestamp("2024-01-09")
    mutated.loc[future_mask, "long_positions"] *= 100
    mutated = build_cftc_position_history(mutated)
    changed = build_causal_cftc_features(mutated, decisions)
    pd.testing.assert_frame_equal(baseline, changed)
    pd.testing.assert_frame_equal(
        build_causal_cftc_asset_scores(baseline),
        build_causal_cftc_asset_scores(changed),
    )
    without_second_brent = history[
        ~(
            (history["market_id"] == "brent")
            & (history["report_date"] == pd.Timestamp("2024-01-09"))
        )
    ]
    partial = build_causal_cftc_features(without_second_brent, _decision_calendar())
    assert np.isnan(partial.iloc[4]["cftc_energy_positioning_net_oi"])


def test_asset_scores_sleep_until_changes_exist_and_remain_bounded() -> None:
    """Stroit polnyi decision-asset product, sleeping NaN i bounded fixed router."""
    features = build_causal_cftc_features(_history(), _decision_calendar())
    scores = build_causal_cftc_asset_scores(features)
    assert len(scores) == len(features) * 4
    assert set(scores["asset_symbol"]) == {"SI", "RI", "BR", "MIX"}
    sleeping = scores[scores["decision_at"] < pd.Timestamp("2024-01-15T15:50:00Z")]
    assert sleeping["score"].isna().all()
    assert set(sleeping["score_status"]) == {"sleeping_missing_channel"}
    live = scores[scores["decision_at"] == pd.Timestamp("2024-01-15T15:50:00Z")]
    assert live["score"].notna().all()
    assert live["score"].between(-1.0, 1.0).all()
    assert set(live["score_status"]) == {"available"}
    assert live["score_formula"].str.startswith("clip(").all()
    assert set(live["channel_signal_formula"]) == {"tanh(2*net_oi+4*change)"}
    extreme = features.iloc[[-1]].copy()
    for channel in CFTC_CHANNEL_COMPONENTS:
        extreme[f"cftc_{channel}_net_oi"] = 100.0
        extreme[f"cftc_{channel}_change"] = 100.0
    extreme_scores = build_causal_cftc_asset_scores(extreme)
    assert extreme_scores["score"].between(-1.0, 1.0).all()
    broken = features.iloc[[-1]].copy()
    broken["cftc_energy_positioning_available_at"] = pd.Timestamp(
        "2025-01-01T00:00:00Z"
    )
    broken["decision_at"] = pd.Timestamp("2024-01-15T15:50:00Z")
    with pytest.raises(ValueError, match="as-of"):
        build_causal_cftc_asset_scores(broken)


def test_append_only_accepts_future_and_rejects_rewrite_or_historical_insert() -> None:
    """Razreshaet strogo future append i otklonyaet rewrite i backfill."""
    full = _history()
    existing = full[full["report_date"] == pd.Timestamp("2024-01-02")]
    assert_append_only_cftc_history(existing, full)
    rewritten = full.copy()
    rewritten.loc[rewritten.index[0], "long_positions"] += 1
    with pytest.raises(ValueError, match="izmenil"):
        assert_append_only_cftc_history(existing, rewritten)
    historical_insert = pd.concat(
        [
            full,
            full.iloc[[0]].assign(report_date=pd.Timestamp("2024-01-03")),
        ],
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="proshloe"):
        assert_append_only_cftc_history(full, historical_insert)


def test_holdout_naive_calendar_duplicates_and_missing_values_fail_closed() -> None:
    """Blokiruet 2026, naive/duplicate decision i propushchennye factual counts."""
    with pytest.raises(ValueError, match="holdout"):
        cftc_bulk_url(2026, CFTC_TFF_FUTURES_ONLY)
    history = _history()
    with pytest.raises(ValueError, match="timezone-aware"):
        attach_cftc_availability(history, ["2024-01-08T07:00:00"])
    with pytest.raises(ValueError, match="unique"):
        attach_cftc_availability(
            history,
            ["2024-01-08T07:00:00Z", "2024-01-08T07:00:00Z"],
        )
    with pytest.raises(ValueError, match="holdout"):
        attach_cftc_availability(history, ["2026-01-05T07:00:00Z"])
    missing = history.copy()
    missing.loc[missing.index[0], "long_positions"] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        build_cftc_position_history(missing)


def test_atomic_snapshot_preserves_raw_csv_hashes_and_never_overwrites(tmp_path: Path) -> None:
    """Proveryaet staged rename, raw bytes, Parquet, manifest i append-only snapshot id."""
    disaggregated, tff = _parse_pair()
    result = persist_cftc_snapshot(
        tmp_path,
        "cftc-fixture-v1",
        [disaggregated, tff],
        created_at=FIXED_FETCHED_AT,
    )
    assert result.rows == 40
    assert result.processed_path.exists()
    assert len(pd.read_parquet(result.processed_path)) == 40
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8-sig"))
    assert manifest["append_only"] is True
    assert manifest["protected_from"] == "2026-01-01"
    assert {item["year"] for item in manifest["archives"]} == {2024}
    for archive, item in zip(
        sorted(
            [disaggregated, tff],
            key=lambda value: (value.provenance.year, value.provenance.report_kind),
        ),
        manifest["archives"],
        strict=True,
    ):
        assert (result.snapshot_path / item["raw_zip_path"]).read_bytes() == (
            archive.archive_content
        )
        assert (result.snapshot_path / item["raw_csv_path"]).read_bytes() == archive.csv_content
        assert item["archive_sha256"] == archive.provenance.archive_sha256
        assert item["csv_sha256"] == archive.provenance.csv_sha256
    manifest_before = result.manifest_path.read_bytes()
    with pytest.raises(FileExistsError, match="uzhe sushchestvuet"):
        persist_cftc_snapshot(
            tmp_path,
            "cftc-fixture-v1",
            [disaggregated, tff],
            created_at=FIXED_FETCHED_AT,
        )
    assert result.manifest_path.read_bytes() == manifest_before
