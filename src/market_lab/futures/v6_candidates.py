"""Causal'naya sborka zapechatannyh futures-v6 candidate scores."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from market_lab.futures.cftc_radar import (
    build_causal_cftc_asset_scores,
    build_causal_cftc_features,
)
from market_lab.futures.info_radar import build_causal_cbr_features
from market_lab.futures.information_fusion import (
    CausalInformationFusionConfig,
    build_macro_conditioned_targets,
)
from market_lab.futures.moe import CausalMoEConfig, build_causal_moe_targets
from market_lab.futures.portfolio_construction import build_causal_portfolio_targets
from market_lab.futures.session_timing import legacy_forts_decision_calendar
from market_lab.futures.specialist_router import (
    SpecialistRouterConfig,
    build_causal_specialist_targets,
)

V6_CANDIDATE_IDS: Final[tuple[str, ...]] = (  # Zapechatannyi poryadok kandidatov.
    "base_moe",
    "macro_overlay",
    "macro_confirmation",
    "specialist_router",
)
V6_ASSETS: Final[tuple[str, ...]] = (  # Polnyi logical futures snapshot.
    "SI",
    "RI",
    "BR",
    "MIX",
)
V6_CBR_SERIES: Final[frozenset[str]] = frozenset(  # Obyazatel'nye CBR istochniki.
    {"ruonia", "key_rate", "usd_rub_official"}
)
V6_CANDIDATE_VERSION: Final[str] = (  # Audit-versiya sborki bez podbora po PnL.
    "futures-v6-causal-candidates-v1"
)
V6_SCORE_TOLERANCE: Final[float] = 1e-12  # Dopusk tol'ko dlya float-granic.
V6_CALENDAR_COLUMNS: Final[tuple[str, ...]] = (  # Exact legacy timing proof.
    "trade_date",
    "decision_at",
    "effective_date",
    "conservative_open_at",
    "timing_regime",
)
V6_SCORE_COLUMNS: Final[tuple[str, ...]] = (  # Stabil'naya universal'naya skhema.
    "candidate_id",
    "decision_date",
    "decision_at",
    "effective_date",
    "asset",
    "candidate_score",
    "provenance",
)


@dataclass(frozen=True, slots=True)
class CausalV6CandidateBundle:
    """Hranit candidate scores i vse causal'nye promezhutochnye tablicy."""

    candidate_scores: pd.DataFrame
    base_targets: pd.DataFrame
    cbr_features: pd.DataFrame
    macro_targets: pd.DataFrame
    cftc_asset_scores: pd.DataFrame
    router_targets: pd.DataFrame
    decision_calendar: pd.DataFrame


def _asset_code(value: object) -> str:
    """Privodit RTS alias i registr k chetyrem logical asset."""
    normalized = str(value).strip().upper()
    return "RI" if normalized == "RTS" else normalized


def _naive_date(values: pd.Series, label: str) -> pd.Series:
    """Normalizuet session date bez sdviga factual kalendarnogo dnya."""
    parsed = pd.to_datetime(values, errors="raise")
    if parsed.isna().any():
        raise ValueError(f"{label} soderzhit propusk daty")
    if parsed.dt.tz is not None:
        parsed = parsed.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    return parsed.dt.normalize()


