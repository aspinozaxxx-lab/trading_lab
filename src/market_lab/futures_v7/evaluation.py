"""Fail-closed execution i development-ocenka futures-v7 bez warmup leakage."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Final, Literal

import numpy as np
import pandas as pd

from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

V7_FOLD_YEARS: Final[tuple[int, ...]] = (  # Pyat' expanding OOS godov development.
    2021,
    2022,
    2023,
    2024,
    2025,
)
V7_PURGE_SESSIONS: Final[int] = 5  # Embargo v nachale kazhdogo scored goda.
V7_TRADING_SESSIONS: Final[int] = 252  # Fiksirovannaya annualizaciya fold returns.
V7_PRIMARY_SCENARIO: Final[str] = "asset_s1_f1"  # Bazovoe ispolnenie v7.
V7_DOUBLE_COST_SCENARIO: Final[str] = "asset_s2_f2"  # Zapechatannyi stress iz v6.
V7_GATE_CAGR: Final[float] = 0.12  # Minimal'nyi development CAGR.
V7_GATE_SHARPE: Final[float] = 0.80  # Minimal'nyi development Sharpe.
V7_GATE_DRAWDOWN: Final[float] = 0.25  # Predel close/intraday prosadki.
V7_GATE_POSITIVE_FOLDS: Final[int] = 4  # Minimum polozhitel'nyh godov iz pyati.
V7_GATE_WORST_FOLD_CAGR: Final[float] = -0.10  # Predel hudshego fold CAGR.
V7_GATE_DOUBLE_COST_CAGR: Final[float] = 0.0  # Stress-CAGR ne dolzhen byt' minusom.
V7_STRETCH_CAGR: Final[float] = 0.50  # Tol'ko aspiracionnyi report, ne gate.
V7_METRIC_TOLERANCE: Final[float] = 1e-12  # Chislovoi dopusk fiksirovannyh gates.
V7_RUIN_SHARPE: Final[float] = -1_000_000.0  # Konechnyi score posle ruin.
V7_FAILURE_EVENT_COLUMNS: Final[tuple[str, ...]] = (  # Audit-skhema sobytiya otkaza.
    "event_id",
    "scenario_id",
    "session_date",
    "event_type",
    "scope",
    "asset_codes",
    "order_keys",
    "reason_tokens",
)


@dataclass(frozen=True, slots=True)
class V7ScenarioSpec:
    """Fiksiruet odin iz dvenadcati execution stressov v7."""

    atomicity: Literal["asset", "portfolio"]
    slippage_ticks: Literal[1, 2, 4]
    fee_multiplier: Literal[1.0, 2.0]

    @property
    def scenario_id(self) -> str:
        """Vozvrashchaet stabil'nyi identifikator execution stressa."""
        return f"{self.atomicity}_s{self.slippage_ticks}_f{int(self.fee_multiplier)}"

    def ledger_config(
        self,
        initial_cash: float,
        expected_assets: tuple[str, ...],
    ) -> FuturesPortfolioLedgerConfig:
        """Stroit neizmenennuyu v6 ledger-konfiguraciyu dlya v7 adaptera."""
        return FuturesPortfolioLedgerConfig(
            initial_cash=initial_cash,
            expected_assets=expected_assets,
            slippage_ticks=self.slippage_ticks,
            fee_multiplier=self.fee_multiplier,
            execution_atomicity=self.atomicity,
        )


@dataclass(frozen=True, slots=True)
class V7LiquidityCoverageAudit:
    """Hranit causal coverage kazhdogo non-flat target order key do PnL."""

    warmup_session_count: int
    target_order_key_count: int
    covered_order_key_count: int
    exact_join: bool
    lagged_liquidity_complete: bool
    coverage: pd.DataFrame
    failures: pd.DataFrame

    @property
    def complete(self) -> bool:
        """Vozvrashchaet True tol'ko pri polnom exact i causal liquidity coverage."""
        return bool(
            self.warmup_session_count >= 1
            and self.exact_join
            and self.lagged_liquidity_complete
            and self.covered_order_key_count == self.target_order_key_count
            and self.failures.empty
        )


class V7ExecutionCoverageError(ValueError):
    """Peredaet machine-readable audit pri otkaze do zapuska PnL."""

    def __init__(self, audit: V7LiquidityCoverageAudit) -> None:
        """Sohranyaet audit i formiruet korotkoe fail-closed soobshchenie."""
        self.audit = audit
        super().__init__(
            "V7 pre-PnL execution coverage incomplete: "
            f"warmup={audit.warmup_session_count}, "
            f"covered={audit.covered_order_key_count}/{audit.target_order_key_count}, "
            f"failures={len(audit.failures)}"
        )


@dataclass(frozen=True, slots=True)
class V7ScenarioResult:
    """Obedinyaet raw ledger, scored slice i deduplicirovannye otkazy."""

    raw: FuturesPortfolioLedgerResult
    scored_ledger: pd.DataFrame
    failure_events: pd.DataFrame
    metrics: dict[str, float | int | bool | str]
    execution_complete: bool


@dataclass(frozen=True, slots=True)
class V7GateDecision:
    """Hranit zapechatannyi GO/NO-GO i otdel'nyi stretch-report."""

    passed: bool
    stretch_50_reached: bool
    candidate_id: str
    checks: dict[str, bool]
    observed: dict[str, float | int | bool | str]


