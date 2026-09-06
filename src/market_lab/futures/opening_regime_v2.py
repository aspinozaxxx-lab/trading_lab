"""V62 causal opening features and purged, chronological model fitting.

Candidate construction never receives labels or examines the current day's close.
All cross-session differences use the exact same contract on consecutive sessions.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier

ASSETS = ("BR", "MIX", "RI", "SI")
DECISIONS = (600, 630, 660)
STEP = pd.Timedelta(minutes=10)
PROTECTED = pd.Timestamp("2026-01-01", tz="UTC")
FEATURES = (
    tuple(
        f"{asset}_{name}"
        for asset in ASSETS
        for name in ("gap_z", "opening", "previous_return", "previous_rv", "gap_vol", "horizon_vol")
    )
    + (
        "gap_mean",
        "gap_dispersion",
        "gap_min",
        "gap_max",
        "opening_mean",
        "opening_dispersion",
        "gap_breadth",
        "opening_breadth",
        "RI_minus_MIX",
        "SI_minus_BR",
        "weekday_sin",
        "weekday_cos",
    )
    + tuple(f"clock_{minute}" for minute in DECISIONS)
    + tuple(f"asset_{a}" for a in ASSETS)
)
KEYS = (
    "candidate_id",
    "local_date",
    "decision_at",
    "entry_at",
    "exit_at",
    "asset",
    "contract_id",
    "decision_minute",
    "own_gap_z",
    "decision_volume",
    "decision_close",
)


def local_time(day: pd.Timestamp, minute: int) -> pd.Timestamp:
    return (
        pd.Timestamp(day).normalize().tz_localize("Europe/Moscow") + pd.Timedelta(minutes=minute)
    ).tz_convert("UTC")


@dataclass
class Market:
    bars: pd.DataFrame
    plan: pd.DataFrame
    sessions: pd.DatetimeIndex

    def __post_init__(self) -> None:
        self.bars = self.bars.copy()
        self.bars["timestamp"] = pd.to_datetime(self.bars["timestamp"], utc=True)
        if self.bars["timestamp"].ge(PROTECTED).any():
            raise ValueError("protected 2026 market rows")
        if self.bars.duplicated(["contract_id", "timestamp"]).any():
            raise ValueError("duplicate contract timestamp")
        self._fields = ("open", "high", "low", "close", "volume")
        self._values = self.bars[list(self._fields)].to_numpy(float)
        timestamps = self.bars["timestamp"].astype("int64").to_numpy()
        endings = pd.to_datetime(self.bars["end_timestamp"], utc=True).astype("int64").to_numpy()
        self._locations = {
            (contract, int(stamp)): index
            for index, (contract, stamp) in enumerate(
                zip(self.bars["contract_id"], timestamps, strict=True)
            )
        }
        values = self._values
        self._valid = (
            np.isfinite(values).all(axis=1)
            & (values[:, :4] > 0).all(axis=1)
            & (values[:, 4] >= 0)
            & (values[:, 1] >= np.maximum(values[:, 0], values[:, 3]))
            & (values[:, 2] <= np.minimum(values[:, 0], values[:, 3]))
            & (endings > timestamps)
            & (endings <= timestamps + STEP.value)
        )
        self.contracts = self.plan.set_index(["local_date", "asset"])["contract_id"].to_dict()

    def bar(self, contract: str, timestamp: pd.Timestamp) -> dict[str, float] | None:
        index = self._locations.get((contract, timestamp.value))
        if index is None or not self._valid[index]:
            return None
        return dict(zip(self._fields, self._values[index], strict=True))

    def horizon(self, contract: str, entry: pd.Timestamp) -> float:
        path = [self.bar(contract, entry + n * STEP) for n in range(7)]
        if any(row is None for row in path):
            return np.nan
        return float(np.log(float(path[-1]["open"]) / float(path[0]["open"])))


def build_candidates(market: Market) -> pd.DataFrame:
    """Build only information observable by each decision; no test labels attached."""
    records = []
    gap_history = {a: [] for a in ASSETS}
    horizon_history = {a: [] for a in ASSETS}
    previous_day = None
    for day in market.sessions:
        if previous_day is None:
            previous_day = day
            continue
        state = {}
        gaps = {}
        for asset in ASSETS:
            contract = market.contracts.get((day, asset))
            prior_contract = market.contracts.get((previous_day, asset))
            # The *current*, already planned contract is used at both gap endpoints.
            opening = market.bar(contract, local_time(day, 600)) if contract else None
            prior_close = market.bar(contract, local_time(previous_day, 1120)) if contract else None
            prior_open = market.bar(contract, local_time(previous_day, 600)) if contract else None
            gap = (
                float(np.log(opening["open"] / prior_close["close"]))
                if opening is not None and prior_close is not None
                else np.nan
            )
            gaps[asset] = gap
            # Each history list retains every prior factual session, including missing.
            gh = np.asarray(gap_history[asset][-60:], float)
            hv = (
                float(np.std(horizon_history[asset][-60:], ddof=0))
                if len(horizon_history[asset]) >= 60
                else np.nan
            )
            gv = float(np.std(gh, ddof=0)) if len(gh) == 60 else np.nan
            previous_return = (
                float(np.log(prior_close["close"] / prior_open["open"]))
                if prior_close is not None and prior_open is not None
                else np.nan
            )
            # Main-session RV uses only exact adjacent completed bars, no clearing bridge.
            rv_terms = []
            last = None
            for minute in range(600, 1121, 10):
                row = market.bar(contract, local_time(previous_day, minute)) if contract else None
                if row is not None and last is not None:
                    rv_terms.append(float(np.log(row["close"] / last["close"])) ** 2)
                last = row
            rv = float(np.sqrt(np.sum(rv_terms))) if len(rv_terms) >= 36 else np.nan
            state[asset] = dict(
                contract=contract,
                opening=opening,
                gap=gap,
                gap_vol=gv,
                horizon_vol=hv,
                previous_return=previous_return,
                previous_rv=rv,
            )
            # Frozen 10:10 -> 11:10 horizon, on the previous day only, not candidate-filtered.
            prior_horizon = (
                market.horizon(prior_contract, local_time(previous_day, 610))
                if prior_contract
                else np.nan
            )
            horizon_history[asset].append(prior_horizon)
            # Update horizon vol after making yesterday's label available, still strictly prior.
            if len(horizon_history[asset]) >= 60:
                state[asset]["horizon_vol"] = float(np.std(horizon_history[asset][-60:], ddof=0))
        for minute in DECISIONS:
            features = {}
            decision_rows = {}
            for asset in ASSETS:
                item = state[asset]
                contract = item["contract"]
                row = market.bar(contract, local_time(day, minute)) if contract else None
                opening_path_complete = bool(contract) and all(
                    market.bar(contract, local_time(day, m)) is not None
                    for m in range(600, minute + 1, 10)
                )
                if (
                    row is None
                    or not opening_path_complete
                    or item["opening"] is None
                    or not np.isfinite(item["gap"])
                    or not np.isfinite(item["gap_vol"])
                    or item["gap_vol"] <= 0
                ):
                    break
                # No current-session bar after this completed decision enters features.
                features.update(
                    {
                        f"{asset}_gap_z": item["gap"] / item["gap_vol"],
                        f"{asset}_opening": float(np.log(row["close"] / item["opening"]["open"])),
                        f"{asset}_previous_return": item["previous_return"],
                        f"{asset}_previous_rv": item["previous_rv"],
                        f"{asset}_gap_vol": item["gap_vol"],
                        f"{asset}_horizon_vol": item["horizon_vol"],
                    }
                )
                decision_rows[asset] = row
            if len(decision_rows) != 4:
                continue
            z = np.asarray([features[f"{a}_gap_z"] for a in ASSETS])
            op = np.asarray([features[f"{a}_opening"] for a in ASSETS])
            features.update(
                dict(
                    gap_mean=z.mean(),
                    gap_dispersion=z.std(ddof=0),
                    gap_min=z.min(),
                    gap_max=z.max(),
                    opening_mean=op.mean(),
                    opening_dispersion=op.std(ddof=0),
                    gap_breadth=(z > 0).mean(),
                    opening_breadth=(op > 0).mean(),
                    RI_minus_MIX=z[2] - z[1],
                    SI_minus_BR=z[3] - z[0],
                    weekday_sin=np.sin(2 * np.pi * day.weekday() / 7),
                    weekday_cos=np.cos(2 * np.pi * day.weekday() / 7),
                )
            )
            features.update({f"clock_{m}": float(m == minute) for m in DECISIONS})
            for asset in ASSETS:
                own_gap = features[f"{asset}_gap_z"]
                if abs(own_gap) < 0.75 and features["gap_dispersion"] < 1.0:
                    continue
                contract = state[asset]["contract"]
                row = decision_rows[asset]
                record = dict(features)
                record.update({f"asset_{a}": float(a == asset) for a in ASSETS})
                record.update(
                    dict(
                        candidate_id=f"{day:%Y%m%d}_{minute}_{asset}",
                        local_date=day,
                        decision_at=local_time(day, minute + 10),
                        entry_at=local_time(day, minute + 10),
                        exit_at=local_time(day, minute + 70),
                        asset=asset,
                        contract_id=contract,
                        decision_minute=minute,
                        own_gap_z=own_gap,
                        decision_volume=float(row["volume"]),
                        decision_close=float(row["close"]),
                    )
                )
                records.append(record)
        for asset in ASSETS:
            gap_history[asset].append(gaps[asset])
        previous_day = day
    return (
        pd.DataFrame(records, columns=[*KEYS, *FEATURES])
        .sort_values(["decision_at", "asset"], kind="stable")
        .reset_index(drop=True)
    )


def build_labels(candidates: pd.DataFrame, market: Market) -> pd.DataFrame:
    records = []
    for row in candidates.itertuples(index=False):
        value = market.horizon(row.contract_id, row.entry_at)
        records.append(
            dict(
                candidate_id=row.candidate_id,
                raw_return=value,
                positive=float(value > 0) if np.isfinite(value) else np.nan,
                available_at=row.exit_at + STEP,
                valid=bool(np.isfinite(value)),
            )
        )
    return pd.DataFrame(
        records, columns=["candidate_id", "raw_return", "positive", "available_at", "valid"]
    )


def fit_transform(train: pd.DataFrame) -> dict[str, np.ndarray]:
    values = train[list(FEATURES)].to_numpy(float)
    # Explicit all-missing columns are neutral plus a missing indicator, fitted on core only.
    median = np.zeros(values.shape[1])
    scale = np.ones(values.shape[1])
    for n in range(values.shape[1]):
        finite = values[np.isfinite(values[:, n]), n]
        if len(finite):
            median[n] = np.median(finite)
            spread = np.percentile(finite, 75) - np.percentile(finite, 25)
            if spread > 1e-12:
                scale[n] = spread
    return dict(median=median, scale=scale)


def transform(frame: pd.DataFrame, fitted: dict[str, np.ndarray]) -> np.ndarray:
    values = frame[list(FEATURES)].to_numpy(float)
    missing = ~np.isfinite(values)
    result = (np.where(missing, fitted["median"], values) - fitted["median"]) / fitted["scale"]
    return np.column_stack([np.clip(result, -8, 8), missing.astype(float)])


def fit_fold(
    core: pd.DataFrame, validation: pd.DataFrame, inference: pd.DataFrame
) -> tuple[dict[str, np.ndarray], dict, list[dict]]:
    """Inference has no target columns; validation is chronological with a session purge."""
    if any(c in inference for c in ("positive", "raw_return", "valid", "available_at")):
        raise ValueError("inference contains outcome columns")
    scaler = fit_transform(core)
    x = transform(core, scaler)
    xv = transform(validation, scaler)
    xt = transform(inference, scaler)
    y = core["positive"].to_numpy(int)
    yv = validation["positive"].to_numpy(int)
    logistic = LogisticRegression(C=0.1, max_iter=400, random_state=6200)
    logistic.fit(x, y)
    probabilities = []
    models = dict(scaler=scaler, logistic=logistic, mlp=[])
    traces = []
    for seed in (6201, 6202, 6203):
        model = MLPClassifier(
            hidden_layer_sizes=(32, 16),
            activation="relu",
            solver="adam",
            alpha=0.001,
            learning_rate_init=0.0005,
            batch_size=256,
            early_stopping=False,
            random_state=seed,
        )
        best = None
        best_score = -np.inf
        stale = 0
        best_epoch = 0
        for epoch in range(1, 81):
            model.partial_fit(x, y, classes=np.asarray([0, 1]))
            score = float(model.score(xv, yv))
            if score > best_score + 0.0001:
                best, best_score, best_epoch = copy.deepcopy(model), score, epoch
                stale = 0
            else:
                stale += 1
            if stale >= 8:
                break
        probabilities.append(best.predict_proba(xt)[:, 1])
        models["mlp"].append(best)
        traces.append(
            dict(seed=seed, epochs=epoch, chosen_epoch=best_epoch, validation_accuracy=best_score)
        )
    return (
        dict(mlp=np.mean(probabilities, axis=0), logistic=logistic.predict_proba(xt)[:, 1]),
        models,
        traces,
    )


def walk_forward(
    candidates: pd.DataFrame, labels: pd.DataFrame, sessions: pd.DatetimeIndex
) -> tuple[pd.DataFrame, list[dict], dict]:
    outputs, folds, artifacts = [], [], {}
    for year in range(2021, 2026):
        test = candidates.loc[candidates["local_date"].dt.year.eq(year)].copy()
        prior_sessions = sessions[sessions.year < year]
        record = dict(
            year=year,
            test_rows=len(test),
            core_rows=0,
            validation_rows=0,
            status="sleep_insufficient_history",
            seeds=[],
        )
        probability = {key: np.full(len(test), np.nan) for key in ("mlp", "logistic")}
        if len(prior_sessions) > 10 and not test.empty:
            outer_cutoff = prior_sessions[-2]
            eligible = candidates.loc[candidates["local_date"].lt(outer_cutoff)].copy()
            # Only past labels are selected and supplied to training/early stopping.
            past_labels = labels.loc[labels["available_at"].lt(local_time(outer_cutoff, 0))]
            train = eligible.merge(past_labels, on="candidate_id", validate="one_to_one")
            train = train.loc[train["valid"]].copy()
            dates = pd.DatetimeIndex(train["local_date"].unique()).sort_values()
            if len(dates) > 10:
                split = int(np.floor(len(dates) * 0.85))
                validation_start = dates[split]
                earlier = sessions[sessions < validation_start]
                core_cutoff = earlier[-2]
                core = train.loc[train["local_date"].lt(core_cutoff)]
                validation = train.loc[train["local_date"].ge(validation_start)]
                counts = core["positive"].value_counts()
                record.update(
                    core_rows=len(core),
                    validation_rows=len(validation),
                    core_cutoff=core_cutoff,
                    validation_start=validation_start,
                    outer_cutoff=outer_cutoff,
                )
                if len(core) >= 1000 and counts.get(0, 0) >= 200 and counts.get(1, 0) >= 200:
                    probability, artifacts[str(year)], trace = fit_fold(core, validation, test)
                    record.update(status="fitted", seeds=trace)
        folds.append(record)
        for model_id in ("mlp", "logistic", "gap_fade", "gap_continuation"):
            output = test.copy()
            if model_id in probability:
                output["probability_long"] = probability[model_id]
            else:
                positive = test["own_gap_z"].gt(0)
                output["probability_long"] = (
                    positive if model_id == "gap_continuation" else ~positive
                ).astype(float)
            output["direction"] = np.select(
                [output["probability_long"].ge(0.60), output["probability_long"].le(0.40)],
                [1, -1],
                default=0,
            )
            output["model_id"] = model_id
            outputs.append(output)
    return pd.concat(outputs, ignore_index=True), folds, artifacts
