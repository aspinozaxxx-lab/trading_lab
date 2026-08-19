"""Polzovatelskii CLI lokalnoi laboratorii."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Literal

import typer

from market_lab.alpha import (
    execute_alpha_experiment,
    execute_ranker_experiment,
    load_alpha_config,
    load_ranker_config,
)
from market_lab.config import AppConfig, load_config
from market_lab.data.storage import processed_path
from market_lab.experiments import download_data, execute_experiment
from market_lab.sequence import download_sequence_data, load_sequence_config

app = typer.Typer(
    name="market-lab",
    help="Локальная CPU-лаборатория торговых стратегий.",
    no_args_is_help=True,
)  # Glavnoe CLI-prilozhenie paketa.
DEFAULT_CONFIG = Path("configs/mvp.yaml")  # Put konfiguracii po umolchaniyu.
CORE_PACKAGES = (  # Pakety, versii kotoryh pokazyvaet doctor.
    "numpy",
    "pandas",
    "scikit-learn",
    "optuna",
    "pydantic",
    "PyYAML",
    "matplotlib",
    "pyarrow",
    "typer",
    "xgboost",
)


def _console_logging() -> None:
    """Nastraivaet standartnyi logging dlya komand bez run-kataloga."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _load_or_exit(config_path: Path) -> AppConfig:
    """Zagruzhaet konfiguraciyu ili zavershaet CLI s ponyatnoi oshibkoi."""
    try:
        return load_config(config_path)
    except Exception as error:
        typer.echo(f"Ошибка конфигурации: {error}", err=True)
        raise typer.Exit(code=2) from error


def _gpu_diagnostics() -> str:
    """Vozvrashchaet model' NVIDIA, VRAM i draiver bez izmeneniya sistemy."""
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return completed.stdout.strip() or "unavailable"


def _run_or_exit(
    config: AppConfig,
    mode: Literal["run", "optimize", "demo"],
    offline: bool = False,
) -> None:
    """Vypolnyaet eksperiment i pechataet put ili prichinu sboya."""
    try:
        run_dir = execute_experiment(config, mode=mode, offline=offline)
    except Exception as error:
        logging.getLogger(__name__).exception("Eksperiment zavershilsya oshibkoi")
        typer.echo(f"Эксперимент не завершён: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Артефакты: {run_dir}")


@app.command()
def doctor(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False)
    ] = DEFAULT_CONFIG,
) -> None:
    """Proveryaet okruzhenie, zavisimosti, katalogi i kesh dannyh."""
    resolved = _load_or_exit(config)
    typer.echo(f"Python: {sys.version.split()[0]}")
    typer.echo(f"Executable: {sys.executable}")
    typer.echo(f"Environment: {sys.prefix}")
    typer.echo(f"Virtual environment: {'yes' if sys.prefix != sys.base_prefix else 'no'}")
    typer.echo(f"CPU mode: cpu, logical cores={os.cpu_count()}, n_jobs=1")
    typer.echo(f"NVIDIA GPU: {_gpu_diagnostics()}")
    for package in CORE_PACKAGES:
        try:
            package_version = version(package)
        except PackageNotFoundError:
            package_version = "MISSING"
        typer.echo(f"{package}: {package_version}")
    all_writable = True
    directories = (
        resolved.paths.raw_data_dir,
        resolved.paths.processed_data_dir,
        resolved.paths.runs_dir,
    )
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix="doctor-", dir=directory, delete=True):
                pass
            status = "writable"
        except OSError as error:
            status = f"not writable: {error}"
            all_writable = False
        typer.echo(f"Directory {directory}: {status}")
    cache = processed_path(resolved)
    typer.echo(f"Cached dataset: {'yes' if cache.exists() else 'no'} ({cache})")
    if not all_writable:
        raise typer.Exit(code=1)


@app.command()
def download(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
) -> None:
    """Zagruzhaet i keshiruet nebolshoi diapazon MOEX."""
    _console_logging()
    resolved = _load_or_exit(config)
    try:
        target = download_data(resolved)
    except Exception as error:
        logging.getLogger(__name__).exception("Zagruzka MOEX zavershilas oshibkoi")
        typer.echo(f"Загрузка не завершена: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Данные сохранены: {target}")


@app.command()
def run(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
) -> None:
    """Zapuskaet odin trial s parametrami iz YAML i lokalnym keshem."""
    resolved = _load_or_exit(config)
    _run_or_exit(resolved, mode="run")


@app.command()
def optimize(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
) -> None:
    """Zapuskaet Optuna-study po lokalno zakeshirovannym dannym."""
    resolved = _load_or_exit(config)
    _run_or_exit(resolved, mode="optimize")