def fixed_v7_scenarios() -> tuple[V7ScenarioSpec, ...]:
    """Stroit rovno 2 atomicity x 3 slippage x 2 fee scenariya."""
    return tuple(
        V7ScenarioSpec(atomicity=atomicity, slippage_ticks=slippage, fee_multiplier=fee)
        for atomicity in ("asset", "portfolio")
        for slippage in (1, 2, 4)
        for fee in (1.0, 2.0)
    )


def _normalized_date(value: str | date | pd.Timestamp, label: str) -> pd.Timestamp:
    """Privodit odnu granicu k timezone-naive calendar date."""
    result = pd.Timestamp(value)
    if pd.isna(result):
        raise ValueError(f"{label} ne mozhet byt' NaT")
    if result.tzinfo is not None:
        result = result.tz_convert("Europe/Moscow").tz_localize(None)
    return result.normalize()


def _normalized_dates(values: pd.Series, label: str) -> pd.Series:
    """Privodit seriyu timestamp k timezone-naive calendar dates."""
    result = pd.to_datetime(values, errors="raise")
    if result.isna().any():
        raise ValueError(f"{label} ne mozhet soderzhat' NaT")
    if result.dt.tz is not None:
        result = result.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    return result.dt.normalize()


def _asset_code(value: object) -> str:
    """Privodit logical asset k upper-case kodu RI/SI/BR/MIX."""
    normalized = str(value).strip().upper()
    return "RI" if normalized == "RTS" else normalized


def _finite_positive(values: pd.Series) -> pd.Series:
    """Vozvrashchaet masku konechnyh strogo polozhitel'nyh znachenii."""
    numeric = pd.to_numeric(values, errors="coerce")
    return np.isfinite(numeric) & numeric.gt(0.0)


def _normalize_v7_targets(
    targets: pd.DataFrame,
    score_start: pd.Timestamp,
    score_end: pd.Timestamp,
    expected_assets: tuple[str, ...],
) -> pd.DataFrame:
    """Proveryaet causal full snapshots i zapreshchaet warmup/holdout targets."""
    aliases = {
        "session_date": "effective_date",
        "asset": "asset_code",
        "canonical_contract_id": "contract_id",
    }
    frame = targets.rename(
        columns={source: target for source, target in aliases.items() if target not in targets}
    ).copy()
    required = {
        "effective_date",
        "decision_date",
        "asset_code",
        "contract_id",
        "target_weight",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V7 targets ne soderzhat kolonok: {sorted(missing)}")
    keep = sorted(required | ({"observed_through"} & set(frame.columns)))
    frame = frame.loc[:, keep].copy()
    frame["effective_date"] = _normalized_dates(frame["effective_date"], "effective_date")
    frame["decision_date"] = _normalized_dates(frame["decision_date"], "decision_date")
    if "observed_through" in frame:
        frame["observed_through"] = _normalized_dates(
            frame["observed_through"], "observed_through"
        )
    frame["asset_code"] = frame["asset_code"].map(_asset_code)
    frame["contract_id"] = frame["contract_id"].astype("string").str.strip()
    frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="raise")
    if frame.empty:
        raise ValueError("V7 targets ne mogut byt' pustymi")
    if (~np.isfinite(frame["target_weight"])).any():
        raise ValueError("V7 target_weight dolzhen byt' konechnym")
    if frame["target_weight"].abs().gt(1.0 + V7_METRIC_TOLERANCE).any():
        raise ValueError("V7 target_weight ne mozhet prevyshat' 1")
    if frame["decision_date"].ge(frame["effective_date"]).any():
        raise ValueError("V7 decision_date dolzhen byt' ran'she effective_date")
    if "observed_through" in frame and frame["observed_through"].gt(
        frame["decision_date"]
    ).any():
        raise ValueError("V7 observed_through ne mozhet byt' pozhe decision_date")
    if frame["effective_date"].lt(score_start).any():
        raise ValueError("V7 targets ne dolzhny torgovat' v warmup periode")
    if frame["effective_date"].gt(score_end).any():
        raise ValueError("V7 targets ne dolzhny torgovat' posle score_end")
    if frame.duplicated(["effective_date", "asset_code"]).any():
        raise ValueError("V7 target snapshot soderzhit duplicate asset")
    expected = frozenset(_asset_code(asset) for asset in expected_assets)
    if not expected or len(expected) != len(expected_assets):
        raise ValueError("expected_assets dolzhny byt' nepustymi i unikal'nymi")
    for effective_date, snapshot in frame.groupby("effective_date", sort=False):
        if frozenset(snapshot["asset_code"]) != expected:
            raise ValueError(f"Nepolnyi V7 target snapshot na {effective_date.date()}")
        if snapshot["decision_date"].nunique() != 1:
            raise ValueError("Odin V7 snapshot dolzhen imet' odnu decision_date")
        if snapshot["target_weight"].abs().sum() > 1.0 + V7_METRIC_TOLERANCE:
            raise ValueError("V7 gross target weights prevyshayut 1x")
    nonflat = frame["target_weight"].abs().gt(V7_METRIC_TOLERANCE)
    invalid_contract = frame["contract_id"].isna() | frame["contract_id"].eq("")
    if (nonflat & invalid_contract).any():
        raise ValueError("Nenulevoi V7 target trebuet contract_id")
    frame.loc[~nonflat, "contract_id"] = pd.NA
    return frame.sort_values(["effective_date", "asset_code"], ignore_index=True)


