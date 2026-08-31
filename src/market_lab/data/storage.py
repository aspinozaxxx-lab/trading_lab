"""Lokalnyi kesh syryh i normalizovannyh rynochnyh dannyh."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pandas as pd

from market_lab.config import AppConfig
from market_lab.data.moex import MarketDataBundle, validate_market_frame
from market_lab.io_utils import TEXT_ENCODING, write_json


def cache_stem(config: AppConfig) -> str:
    """Formiruet stabilnoe imya nabora bez absolyutnyh putei."""
    data = config.data
    return (
        f"{data.instrument}_{data.board}_{data.timeframe}_"
        f"{data.start.isoformat()}_{data.end.isoformat()}"
    )


def processed_path(config: AppConfig) -> Path:
    """Vozvrashchaet put normalizovannogo Parquet-kesha."""
    return config.paths.processed_data_dir / f"{cache_stem(config)}.parquet"


def _frame_fingerprint(frame: pd.DataFrame) -> str:
    """Vychislyaet SHA-256 po stabilnym hash-znacheniyam strok."""
    hashed = pd.util.hash_pandas_object(frame, index=True).values.tobytes()
    return hashlib.sha256(hashed).hexdigest()


def save_market_data(config: AppConfig, bundle: MarketDataBundle) -> Path:
    """Atomarno sohranyaet syroi JSON, metadannye i Parquet."""
    raw_dir = config.paths.raw_data_dir
    processed_dir = config.paths.processed_data_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    stem = cache_stem(config)
    raw_document = {"pages": bundle.raw_pages}
    write_json(raw_dir / f"{stem}.json", raw_document)
    target = processed_path(config)
    with tempfile.NamedTemporaryFile(
        prefix=f".{target.name}.", suffix=".parquet", dir=processed_dir, delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        bundle.frame.to_parquet(temporary, index=True)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    metadata = {
        **bundle.metadata,
        "fingerprint_sha256": _frame_fingerprint(bundle.frame),
        "processed_path": str(target),
    }
    write_json(processed_dir / f"{stem}.metadata.json", metadata)
    return target


def load_cached_data(config: AppConfig) -> MarketDataBundle:
    """Chitaet proverennyi Parquet i ego metadannye bez seti."""
    target = processed_path(config)
    if not target.exists():
        raise FileNotFoundError(
            f"Kesh ne naiden: {target}. Snachala vypolnite market-lab download."
        )
    frame = validate_market_frame(pd.read_parquet(target))
    metadata_path = target.with_name(f"{cache_stem(config)}.metadata.json")
    if metadata_path.exists():
        with metadata_path.open("r", encoding=TEXT_ENCODING) as stream:
            metadata = json.load(stream)
    else:
        metadata = {"source": "cache", "rows": len(frame), "processed_path": str(target)}
    return MarketDataBundle(frame=frame, raw_pages=[], metadata=metadata)