def _normalize_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Trebuet po odnoi stroke SI/RI/BR/MIX na kazhduyu factual sessiyu."""
    required = {"trade_date", "asset_code", "open"}
    if missing := required - set(panel.columns):
        raise ValueError(f"Development panel ne soderzhit kolonok: {sorted(missing)}")
    frame = panel.copy()
    frame["trade_date"] = _naive_date(frame["trade_date"], "development_panel")
    frame["asset_code"] = frame["asset_code"].map(_asset_code)
    unknown = sorted(set(frame["asset_code"]) - set(V6_ASSETS))
    if unknown:
        raise ValueError(f"Development panel soderzhit neizvestnye assets: {unknown}")
    if frame.duplicated(["trade_date", "asset_code"]).any():
        raise ValueError("Development panel soderzhit duplicate date/asset")
    expected = frozenset(V6_ASSETS)
    for trade_date, snapshot in frame.groupby("trade_date", sort=True):
        if frozenset(snapshot["asset_code"]) != expected:
            raise ValueError(f"Nepolnyi development snapshot na {trade_date.date()}")
    dates = pd.DatetimeIndex(frame["trade_date"].drop_duplicates().sort_values())
    if len(dates) < 2:
        raise ValueError("Development panel trebuet minimum dve factual sessii")
    return frame.sort_values(["trade_date", "asset_code"], kind="mergesort").reset_index(
        drop=True
    )


def _normalize_calendar(
    calendar: pd.DataFrame,
    panel_dates: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Sveriaet peredannyi calendar s exact legacy mapping iz factual sessii."""
    if missing := set(V6_CALENDAR_COLUMNS) - set(calendar.columns):
        raise ValueError(f"Decision calendar ne soderzhit kolonok: {sorted(missing)}")
    frame = calendar.loc[:, V6_CALENDAR_COLUMNS].copy()
    frame["trade_date"] = _naive_date(frame["trade_date"], "decision_calendar")
    frame["effective_date"] = _naive_date(frame["effective_date"], "decision_calendar")
    frame["decision_at"] = pd.to_datetime(frame["decision_at"], errors="raise", utc=True)
    frame["conservative_open_at"] = pd.to_datetime(
        frame["conservative_open_at"], errors="raise", utc=True
    )
    frame["timing_regime"] = frame["timing_regime"].astype("string")
    if frame.duplicated("trade_date").any() or frame.duplicated("decision_at").any():
        raise ValueError("Decision calendar soderzhit duplicate")
    frame = frame.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
    expected = legacy_forts_decision_calendar(panel_dates)
    expected = expected.loc[:, V6_CALENDAR_COLUMNS].copy()
    expected["timing_regime"] = expected["timing_regime"].astype("string")
    try:
        pd.testing.assert_frame_equal(frame, expected, check_exact=True)
    except AssertionError as error:
        raise ValueError("Decision calendar ne sovpadaet s exact legacy mapping") from error
    if not (frame["decision_at"] < frame["conservative_open_at"]).all():
        raise ValueError("Decision timestamp ne predshestvuet factual next-open")
    return frame