def _normalize_market_for_coverage(market: pd.DataFrame) -> pd.DataFrame:
    """Stroit exact factual keys i lagged volume iz polnoi dostupnoi istorii."""
    aliases = {
        "trade_date": "session_date",
        "asset": "asset_code",
        "canonical_contract_id": "contract_id",
    }
    frame = market.rename(
        columns={source: target for source, target in aliases.items() if target not in market}
    ).copy()
    required = {"session_date", "asset_code", "contract_id", "volume"}
    if missing := required - set(frame.columns):
        raise ValueError(f"V7 market coverage ne soderzhit: {sorted(missing)}")
    frame = frame.loc[:, sorted(required)].copy()
    frame["session_date"] = _normalized_dates(frame["session_date"], "market session_date")
    frame["asset_code"] = frame["asset_code"].map(_asset_code)
    frame["contract_id"] = frame["contract_id"].astype("string").str.strip()
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    if frame["asset_code"].eq("").any() or frame["contract_id"].isna().any() or frame[
        "contract_id"
    ].eq("").any():
        raise ValueError("V7 market keys ne mogut byt' pustymi")
    if frame.duplicated(["session_date", "asset_code", "contract_id"]).any():
        raise ValueError("V7 market coverage soderzhit duplicate exact key")
    frame = frame.sort_values(
        ["asset_code", "contract_id", "session_date"], kind="mergesort"
    ).reset_index(drop=True)
    grouped = frame.groupby(["asset_code", "contract_id"], sort=False)
    frame["lagged_volume"] = grouped["volume"].shift(1)
    frame["liquidity_source_date"] = grouped["session_date"].shift(1)
    return frame.sort_values(
        ["session_date", "asset_code", "contract_id"], kind="mergesort", ignore_index=True
    )


