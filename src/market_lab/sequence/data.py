"""Parallel'naya zagruzka 10-minutnyh svechei cherez oficial'nyi MOEX ISS."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import requests

from market_lab.data.moex import parse_moex_payload, validate_market_frame
from market_lab.io_utils import atomic_write_bytes, write_json
from market_lab.sequence.config import SequenceExperimentConfig

LOGGER = logging.getLogger(__name__)  # Logger zagruzchika posledovatel'nostei.
MOEX_INTERVAL_10M = 10  # Chislovoi kod desyatiminutnogo intervala ISS.
PARTITION_CONTEXT_DAYS = 30  # Istoricheskii kontekst pered testom bez ego targetov.


@dataclass(frozen=True)
class DownloadResult:
    """Hranit proveriaemye metadannye odnogo zakeshirovannogo instrumenta."""

    ticker: str
    rows: int
    pages: int
    first_timestamp: str
    last_timestamp: str
    parquet_path: str
    raw_path: str
    sha256: str
    cached: bool


def sequence_cache_path(config: SequenceExperimentConfig, ticker: str) -> Path:
    """Vozvrashchaet datirovannyi put Parquet-kesha odnogo tickera."""
    protocol = config.protocol
    stem = (
        f"{ticker}_{config.universe.board}_10m_"
        f"{protocol.data_start.isoformat()}_{protocol.test_end.isoformat()}.parquet"
    )
    return config.paths.processed_data_dir / "sequence_10m" / stem


def sequence_raw_path(config: SequenceExperimentConfig, ticker: str) -> Path:
    """Vozvrashchaet put gzip-arhiva ishodnyh JSON-stranic."""
    protocol = config.protocol
    stem = (
        f"{ticker}_{config.universe.board}_10m_"
        f"{protocol.data_start.isoformat()}_{protocol.test_end.isoformat()}.jsonl.gz"
    )
    return config.paths.raw_data_dir / "sequence_10m" / stem


def sequence_partition_path(
    config: SequenceExperimentConfig,
    ticker: str,
    partition: Literal["pretest", "test"],
) -> Path:
    """Vozvrashchaet fizicheski razdelennyi put pretest ili test-kesha."""
    filename = sequence_cache_path(config, ticker).name
    return config.paths.processed_data_dir / "sequence_10m" / "partitions" / partition / filename


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 faila potokovo."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno sohranyaet proverennyi DataFrame v Parquet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=True, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _endpoint(config: SequenceExperimentConfig, ticker: str) -> str:
    """Formiruet board-specific endpoint svechei ISS."""
    universe = config.universe
    return (
        "https://iss.moex.com/iss/engines/"
        f"{universe.engine}/markets/{universe.market}/boards/{universe.board}/"
        f"securities/{ticker}/candles.json"
    )


def _request_page(
    session: requests.Session,
    config: SequenceExperimentConfig,
    ticker: str,
    start: int,
) -> dict[str, Any]:
    """Zaprashivaet odnu stranicu s bounded retry i proveriaet JSON."""
    parameters = {
        "from": config.protocol.data_start.isoformat(),
        "till": config.protocol.test_end.isoformat(),
        "interval": MOEX_INTERVAL_10M,
        "start": start,
        "limit": config.download.page_size,
        "iss.meta": "off",
        "iss.only": "candles",
    }
    last_error: Exception | None = None
    for attempt in range(config.download.max_retries + 1):
        try:
            response = session.get(
                _endpoint(config, ticker),
                params=parameters,
                timeout=config.download.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("MOEX vernul ne JSON-obekt")
            candles = payload.get("candles")
            if not isinstance(candles, dict) or not isinstance(candles.get("data"), list):
                raise ValueError("MOEX vernul nekorrektnyi blok candles")
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt >= config.download.max_retries:
                break
            delay = min(2**attempt, 8)
            LOGGER.warning("MOEX %s start=%s: povtor cherez %s s", ticker, start, delay)
            time.sleep(delay)
    raise RuntimeError(f"Ne udalos zagruzit {ticker} start={start}: {last_error}") from last_error


def _cached_result(config: SequenceExperimentConfig, ticker: str) -> DownloadResult | None:
    """Proveryaet gotovyi kesh i vozvrashchaet ego audit-metadannye."""
    parquet_path = sequence_cache_path(config, ticker)
    raw_path = sequence_raw_path(config, ticker)
    if not parquet_path.exists() or not raw_path.exists():
        return None
    frame = validate_market_frame(pd.read_parquet(parquet_path))
    return DownloadResult(
        ticker=ticker,
        rows=len(frame),
        pages=-1,
        first_timestamp=frame.index.min().isoformat(),
        last_timestamp=frame.index.max().isoformat(),
        parquet_path=str(parquet_path),
        raw_path=str(raw_path),
        sha256=_sha256_file(parquet_path),
        cached=True,
    )


def _download_ticker(config: SequenceExperimentConfig, ticker: str) -> DownloadResult:
    """Zagruzhaet vse stranicy tickera i atomarno sohranyaet oba formata."""
    cached = _cached_result(config, ticker)
    if cached is not None:
        LOGGER.info("Sequence cache hit: %s rows=%s", ticker, cached.rows)
        return cached
    session = requests.Session()
    session.headers.update({"User-Agent": "market-lab-research/0.4 (MOEX ISS)"})
    pages: list[dict[str, Any]] = []
    frames: list[pd.DataFrame] = []
    start = 0
    while True:
        payload = _request_page(session, config, ticker, start)
        rows = payload["candles"]["data"]
        if rows:
            pages.append(payload)
            frames.append(parse_moex_payload(payload))
        if not rows or len(rows) < config.download.page_size:
            break
        start += len(rows)
        if config.download.request_pause_seconds:
            time.sleep(config.download.request_pause_seconds)
    session.close()
    if not frames:
        raise ValueError(f"MOEX ne vernul 10m-svechi dlya {ticker}")
    frame = validate_market_frame(pd.concat(frames))
    raw_lines = b"".join(
        json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for page in pages
    )
    raw_path = sequence_raw_path(config, ticker)
    atomic_write_bytes(raw_path, gzip.compress(raw_lines, compresslevel=6, mtime=0))
    parquet_path = sequence_cache_path(config, ticker)
    _atomic_write_parquet(parquet_path, frame)
    result = DownloadResult(
        ticker=ticker,
        rows=len(frame),
        pages=len(pages),
        first_timestamp=frame.index.min().isoformat(),
        last_timestamp=frame.index.max().isoformat(),
        parquet_path=str(parquet_path),
        raw_path=str(raw_path),
        sha256=_sha256_file(parquet_path),
        cached=False,
    )
    LOGGER.info("Sequence downloaded: %s rows=%s pages=%s", ticker, result.rows, result.pages)
    return result


def download_sequence_data(config: SequenceExperimentConfig) -> Path:
    """Parallel'no zagruzhaet oba universuma i zapisivaet svodnyi manifest."""
    config.paths.raw_data_dir.mkdir(parents=True, exist_ok=True)
    config.paths.processed_data_dir.mkdir(parents=True, exist_ok=True)
    tickers = [*config.universe.development, *config.universe.holdout]
    results: list[DownloadResult] = []
    failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=config.download.max_workers) as executor:
        futures = {executor.submit(_download_ticker, config, ticker): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                results.append(future.result())
            except Exception as error:
                failures[ticker] = repr(error)
                LOGGER.exception("Sequence download failed: %s", ticker)
    manifest_path = config.paths.processed_data_dir / "sequence_10m" / "manifest.json"
    payload = {
        "source": "MOEX ISS",
        "endpoint_kind": "anonymous official candles API",
        "requested_tickers": tickers,
        "results": [result.__dict__ for result in sorted(results, key=lambda item: item.ticker)],
        "failures": failures,
    }
    write_json(manifest_path, payload)
    if failures:
        raise RuntimeError(f"Ne zagruzhena chast' universuma: {failures}")
    partition_sequence_data(config)
    return manifest_path


def partition_sequence_data(config: SequenceExperimentConfig) -> Path:
    """Fizicheski otdelyaet pretest ot test s dovol'nym causal-kontekstom."""
    rows: list[dict[str, object]] = []
    pretest_end = pd.Timestamp(config.protocol.calibration_end, tz="UTC") + pd.Timedelta(
        days=1
    ) - pd.Timedelta(nanoseconds=1)
    context_start = pd.Timestamp(
        config.protocol.test_start - timedelta(days=PARTITION_CONTEXT_DAYS),
        tz="UTC",
    )
    tickers = [*config.universe.development, *config.universe.holdout]
    for ticker in tickers:
        source = sequence_cache_path(config, ticker)
        if not source.exists():
            raise FileNotFoundError(f"Net polnogo sequence-kesha dlya {ticker}: {source}")
        frame = validate_market_frame(pd.read_parquet(source))
        partitions = {
            "pretest": frame.loc[frame.index <= pretest_end],
            "test": frame.loc[frame.index >= context_start],
        }
        for partition, part in partitions.items():
            if part.empty:
                raise ValueError(f"Pustaya {partition}-particiya dlya {ticker}")
            target = sequence_partition_path(config, ticker, partition)
            _atomic_write_parquet(target, part)
            rows.append(
                {
                    "ticker": ticker,
                    "partition": partition,
                    "rows": len(part),
                    "first_timestamp": part.index.min(),
                    "last_timestamp": part.index.max(),
                    "path": str(target),
                    "sha256": _sha256_file(target),
                }
            )
    manifest_path = (
        config.paths.processed_data_dir / "sequence_10m" / "partitions" / "manifest.json"
    )
    write_json(
        manifest_path,
        {
            "created_from": "full immutable MOEX cache",
            "pretest_end": pretest_end,
            "test_context_start": context_start,
            "context_days": PARTITION_CONTEXT_DAYS,
            "partitions": rows,
        },
    )
    return manifest_path