def _normalize_cbr_observations(cbr: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet tri official CBR ryada i ih odnoznachnye publication rows."""
    required = {"series_id", "observation_date", "available_at", "value"}
    if missing := required - set(cbr.columns):
        raise ValueError(f"CBR observations ne soderzhat kolonok: {sorted(missing)}")
    frame = cbr.copy()
    frame["series_id"] = frame["series_id"].astype("string").str.strip().str.lower()
    absent = sorted(V6_CBR_SERIES - set(frame["series_id"]))
    if absent:
        raise ValueError(f"CBR observations ne soderzhat ryady: {absent}")
    frame["observation_date"] = _naive_date(frame["observation_date"], "CBR")
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="raise").astype(float)
    if (~np.isfinite(frame["value"])).any():
        raise ValueError("CBR observation value dolzhen byt' konechnym")
    if frame.duplicated(["series_id", "observation_date", "available_at"]).any():
        raise ValueError("CBR observations soderzhat duplicate")
    return frame.sort_values(["series_id", "available_at"], kind="mergesort").reset_index(
        drop=True
    )


def _normalize_prebuilt_cftc(scores: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet output official CFTC asset router i ego causal provenance."""
    asset_column = "asset_symbol" if "asset_symbol" in scores else "asset"
    score_column = "score" if "score" in scores else "cftc_score"
    required = {"decision_at", asset_column, score_column}
    if missing := required - set(scores.columns):
        raise ValueError(f"Prebuilt CFTC scores ne soderzhat kolonok: {sorted(missing)}")
    frame = scores.copy()
    frame["decision_at"] = pd.to_datetime(frame["decision_at"], errors="raise", utc=True)
    frame["asset_symbol"] = frame[asset_column].map(_asset_code)
    unknown = sorted(set(frame["asset_symbol"]) - set(V6_ASSETS))
    if unknown:
        raise ValueError(f"Prebuilt CFTC scores soderzhat neizvestnye assets: {unknown}")
    frame["score"] = pd.to_numeric(frame[score_column], errors="coerce").astype(float)
    if np.isinf(frame["score"].to_numpy()).any():
        raise ValueError("Prebuilt CFTC score ne mozhet byt' beskonechnym")
    outside = frame["score"].notna() & (
        frame["score"].abs() > 1.0 + V6_SCORE_TOLERANCE
    )
    if outside.any():
        raise ValueError("Prebuilt CFTC score vyshel iz [-1, 1]")
    frame["score"] = frame["score"].clip(-1.0, 1.0)
    if frame.duplicated(["decision_at", "asset_symbol"]).any():
        raise ValueError("Prebuilt CFTC scores soderzhat duplicate")
    for column in [name for name in frame if name.endswith("available_at")]:
        available_at = pd.to_datetime(frame[column], errors="coerce", utc=True)
        future = frame["score"].notna() & available_at.notna() & (
            available_at > frame["decision_at"]
        )
        if future.any():
            raise ValueError(f"Prebuilt CFTC ispol'zuet budushchii timestamp: {column}")
        frame[column] = available_at
    return frame.sort_values(["decision_at", "asset_symbol"], kind="mergesort").reset_index(
        drop=True
    )


def _dense_cftc_scores(
    decision_calendar: pd.DataFrame,
    scores: pd.DataFrame | None,
) -> pd.DataFrame:
    """Stroit polnyi decision/asset grid, gde otsutstvuyushchii CFTC spit v NaN."""
    grid = pd.MultiIndex.from_product(
        [decision_calendar["decision_at"], V6_ASSETS],
        names=["decision_at", "asset_symbol"],
    ).to_frame(index=False)
    if scores is None or scores.empty:
        grid["score"] = np.nan
        grid["score_status"] = "sleeping_missing_source"
        return grid
    normalized = _normalize_prebuilt_cftc(scores)
    selected = normalized.loc[
        normalized["decision_at"].isin(decision_calendar["decision_at"])
    ].copy()
    dense = grid.merge(
        selected,
        on=["decision_at", "asset_symbol"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_source"),
    )
    if "score_status" not in dense:
        dense["score_status"] = np.where(
            dense["score"].notna(), "available", "sleeping_missing_source"
        )
    else:
        dense["score_status"] = dense["score_status"].fillna(
            "sleeping_missing_source"
        )
    return dense.sort_values(["decision_at", "asset_symbol"], kind="mergesort").reset_index(
        drop=True
    )


def _cftc_scores_from_inputs(
    decision_calendar: pd.DataFrame,
    cftc_history: pd.DataFrame | None,
    cftc_asset_scores: pd.DataFrame | None,
    release_overrides: Mapping[object, object] | None,
    ambiguous_report_dates: Iterable[object],
) -> pd.DataFrame:
    """Vyberaet odin CFTC vhod ili yavno ostavlyaet specialist sleeping."""
    if cftc_history is not None and cftc_asset_scores is not None:
        raise ValueError("Nuzhno peredat' tol'ko odin iz CFTC history ili asset scores")
    source_scores = cftc_asset_scores
    if cftc_history is not None and not cftc_history.empty:
        features = build_causal_cftc_features(
            cftc_history,
            decision_calendar["decision_at"],
            release_overrides=release_overrides,
            ambiguous_report_dates=ambiguous_report_dates,
        )
        source_scores = build_causal_cftc_asset_scores(features)
    return _dense_cftc_scores(decision_calendar, source_scores)


def _validate_causal_feature_times(features: pd.DataFrame) -> None:
    """Zapreshchaet information availability posle sootvetstvuyushchego decision."""
    if "decision_at" not in features:
        raise ValueError("Feature frame ne soderzhit decision_at")
    decisions = pd.to_datetime(features["decision_at"], errors="raise", utc=True)
    for column in [name for name in features if name.endswith("available_at")]:
        available = pd.to_datetime(features[column], errors="coerce", utc=True)
        if (available.notna() & (available > decisions)).any():
            raise ValueError(f"Feature frame ispol'zuet budushchii timestamp: {column}")


def _router_input(
    panel: pd.DataFrame,
    base_targets: pd.DataFrame,
    macro_targets: pd.DataFrame,
    cftc_scores: pd.DataFrame,
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    """Sobiraet factual open i pyat' specialist scores bez synthetic wake-up."""
    cbr = macro_targets.loc[
        macro_targets["candidate_id"].eq("base_moe"),
        ["trade_date", "asset_code", "information_score"],
    ].rename(columns={"information_score": "cbr_macro_score"})
    cftc = cftc_scores.rename(
        columns={"asset_symbol": "asset_code", "score": "cftc_score"}
    ).merge(
        calendar[["trade_date", "decision_at"]],
        on="decision_at",
        how="left",
        validate="many_to_one",
    )[["trade_date", "asset_code", "cftc_score"]]
    routed = base_targets.merge(
        panel[["trade_date", "asset_code", "open"]],
        on=["trade_date", "asset_code"],
        how="left",
        validate="one_to_one",
    )
    routed = routed.merge(
        cbr,
        on=["trade_date", "asset_code"],
        how="left",
        validate="one_to_one",
    ).merge(
        cftc,
        on=["trade_date", "asset_code"],
        how="left",
        validate="one_to_one",
    )
    routed["filings_score"] = np.nan
    routed["news_score"] = np.nan
    if routed["cbr_macro_score"].isna().any():
        raise ValueError("Obyazatel'nyi pure CBR score okazalsya sleeping")
    return routed


def _json_scalar(value: object) -> object:
    """Privodit pandas/numpy scalar k stabil'nomu JSON ili yavnomu null."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value)
    return str(value)


def _score_provenance(
    candidate_id: str,
    macro_row: pd.Series | None,
    router_row: pd.Series | None,
    cftc_row: pd.Series,
    calendar_row: pd.Series,
) -> str:
    """Serializuet dostatochnyi per-row proof bez global future metadata."""
    payload: dict[str, object] = {
        "version": V6_CANDIDATE_VERSION,
        "candidate_id": candidate_id,
        "decision_at": _json_scalar(calendar_row["decision_at"]),
        "effective_date": _json_scalar(calendar_row["effective_date"]),
        "timing_regime": _json_scalar(calendar_row["timing_regime"]),
        "target_session_offset": 1,
        "cftc_status": _json_scalar(cftc_row["score_status"]),
        "filings_status": "sleeping_no_authorized_historical_corpus",
        "news_status": "sleeping_source_disabled",
        "uses_future_prices_or_labels": False,
    }
    if macro_row is not None:
        for column in (
            "information_source_mode",
            "information_score",
            "information_activation",
            "gross_scale",
            "shock_currency_stress",
            "shock_risk_off",
            "shock_energy_supply",
            "shock_monetary_tightening",
        ):
            payload[column] = _json_scalar(macro_row[column])
    if router_row is not None:
        for specialist in ("base", "cbr_macro", "cftc", "filings", "news"):
            for kind in ("score", "available", "weight"):
                column = f"router_{kind}_{specialist}"
                payload[column] = _json_scalar(router_row[column])
        payload["router_observed_through"] = _json_scalar(
            router_row["router_observed_through"]
        )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _candidate_score_frame(
    macro_targets: pd.DataFrame,
    router_targets: pd.DataFrame,
    cftc_scores: pd.DataFrame,
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    """Prevrashchaet tri macro i odin router output v odnu exact score skhemu."""
    calendar_by_date = calendar.set_index("trade_date")
    cftc_by_key = cftc_scores.merge(
        calendar[["trade_date", "decision_at"]],
        on="decision_at",
        how="left",
        validate="many_to_one",
    ).set_index(["trade_date", "asset_symbol"])
    rows: list[dict[str, object]] = []
    for candidate_id in V6_CANDIDATE_IDS:
        if candidate_id == "specialist_router":
            source = router_targets
            score_column = "router_target_score"
        else:
            source = macro_targets.loc[macro_targets["candidate_id"].eq(candidate_id)]
            score_column = "candidate_score"
        for _, source_row in source.iterrows():
            trade_date = pd.Timestamp(source_row["trade_date"])
            asset = str(source_row["asset_code"])
            calendar_row = calendar_by_date.loc[trade_date]
            cftc_row = cftc_by_key.loc[(trade_date, asset)]
            score = float(source_row[score_column])
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "decision_date": trade_date,
                    "decision_at": calendar_row["decision_at"],
                    "effective_date": calendar_row["effective_date"],
                    "asset": asset,
                    "candidate_score": score,
                    "provenance": _score_provenance(
                        candidate_id,
                        None if candidate_id == "specialist_router" else source_row,
                        source_row if candidate_id == "specialist_router" else None,
                        cftc_row,
                        calendar_row,
                    ),
                }
            )
    output = pd.DataFrame(rows, columns=V6_SCORE_COLUMNS)
    output["_candidate_order"] = output["candidate_id"].map(
        {name: index for index, name in enumerate(V6_CANDIDATE_IDS)}
    )
    output = output.sort_values(
        ["_candidate_order", "decision_date", "asset"], kind="mergesort"
    ).drop(columns="_candidate_order").reset_index(drop=True)
    _validate_candidate_scores(output)
    return output


def _validate_candidate_scores(scores: pd.DataFrame) -> None:
    """Trebuet exact kandidaty, polnye snapshots i bounded finite scores."""
    if tuple(scores["candidate_id"].drop_duplicates()) != V6_CANDIDATE_IDS:
        raise ValueError("Candidate frame ne sovpadaet s zapechatannym spiskom")
    if scores.duplicated(["candidate_id", "decision_date", "asset"]).any():
        raise ValueError("Candidate frame soderzhit duplicate")
    values = pd.to_numeric(scores["candidate_score"], errors="coerce")
    if values.isna().any() or (~np.isfinite(values)).any():
        raise ValueError("Candidate score dolzhen byt' konechnym")
    if (values.abs() > 1.0 + V6_SCORE_TOLERANCE).any():
        raise ValueError("Candidate score vyshel iz [-1, 1]")
    expected_assets = frozenset(V6_ASSETS)
    grouped = scores.groupby(["candidate_id", "decision_date"], sort=False)
    for key, snapshot in grouped:
        if frozenset(snapshot["asset"]) != expected_assets:
            raise ValueError(f"Nepolnyi candidate snapshot: {key}")
    counts = scores.groupby("candidate_id")["decision_date"].nunique()
    if counts.nunique() != 1:
        raise ValueError("Kandidaty pokryvayut raznye decision dates")


def build_causal_v6_candidates(
    development_panel: pd.DataFrame,
    cbr_observations: pd.DataFrame,
    decision_calendar: pd.DataFrame,
    *,
    cftc_history: pd.DataFrame | None = None,
    cftc_asset_scores: pd.DataFrame | None = None,
    cftc_release_overrides: Mapping[object, object] | None = None,
    cftc_ambiguous_report_dates: Iterable[object] = (),
    moe_config: CausalMoEConfig | None = None,
    fusion_config: CausalInformationFusionConfig | None = None,
    router_config: SpecialistRouterConfig | None = None,
) -> CausalV6CandidateBundle:
    """Sobiraet chetyre kandidata tol'ko iz information na close resheniya D."""
    panel = _normalize_panel(development_panel)
    panel_dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    calendar = _normalize_calendar(decision_calendar, panel_dates)
    cbr = _normalize_cbr_observations(cbr_observations)
    base_all = build_causal_moe_targets(panel, moe_config)
    base = base_all.loc[base_all["trade_date"].isin(calendar["trade_date"])].copy()
    cbr_features = build_causal_cbr_features(cbr, calendar["decision_at"])
    _validate_causal_feature_times(cbr_features)
    macro = build_macro_conditioned_targets(
        base,
        cbr_features,
        calendar,
        fusion_config,
    )
    cftc = _cftc_scores_from_inputs(
        calendar,
        cftc_history,
        cftc_asset_scores,
        cftc_release_overrides,
        cftc_ambiguous_report_dates,
    )
    _validate_causal_feature_times(cftc)
    router_panel = _router_input(panel, base, macro, cftc, calendar)
    router = build_causal_specialist_targets(router_panel, router_config)
    scores = _candidate_score_frame(macro, router, cftc, calendar)
    if scores["decision_date"].max() != panel_dates[-2]:
        raise AssertionError("Poslednyaya sessiya bez next-open dolzhna byt' isklyuchena")
    if scores["decision_date"].isin([panel_dates[-1]]).any():
        raise AssertionError("Candidate frame soderzhit sessiyu bez factual next-open")
    return CausalV6CandidateBundle(
        candidate_scores=scores,
        base_targets=base.reset_index(drop=True),
        cbr_features=cbr_features.reset_index(drop=True),
        macro_targets=macro.reset_index(drop=True),
        cftc_asset_scores=cftc.reset_index(drop=True),
        router_targets=router.reset_index(drop=True),
        decision_calendar=calendar.reset_index(drop=True),
    )


def build_v6_candidate_portfolio_targets(
    market_panel: pd.DataFrame,
    candidates: CausalV6CandidateBundle | pd.DataFrame,
) -> pd.DataFrame:
    """Stroit odinakovo risk-scaled portfolio target dlya kazhdogo kandidata."""
    scores = (
        candidates.candidate_scores.copy()
        if isinstance(candidates, CausalV6CandidateBundle)
        else candidates.copy()
    )
    required = {"candidate_id", "decision_date", "asset", "candidate_score"}
    if missing := required - set(scores.columns):
        raise ValueError(f"Candidate scores ne soderzhat kolonok: {sorted(missing)}")
    _validate_candidate_scores(scores)
    outputs: list[pd.DataFrame] = []
    for candidate_id in V6_CANDIDATE_IDS:
        selected = scores.loc[
            scores["candidate_id"].eq(candidate_id),
            ["decision_date", "asset", "candidate_score"],
        ]
        portfolio = build_causal_portfolio_targets(market_panel, selected)
        portfolio.insert(0, "candidate_id", candidate_id)
        outputs.append(portfolio)
    return pd.concat(outputs, ignore_index=True)


__all__ = [
    "V6_ASSETS",
    "V6_CANDIDATE_IDS",
    "CausalV6CandidateBundle",
    "build_causal_v6_candidates",
    "build_v6_candidate_portfolio_targets",
]
