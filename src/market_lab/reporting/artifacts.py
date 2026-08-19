"""Atomarnaya zapis polnogo nabora artefaktov eksperimenta."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from market_lab.io_utils import TEXT_ENCODING, atomic_write_text, write_json, write_yaml

PROJECT_CACHE = Path(__file__).resolve().parents[3] / ".cache" / "matplotlib"  # Lokalnyi kesh.
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_CACHE))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

LEADERBOARD_COLUMNS = [  # Stabilnaya publichnaya schema leaderboard.
    "candidate",
    "kind",
    "validation_score",
    "validation_return",
    "validation_sharpe",
    "validation_calmar",
    "validation_max_drawdown",
    "validation_trade_count",
    "validation_positive_fold_fraction",
    "validation_recent_fold_return",
    "validation_worst_fold_return",
    "test_return",
    "test_sharpe",
    "test_calmar",
    "test_max_drawdown",
    "test_turnover",
    "test_trade_count",
    "test_costs",
    "parameters",
    "eligible",
    "selected",
]


def create_run_directory(runs_dir: Path) -> Path:
    """Sozdaet unikalnyi katalog po UTC-vremeni i korotkomu UUID."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    run_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=False, exist_ok=False)
    return run_dir


def sort_leaderboard(frame: pd.DataFrame) -> pd.DataFrame:
    """Sortiruet kandidatov tolko po validation-score."""
    missing = set(LEADERBOARD_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"Leaderboard ne soderzhit kolonki: {sorted(missing)}")
    return frame.sort_values(
        by=["validation_score", "candidate"],
        ascending=[False, True],
        na_position="last",
        kind="mergesort",
    ).reset_index(drop=True)


class ArtifactWriter:
    """Sohranyaet vse tekstovye i binarnye rezultaty odnogo zapuska."""

    def __init__(self, run_dir: Path) -> None:
        """Privyazyvaet zapis k uzhe sozdannomu katalogu."""
        self.run_dir = run_dir

    def write_json(self, name: str, payload: Any) -> Path:
        """Sohranyaet JSON v katalog zapuska."""
        target = self.run_dir / name
        write_json(target, payload)
        return target

    def write_yaml(self, name: str, payload: Any) -> Path:
        """Sohranyaet YAML v katalog zapuska."""
        target = self.run_dir / name
        write_yaml(target, payload)
        return target

    def write_text(self, name: str, content: str) -> Path:
        """Sohranyaet proizvolnyi tekstovyi otchet."""
        target = self.run_dir / name
        atomic_write_text(target, content)
        return target

    def write_frame(self, name: str, frame: pd.DataFrame, index: bool = False) -> Path:
        """Atomarno sohranyaet DataFrame v CSV s BOM."""
        target = self.run_dir / name
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.", suffix=".csv", dir=self.run_dir, delete=False
        ) as stream:
            temporary = Path(stream.name)
        try:
            frame.to_csv(temporary, index=index, encoding=TEXT_ENCODING)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def write_model(self, name: str, model: Any) -> Path:
        """Atomarno serializuet obuchennyi obekt cherez joblib."""
        target = self.run_dir / name
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.", suffix=".joblib", dir=self.run_dir, delete=False
        ) as stream:
            temporary = Path(stream.name)
        try:
            joblib.dump(model, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def write_equity_plot(
        self,
        name: str,
        equity: pd.Series,
        width: float,
        height: float,
        title: str,
    ) -> Path:
        """Atomarno sohranyaet PNG-grafik krivoi kapitala."""
        target = self.run_dir / name
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.", suffix=".png", dir=self.run_dir, delete=False
        ) as stream:
            temporary = Path(stream.name)
        figure, axis = plt.subplots(figsize=(width, height))
        try:
            equity.plot(ax=axis, color="#1f77b4", linewidth=1.5)
            axis.set_title(title)
            axis.set_xlabel("Time")
            axis.set_ylabel("Equity")
            axis.grid(True, alpha=0.3)
            figure.tight_layout()
            figure.savefig(temporary, dpi=120, format="png")
            temporary.replace(target)
        finally:
            plt.close(figure)
            temporary.unlink(missing_ok=True)
        return target


def format_parameters(parameters: dict[str, Any]) -> str:
    """Serializuet parametry v stabilnuyu yacheiku CSV."""
    return json.dumps(parameters, ensure_ascii=False, sort_keys=True)