def audit_v7_lagged_liquidity(
    market: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    score_start: str | date | pd.Timestamp,
    score_end: str | date | pd.Timestamp,
    expected_assets: tuple[str, ...] = ("SI", "RI", "BR", "MIX"),
) -> V7LiquidityCoverageAudit:
    """Dokazyvaet exact target keys i strictly-prior positive volume do PnL."""
    start = _normalized_date(score_start, "score_start")
    end = _normalized_date(score_end, "score_end")
    if start > end:
        raise ValueError("score_start ne mozhet byt' pozhe score_end")
    normalized_targets = _normalize_v7_targets(targets, start, end, expected_assets)
    normalized_market = _normalize_market_for_coverage(market)
    warmup_sessions = int(
        normalized_market.loc[normalized_market["session_date"].lt(start), "session_date"].nunique()
    )
    nonflat = normalized_targets.loc[
        normalized_targets["target_weight"].abs().gt(V7_METRIC_TOLERANCE),
        ["effective_date", "asset_code", "contract_id", "target_weight"],
    ].copy()
    nonflat["order_key"] = (
        nonflat["effective_date"].dt.date.astype(str)
        + "|"
        + nonflat["asset_code"].astype(str)
        + "|"
        + nonflat["contract_id"].astype(str)
    )
    market_keys = normalized_market.rename(columns={"session_date": "effective_date"})
    joined = nonflat.merge(
        market_keys,
        on=["effective_date", "asset_code", "contract_id"],
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    joined["exact_market_row"] = joined["_merge"].eq("both")
    joined["strictly_prior_liquidity"] = (
        joined["liquidity_source_date"].notna()
        & joined["liquidity_source_date"].lt(joined["effective_date"])
    )
    joined["positive_lagged_volume"] = _finite_positive(joined["lagged_volume"])
    joined["covered"] = (
        joined["exact_market_row"]
        & joined["strictly_prior_liquidity"]
        & joined["positive_lagged_volume"]
    )
    failure_rows: list[dict[str, object]] = []
    if warmup_sessions < 1:
        failure_rows.append(
            {
                "event_id": "coverage:warmup:missing",
                "effective_date": pd.NaT,
                "asset_code": "",
                "contract_id": "",
                "reason": "missing_prior_warmup_session",
            }
        )
    for row in joined.loc[~joined["covered"]].itertuples(index=False):
        if not bool(row.exact_market_row):
            reason = "missing_exact_target_market_key"
        elif not bool(row.strictly_prior_liquidity):
            reason = "missing_strictly_prior_contract_volume"
        else:
            reason = "nonpositive_or_unknown_lagged_volume"
        failure_rows.append(
            {
                "event_id": f"coverage:{row.order_key}",
                "effective_date": row.effective_date,
                "asset_code": str(row.asset_code),
                "contract_id": str(row.contract_id),
                "reason": reason,
            }
        )
    failures = pd.DataFrame(
        failure_rows,
        columns=["event_id", "effective_date", "asset_code", "contract_id", "reason"],
    )
    if failures["event_id"].duplicated().any():
        raise ValueError("V7 coverage failure event_id dolzhen byt' unikal'nym")
    coverage = joined.drop(columns="_merge").sort_values(
        ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
    )
    exact_join = bool(joined["exact_market_row"].all())
    liquidity_complete = bool(
        joined["strictly_prior_liquidity"].all() & joined["positive_lagged_volume"].all()
    )
    return V7LiquidityCoverageAudit(
        warmup_session_count=warmup_sessions,
        target_order_key_count=len(joined),
        covered_order_key_count=int(joined["covered"].sum()),
        exact_join=exact_join,
        lagged_liquidity_complete=liquidity_complete,
        coverage=coverage,
        failures=failures,
    )


def _normalize_ledger(
    ledger: pd.DataFrame,
    initial_cash: float,
) -> pd.DataFrame:
    """Normalizuet continuous ledger i sohranyaet return ot predydushchei sessii."""
    required = {"session_date", "ending_cash", "intraday_adverse_equity"}
    if missing := required - set(ledger.columns):
        raise ValueError(f"V7 ledger ne soderzhit kolonok: {sorted(missing)}")
    if not np.isfinite(initial_cash) or initial_cash <= 0.0:
        raise ValueError("initial_cash dolzhen byt' konechnym i > 0")
    keep = sorted(required | ({"starting_cash"} & set(ledger.columns)))
    frame = ledger.loc[:, keep].copy()
    frame["session_date"] = _normalized_dates(frame["session_date"], "ledger session_date")
    if frame["session_date"].duplicated().any():
        raise ValueError("V7 ledger soderzhit povtornuyu session_date")
    frame = frame.sort_values("session_date", kind="mergesort").reset_index(drop=True)
    for column in ("ending_cash", "intraday_adverse_equity"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
        if (~np.isfinite(frame[column])).any():
            raise ValueError(f"V7 ledger {column} dolzhen byt' konechnym")
    prior_cash = frame["ending_cash"].shift(1, fill_value=float(initial_cash))
    if "starting_cash" in frame:
        stated = pd.to_numeric(frame["starting_cash"], errors="raise").astype(float)
        if (~np.isfinite(stated)).any():
            raise ValueError("V7 ledger starting_cash dolzhen byt' konechnym")
        mismatch = ~np.isclose(stated, prior_cash, rtol=0.0, atol=V7_METRIC_TOLERANCE)
        if mismatch.any():
            raise ValueError("V7 ledger starting_cash narushaet continuous cash path")
        frame["starting_cash"] = stated
    else:
        frame["starting_cash"] = prior_cash
    valid_return = frame["starting_cash"].gt(0.0) & frame["ending_cash"].gt(0.0)
    frame["daily_return"] = np.where(
        valid_return,
        frame["ending_cash"] / frame["starting_cash"] - 1.0,
        np.nan,
    )
    frame["ruined"] = (~valid_return) | frame["intraday_adverse_equity"].le(0.0)
    return frame


def _return_statistics(
    frame: pd.DataFrame,
    *,
    annualization: Literal["calendar", "sessions"],
) -> dict[str, float | int | bool]:
    """Schitaet metriki tol'ko po peredannym scored strochkam continuous path."""
    if len(frame) < 2:
        raise ValueError("V7 scored interval dolzhen soderzhat' minimum dve sessii")
    if frame["ruined"].any() or frame["daily_return"].isna().any():
        return {
            "session_count": len(frame),
            "ruined": True,
            "total_return": -1.0,
            "cagr": -1.0,
            "sharpe": V7_RUIN_SHARPE,
            "maximum_drawdown": 1.0,
        }
    returns = frame["daily_return"].to_numpy(dtype=float)
    growth = float(np.prod(1.0 + returns))
    if annualization == "sessions":
        exponent = V7_TRADING_SESSIONS / len(frame)
    else:
        elapsed_days = max(
            (pd.Timestamp(frame.iloc[-1]["session_date"]) - pd.Timestamp(
                frame.iloc[0]["session_date"]
            )).days,
            1,
        )
        exponent = 365.2425 / elapsed_days
    cagr = growth**exponent - 1.0
    deviation = float(pd.Series(returns).std(ddof=1))
    sharpe = (
        float(np.sqrt(V7_TRADING_SESSIONS) * np.mean(returns) / deviation)
        if deviation > V7_METRIC_TOLERANCE
        else 0.0
    )
    baseline = float(frame.iloc[0]["starting_cash"])
    endings = frame["ending_cash"].to_numpy(dtype=float)
    equity = np.r_[baseline, endings]
    peaks = np.maximum.accumulate(equity)
    close_drawdown = float(np.max(1.0 - equity / np.maximum(peaks, V7_METRIC_TOLERANCE)))
    prior_peaks = peaks[:-1]
    adverse = frame["intraday_adverse_equity"].to_numpy(dtype=float)
    adverse_drawdown = float(
        np.max(1.0 - adverse / np.maximum(prior_peaks, V7_METRIC_TOLERANCE))
    )
    return {
        "session_count": len(frame),
        "ruined": False,
        "total_return": growth - 1.0,
        "cagr": float(cagr),
        "sharpe": sharpe,
        "maximum_drawdown": max(0.0, close_drawdown, adverse_drawdown),
    }


def build_v7_score_metrics(
    ledger: pd.DataFrame,
    initial_cash: float,
    *,
    score_start: str | date | pd.Timestamp,
    score_end: str | date | pd.Timestamp,
) -> tuple[dict[str, float | int | bool], pd.DataFrame]:
    """Isklyuchaet warmup iz aggregate metrik, no sohranyaet ego previous cash."""
    start = _normalized_date(score_start, "score_start")
    end = _normalized_date(score_end, "score_end")
    if start > end:
        raise ValueError("score_start ne mozhet byt' pozhe score_end")
    normalized = _normalize_ledger(ledger, initial_cash)
    scored = normalized.loc[
        normalized["session_date"].between(start, end, inclusive="both")
    ].copy()
    if scored.empty:
        raise ValueError("V7 ledger ne imeet scored sessii")
    ruined_before_end = bool(
        normalized.loc[
            normalized["session_date"].between(start, scored["session_date"].iloc[-1]),
            "ruined",
        ].any()
    )
    if ruined_before_end:
        scored["ruined"] = True
    statistics = _return_statistics(scored, annualization="calendar")
    statistics.update(
        {
            "score_start": scored["session_date"].iloc[0].date().isoformat(),
            "score_end": scored["session_date"].iloc[-1].date().isoformat(),
            "starting_cash": float(scored.iloc[0]["starting_cash"]),
            "ending_cash": float(scored.iloc[-1]["ending_cash"]),
            "warmup_session_count": int(normalized["session_date"].lt(start).sum()),
            "positions_reset_between_folds": False,
        }
    )
    return statistics, scored.reset_index(drop=True)


def build_v7_fold_metrics(
    ledger: pd.DataFrame,
    initial_cash: float,
    *,
    score_start: str | date | pd.Timestamp,
    score_end: str | date | pd.Timestamp,
    fold_years: tuple[int, ...] = V7_FOLD_YEARS,
    purge_sessions: int = V7_PURGE_SESSIONS,
) -> pd.DataFrame:
    """Rezhit odin continuous path na purged folds bez sbrosa pozicii."""
    if purge_sessions < 0:
        raise ValueError("purge_sessions ne mozhet byt' otricatel'nym")
    if not fold_years or len(set(fold_years)) != len(fold_years):
        raise ValueError("fold_years dolzhny byt' nepustymi i unikal'nymi")
    start = _normalized_date(score_start, "score_start")
    end = _normalized_date(score_end, "score_end")
    normalized = _normalize_ledger(ledger, initial_cash)
    development = normalized.loc[
        normalized["session_date"].between(start, end, inclusive="both")
    ].copy()
    rows: list[dict[str, float | int | bool | str]] = []
    for year in fold_years:
        annual = development.loc[development["session_date"].dt.year.eq(year)].reset_index(
            drop=True
        )
        if len(annual) <= purge_sessions + 1:
            raise ValueError(f"V7 fold {year} ne imeet dostatochno sessii posle purge")
        scored = annual.iloc[purge_sessions:].copy()
        ruined_before_end = bool(
            development.loc[
                development["session_date"].le(scored["session_date"].iloc[-1]), "ruined"
            ].any()
        )
        if ruined_before_end:
            scored["ruined"] = True
        statistics = _return_statistics(scored, annualization="sessions")
        rows.append(
            {
                "fold_year": int(year),
                "purge_sessions": int(purge_sessions),
                "score_start": scored["session_date"].iloc[0].date().isoformat(),
                "score_end": scored["session_date"].iloc[-1].date().isoformat(),
                "positions_reset": False,
                **statistics,
            }
        )
    return pd.DataFrame(rows)


def _reason_tokens(values: pd.Series) -> list[str]:
    """Obedinyaet comma-separated prichiny bez povtorov i poryadkovogo shuma."""
    tokens = {
        token.strip()
        for value in values.astype(str)
        for token in value.split(",")
        if token.strip()
    }
    return sorted(tokens)


def _json_list(values: list[str]) -> str:
    """Kodiruet stabil'nyi spisok dlya CSV/JSON audit artefakta."""
    return json.dumps(sorted(set(values)), ensure_ascii=False, separators=(",", ":"))


def build_v7_execution_failure_events(
    result: FuturesPortfolioLedgerResult,
    scenario: V7ScenarioSpec,
) -> pd.DataFrame:
    """Dedupliciruet category counters do odnogo sobytiya na atomic attempt."""
    events: list[dict[str, object]] = []
    critical = result.orders.loc[
        result.orders["rejection_class"].astype(str).eq("critical")
    ].copy()
    group_columns = ["atomic_group"]
    if scenario.atomicity == "asset":
        group_columns.append("asset_code")
    for key, group in critical.groupby(group_columns, sort=True, dropna=False):
        key_values = key if isinstance(key, tuple) else (key,)
        atomic_group = str(key_values[0])
        scope = str(key_values[1]) if scenario.atomicity == "asset" else "portfolio"
        session_date = pd.Timestamp(group["session_date"].iloc[0]).normalize()
        order_keys = [
            f"{row.asset_code}|{row.contract_id}|{row.leg}"
            for row in group.itertuples(index=False)
        ]
        events.append(
            {
                "event_id": f"{scenario.scenario_id}:{atomic_group}:{scope}",
                "scenario_id": scenario.scenario_id,
                "session_date": session_date,
                "event_type": "critical_execution",
                "scope": scope,
                "asset_codes": _json_list(group["asset_code"].astype(str).tolist()),
                "order_keys": _json_list(order_keys),
                "reason_tokens": _json_list(_reason_tokens(group["reason"])),
            }
        )
    critical_by_date = {
        pd.Timestamp(event["session_date"]): event for event in events
    }
    ledger = result.ledger.copy()
    ledger["session_date"] = _normalized_dates(ledger["session_date"], "ledger events")
    for row in ledger.itertuples(index=False):
        session_date = pd.Timestamp(row.session_date)
        blocked_count = int(getattr(row, "critical_blocked_asset_count", 0))
        critical_status = "critical" in str(getattr(row, "status", ""))
        if (blocked_count > 0 or critical_status) and session_date not in critical_by_date:
            count = max(blocked_count, 1)
            for ordinal in range(count):
                events.append(
                    {
                        "event_id": (
                            f"{scenario.scenario_id}:{session_date.date()}:"
                            f"critical_mark:{ordinal + 1}"
                        ),
                        "scenario_id": scenario.scenario_id,
                        "session_date": session_date,
                        "event_type": "critical_mark_or_unsized_attempt",
                        "scope": "portfolio" if scenario.atomicity == "portfolio" else "asset",
                        "asset_codes": "[]",
                        "order_keys": "[]",
                        "reason_tokens": '["critical_ledger_status"]',
                    }
                )
    raw_critical = int(result.metrics.get("critical_failure_count", 0))
    if raw_critical > 0 and not events:
        last_date = pd.Timestamp(ledger["session_date"].iloc[-1])
        events.append(
            {
                "event_id": f"{scenario.scenario_id}:{last_date.date()}:unclassified:1",
                "scenario_id": scenario.scenario_id,
                "session_date": last_date,
                "event_type": "unclassified_ledger_failure",
                "scope": "portfolio",
                "asset_codes": "[]",
                "order_keys": "[]",
                "reason_tokens": '["raw_critical_counter_without_order"]',
            }
        )
    unresolved = int(result.metrics.get("unresolved_halt_count", 0))
    if unresolved > 0:
        last_date = pd.Timestamp(ledger["session_date"].iloc[-1])
        for ordinal in range(unresolved):
            events.append(
                {
                    "event_id": (
                        f"{scenario.scenario_id}:{last_date.date()}:"
                        f"unresolved_halt:{ordinal + 1}"
                    ),
                    "scenario_id": scenario.scenario_id,
                    "session_date": last_date,
                    "event_type": "unresolved_halt",
                    "scope": "portfolio" if scenario.atomicity == "portfolio" else "asset",
                    "asset_codes": "[]",
                    "order_keys": "[]",
                    "reason_tokens": '["terminal_unresolved_halt"]',
                }
            )
    frame = pd.DataFrame(events, columns=V7_FAILURE_EVENT_COLUMNS)
    if frame["event_id"].duplicated().any():
        raise ValueError("V7 execution failure event_id dolzhen byt' unikal'nym")
    return frame.sort_values(["session_date", "event_id"], ignore_index=True)


def _scenario_score_metrics(
    result: FuturesPortfolioLedgerResult,
    scenario: V7ScenarioSpec,
    *,
    initial_cash: float,
    score_start: pd.Timestamp,
    score_end: pd.Timestamp,
) -> tuple[dict[str, float | int | bool | str], pd.DataFrame, pd.DataFrame]:
    """Dobavlyaet score-only costs i unique execution failures k PnL metrikam."""
    performance, scored = build_v7_score_metrics(
        result.ledger,
        initial_cash,
        score_start=score_start,
        score_end=score_end,
    )
    orders = result.orders.copy()
    if not orders.empty:
        orders["session_date"] = _normalized_dates(orders["session_date"], "order date")
        orders = orders.loc[
            orders["session_date"].between(score_start, score_end, inclusive="both")
        ].copy()
    failure_events = build_v7_execution_failure_events(result, scenario)
    failure_events = failure_events.loc[
        failure_events["session_date"].between(score_start, score_end, inclusive="both")
    ].reset_index(drop=True)
    critical_event_count = int(
        failure_events["event_type"].ne("unresolved_halt").sum()
    )
    unresolved_event_count = int(
        failure_events["event_type"].eq("unresolved_halt").sum()
    )
    filled = orders.loc[orders["filled"].astype(bool)] if not orders.empty else orders
    commission = float(filled["commission_cost"].sum()) if not filled.empty else 0.0
    slippage = float(filled["slippage_cost"].sum()) if not filled.empty else 0.0
    order_notional = float(filled["gross_notional"].sum()) if not filled.empty else 0.0
    maximum_participation = (
        float(filled["participation"].max()) if not filled.empty else 0.0
    )
    cash_positive = float(performance["ending_cash"]) > 0.0
    execution_complete = bool(
        critical_event_count == 0 and unresolved_event_count == 0 and cash_positive
    )
    metrics: dict[str, float | int | bool | str] = {
        **performance,
        "commission_cost": commission,
        "slippage_cost": slippage,
        "total_cost": commission + slippage,
        "order_notional": order_notional,
        "maximum_gross_notional": float(scored["ending_cash"].mul(0.0).max()),
        "maximum_participation": maximum_participation,
        "filled_leg_count": int(len(filled)),
        "critical_execution_event_count": critical_event_count,
        "unresolved_halt_event_count": unresolved_event_count,
        "execution_failure_event_count": critical_event_count + unresolved_event_count,
        "critical_failure_count": critical_event_count,
        "unresolved_halt_count": unresolved_event_count,
        "raw_ledger_critical_failure_counter_sum": int(
            result.metrics.get("critical_failure_count", 0)
        ),
        "execution_complete": execution_complete,
        "continuous_position_path": True,
        "research_only": True,
    }
    score_mask = result.ledger["session_date"].pipe(
        lambda values: _normalized_dates(values, "ledger metric date").between(
            score_start, score_end, inclusive="both"
        )
    )
    score_raw = result.ledger.loc[score_mask]
    if not score_raw.empty:
        metrics["maximum_gross_notional"] = float(score_raw["gross_notional"].max())
        intraday_drawdown = _return_statistics(
            scored,
            annualization="calendar",
        )["maximum_drawdown"]
        metrics["intraday_adverse_drawdown"] = float(intraday_drawdown)
        metrics["maximum_modeled_initial_margin"] = float(
            score_raw["modeled_initial_margin"].max()
        )
        metrics["minimum_intraday_adverse_equity"] = float(
            score_raw["intraday_adverse_equity"].min()
        )
    else:
        metrics["intraday_adverse_drawdown"] = float(performance["maximum_drawdown"])
        metrics["maximum_modeled_initial_margin"] = 0.0
        metrics["minimum_intraday_adverse_equity"] = float(performance["starting_cash"])
    return metrics, scored, failure_events


def _market_through_end(market: pd.DataFrame, score_end: pd.Timestamp) -> pd.DataFrame:
    """Otrezaet budushchie stroki do peredachi v immutable v6 ledger."""
    date_column = "session_date" if "session_date" in market else "trade_date"
    if date_column not in market:
        raise ValueError("V7 market ne imeet session_date/trade_date")
    dates = _normalized_dates(market[date_column], "market score boundary")
    return market.loc[dates.le(score_end)].copy()


def run_v7_scenarios(
    market: pd.DataFrame,
    targets: pd.DataFrame,
    *,
    score_start: str | date | pd.Timestamp,
    score_end: str | date | pd.Timestamp,
    candidate_id: str = "causal_multiresolution_ensemble",
    initial_cash: float = 1_000_000.0,
    expected_assets: tuple[str, ...] = ("SI", "RI", "BR", "MIX"),
    fold_years: tuple[int, ...] = V7_FOLD_YEARS,
    purge_sessions: int = V7_PURGE_SESSIONS,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, V7ScenarioResult]]:
    """Auditit coverage, zatem ispolnyaet 12 stressov odnim continuous putem."""
    normalized_candidate = str(candidate_id).strip()
    if not normalized_candidate:
        raise ValueError("candidate_id ne mozhet byt' pustym")
    start = _normalized_date(score_start, "score_start")
    end = _normalized_date(score_end, "score_end")
    if start > end:
        raise ValueError("score_start ne mozhet byt' pozhe score_end")
    normalized_targets = _normalize_v7_targets(targets, start, end, expected_assets)
    market_for_ledger = _market_through_end(market, end)
    coverage = audit_v7_lagged_liquidity(
        market_for_ledger,
        normalized_targets,
        score_start=start,
        score_end=end,
        expected_assets=expected_assets,
    )
    if not coverage.complete:
        raise V7ExecutionCoverageError(coverage)
    scenario_rows: list[dict[str, object]] = []
    fold_frames: list[pd.DataFrame] = []
    results: dict[str, V7ScenarioResult] = {}
    for scenario in fixed_v7_scenarios():
        raw = run_futures_portfolio_ledger(
            market_for_ledger,
            normalized_targets,
            scenario.ledger_config(initial_cash, expected_assets),
        )
        metrics, scored, failures = _scenario_score_metrics(
            raw,
            scenario,
            initial_cash=initial_cash,
            score_start=start,
            score_end=end,
        )
        scenario_rows.append(
            {
                "candidate_id": normalized_candidate,
                "scenario_id": scenario.scenario_id,
                **asdict(scenario),
                **metrics,
                "pre_pnl_coverage_complete": coverage.complete,
                "covered_target_order_key_count": coverage.covered_order_key_count,
            }
        )
        folds = build_v7_fold_metrics(
            raw.ledger,
            initial_cash,
            score_start=start,
            score_end=end,
            fold_years=fold_years,
            purge_sessions=purge_sessions,
        )
        folds.insert(0, "scenario_id", scenario.scenario_id)
        folds.insert(0, "candidate_id", normalized_candidate)
        fold_frames.append(folds)
        results[scenario.scenario_id] = V7ScenarioResult(
            raw=raw,
            scored_ledger=scored,
            failure_events=failures,
            metrics=metrics,
            execution_complete=bool(metrics["execution_complete"]),
        )
    return (
        pd.DataFrame(scenario_rows),
        pd.concat(fold_frames, ignore_index=True),
        results,
    )


def evaluate_v7_gates(
    scenario_metrics: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    *,
    candidate_id: str = "causal_multiresolution_ensemble",
    fold_years: tuple[int, ...] = V7_FOLD_YEARS,
) -> V7GateDecision:
    """Primenyayet tol'ko fixed v7 gates i ne prevrashchaet 50% v objective."""
    required_scenario_columns = {
        "candidate_id",
        "scenario_id",
        "cagr",
        "sharpe",
        "maximum_drawdown",
        "intraday_adverse_drawdown",
        "execution_complete",
        "critical_execution_event_count",
        "unresolved_halt_event_count",
    }
    if missing := required_scenario_columns - set(scenario_metrics.columns):
        raise ValueError(f"V7 scenario metrics ne soderzhat: {sorted(missing)}")
    required_fold_columns = {"candidate_id", "scenario_id", "fold_year", "cagr"}
    if missing := required_fold_columns - set(fold_metrics.columns):
        raise ValueError(f"V7 fold metrics ne soderzhat: {sorted(missing)}")
    selected_scenarios = scenario_metrics.loc[
        scenario_metrics["candidate_id"].astype(str).eq(candidate_id)
    ].copy()
    required_ids = {scenario.scenario_id for scenario in fixed_v7_scenarios()}
    actual_ids = set(selected_scenarios["scenario_id"].astype(str))
    complete_grid = bool(
        actual_ids == required_ids
        and len(selected_scenarios) == len(required_ids)
        and not selected_scenarios["scenario_id"].duplicated().any()
    )
    if V7_PRIMARY_SCENARIO not in actual_ids:
        raise ValueError("Net V7 primary scenario")
    if V7_DOUBLE_COST_SCENARIO not in actual_ids:
        raise ValueError("Net V7 double-cost scenario")
    indexed = selected_scenarios.set_index("scenario_id")
    primary = indexed.loc[V7_PRIMARY_SCENARIO]
    double_cost = indexed.loc[V7_DOUBLE_COST_SCENARIO]
    selected_folds = fold_metrics.loc[
        fold_metrics["candidate_id"].astype(str).eq(candidate_id)
        & fold_metrics["scenario_id"].astype(str).eq(V7_PRIMARY_SCENARIO)
    ].copy()
    complete_folds = bool(
        set(selected_folds["fold_year"].astype(int)) == set(fold_years)
        and len(selected_folds) == len(fold_years)
        and not selected_folds["fold_year"].duplicated().any()
    )
    positive_folds = int(selected_folds["cagr"].gt(0.0).sum())
    worst_fold_cagr = (
        float(selected_folds["cagr"].min()) if not selected_folds.empty else float("-inf")
    )
    maximum_critical = int(selected_scenarios["critical_execution_event_count"].max())
    maximum_unresolved = int(selected_scenarios["unresolved_halt_event_count"].max())
    risk_drawdown = max(
        float(primary["maximum_drawdown"]),
        float(primary["intraday_adverse_drawdown"]),
    )
    checks = {
        "complete_execution_scenario_grid": complete_grid,
        "complete_fold_set": complete_folds,
        "all_execution_complete": bool(
            complete_grid and selected_scenarios["execution_complete"].astype(bool).all()
        ),
        "zero_critical_execution_events": maximum_critical == 0,
        "zero_unresolved_halt_events": maximum_unresolved == 0,
        "aggregate_cagr": float(primary["cagr"]) + V7_METRIC_TOLERANCE >= V7_GATE_CAGR,
        "aggregate_sharpe": (
            float(primary["sharpe"]) + V7_METRIC_TOLERANCE >= V7_GATE_SHARPE
        ),
        "maximum_drawdown": risk_drawdown <= V7_GATE_DRAWDOWN + V7_METRIC_TOLERANCE,
        "positive_fold_count": positive_folds >= V7_GATE_POSITIVE_FOLDS,
        "worst_fold_cagr": (
            worst_fold_cagr + V7_METRIC_TOLERANCE >= V7_GATE_WORST_FOLD_CAGR
        ),
        "double_cost_cagr": (
            float(double_cost["cagr"]) + V7_METRIC_TOLERANCE
            >= V7_GATE_DOUBLE_COST_CAGR
        ),
    }
    observed: dict[str, float | int | bool | str] = {
        "primary_scenario": V7_PRIMARY_SCENARIO,
        "double_cost_scenario": V7_DOUBLE_COST_SCENARIO,
        "primary_cagr": float(primary["cagr"]),
        "primary_sharpe": float(primary["sharpe"]),
        "primary_risk_drawdown": risk_drawdown,
        "positive_fold_count": positive_folds,
        "worst_fold_cagr": worst_fold_cagr,
        "double_cost_cagr": float(double_cost["cagr"]),
        "scenario_count": len(selected_scenarios),
        "expected_scenario_count": len(required_ids),
        "maximum_critical_execution_event_count": maximum_critical,
        "maximum_unresolved_halt_event_count": maximum_unresolved,
        "stretch_target_cagr": V7_STRETCH_CAGR,
    }
    return V7GateDecision(
        passed=all(checks.values()),
        stretch_50_reached=float(primary["cagr"]) + V7_METRIC_TOLERANCE
        >= V7_STRETCH_CAGR,
        candidate_id=candidate_id,
        checks=checks,
        observed=observed,
    )


__all__ = [
    "V7_DOUBLE_COST_SCENARIO",
    "V7_FOLD_YEARS",
    "V7_PRIMARY_SCENARIO",
    "V7ExecutionCoverageError",
    "V7GateDecision",
    "V7LiquidityCoverageAudit",
    "V7ScenarioResult",
    "V7ScenarioSpec",
    "audit_v7_lagged_liquidity",
    "build_v7_execution_failure_events",
    "build_v7_fold_metrics",
    "build_v7_score_metrics",
    "evaluate_v7_gates",
    "fixed_v7_scenarios",
    "run_v7_scenarios",
]