@app.command()
def demo(
    config: Annotated[Path, typer.Option("--config", exists=True, dir_okay=False)],
    offline: Annotated[
        bool, typer.Option("--offline", help="Использовать только fixture.")
    ] = False,
) -> None:
    """Zapuskaet praktichnyi demo-konveier online ili bez seti."""
    resolved = _load_or_exit(config)
    _run_or_exit(resolved, mode="demo", offline=offline)


@app.command()
def alpha(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False)
    ] = Path("configs/alpha50.yaml"),
    validation_only: Annotated[
        bool,
        typer.Option(
            "--validation-only",
            help="Не открывать final holdout после выбора стратегии.",
        ),
    ] = False,
) -> None:
    """Zapuskaet mezhaktivnyi alpha-eksperiment s zapechatannym holdout."""
    try:
        resolved = load_alpha_config(config)
        run_dir = execute_alpha_experiment(resolved, validation_only=validation_only)
    except Exception as error:
        logging.getLogger(__name__).exception("Alpha-eksperiment zavershilsya oshibkoi")
        typer.echo(f"Alpha-эксперимент не завершён: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Alpha-артефакты: {run_dir}")


@app.command()
def ranker(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False)
    ] = Path("configs/alpha50_ranker.yaml"),
    validation_only: Annotated[
        bool,
        typer.Option(
            "--validation-only",
            help="Не открывать новый instrument-holdout после фиксации модели.",
        ),
    ] = False,
) -> None:
    """Zapuskaet GPU-ranker s zapechatannym novym instrument-holdout."""
    try:
        resolved = load_ranker_config(config)
        run_dir = execute_ranker_experiment(resolved, validation_only=validation_only)
    except Exception as error:
        logging.getLogger(__name__).exception("Ranker-eksperiment zavershilsya oshibkoi")
        typer.echo(f"Ranker-эксперимент не завершён: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Ranker-артефакты: {run_dir}")


@app.command("sequence-download")
def sequence_download(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False)
    ] = Path("configs/sequence_5090.yaml"),
) -> None:
    """Zagruzhaet shirokii 10m-universum dlya GPU-TCN."""
    _console_logging()
    try:
        resolved = load_sequence_config(config)
        manifest = download_sequence_data(resolved)
    except Exception as error:
        logging.getLogger(__name__).exception("Sequence-zagruzka zavershilas oshibkoi")
        typer.echo(f"Sequence-загрузка не завершена: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Sequence-манифест: {manifest}")


@app.command("sequence")
def sequence_experiment(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False)
    ] = Path("configs/sequence_5090.yaml"),
) -> None:
    """Obuchaet causal-TCN i otkryvaet holdout tol'ko posle selection-seal."""
    try:
        from market_lab.sequence.experiment import execute_sequence_experiment

        resolved = load_sequence_config(config)
        run_dir = execute_sequence_experiment(resolved)
    except Exception as error:
        logging.getLogger(__name__).exception("Sequence-eksperiment zavershilsya oshibkoi")
        typer.echo(f"Sequence-эксперимент не завершён: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Sequence-артефакты: {run_dir}")


@app.command("sequence-daily-development")
def sequence_daily_development(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False)
    ] = Path("configs/sequence_5090_daily_v3.yaml"),
) -> None:
    """Obuchaet daily ensemble tol'ko na original30 i ne otkryvaet holdout."""
    try:
        from market_lab.sequence.daily_config import load_daily_experiment_config
        from market_lab.sequence.daily_experiment import (
            execute_daily_development_experiment,
        )

        resolved = load_daily_experiment_config(config)
        run_dir = execute_daily_development_experiment(resolved)
    except Exception as error:
        logging.getLogger(__name__).exception(
            "Daily development-eksperiment zavershilsya oshibkoi"
        )
        typer.echo(f"Daily development не завершён: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Daily development-артефакты: {run_dir}")


@app.command("futures-v6-development")
def futures_v6_development(
    config: Annotated[
        Path, typer.Option("--config", exists=True, dir_okay=False)
    ] = Path("configs/futures_v6_experiment.yaml"),
) -> None:
    """Zapuskaet sealed information-specialist futures OOS bez holdout."""
    try:
        from market_lab.futures.v6_experiment import execute_futures_v6_development

        run_dir = execute_futures_v6_development(config)
    except Exception as error:
        logging.getLogger(__name__).exception(
            "Futures-v6 development eksperiment zavershilsya oshibkoi"
        )
        typer.echo(f"Futures-v6 development не завершён: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Futures-v6 development-артефакты: {run_dir}")


if __name__ == "__main__":
    app()
