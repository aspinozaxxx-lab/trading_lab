"""Tipy instrumentov i kanonicheskie identifikatory srochnogo rynka."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

DEFAULT_FUTURES_ENGINE = "futures"  # Kod torgovogo dvizhka srochnogo rynka ISS.
DEFAULT_FUTURES_MARKET = "forts"  # Kod rynka futures i options v ISS.
DEFAULT_FUTURES_BOARD = "RFUD"  # Osnovnoi rezhim torgov futures MOEX.
DEFAULT_FUTURES_TIMEZONE = "Europe/Moscow"  # Birzhevaya vremennaya zona MOEX.
ARCHIVE_SECID_SUFFIX_PATTERN = re.compile(  # Suffix arhivnogo aliasa vida _2018.
    r"_\d{4}$"
)
FUTURES_ASSET_REGISTRY = {  # Logical symbol -> oficial'nyi asset_code i prefiks SECID.
    "SI": ("Si", "Si"),
    "RI": ("RTS", "RI"),
    "BR": ("BR", "BR"),
    "MIX": ("MIX", "MX"),
}
FUTURES_ASSET_CODE_REGISTRY = {  # Oficial'nyi asset_code -> logical symbol i prefiks.
    asset_code: (logical_symbol, prefix)
    for logical_symbol, (asset_code, prefix) in FUTURES_ASSET_REGISTRY.items()
}


@dataclass(frozen=True, slots=True)
class FuturesAssetSpec:
    """Opisyvaet odnu seriyu futures i ee stabil'nyi ISS-marshrut."""

    asset_code: str
    logical_symbol: str | None = None
    security_prefix: str | None = None
    engine: str = DEFAULT_FUTURES_ENGINE
    market: str = DEFAULT_FUTURES_MARKET
    primary_board: str = DEFAULT_FUTURES_BOARD
    timezone: str = DEFAULT_FUTURES_TIMEZONE

    def __post_init__(self) -> None:
        """Proveryaet, chto identifikatory bezopasny dlya segmentov URL."""
        if self.asset_code not in FUTURES_ASSET_CODE_REGISTRY:
            raise ValueError(
                f"Neizvestnyi asset_code {self.asset_code!r}; "
                f"razresheny {sorted(FUTURES_ASSET_CODE_REGISTRY)}"
            )
        expected_symbol, expected_prefix = FUTURES_ASSET_CODE_REGISTRY[self.asset_code]
        logical_symbol = self.logical_symbol or expected_symbol
        security_prefix = self.security_prefix or expected_prefix
        if logical_symbol.upper() != expected_symbol:
            raise ValueError(f"asset_code {self.asset_code} ne sootvetstvuet {logical_symbol}")
        if security_prefix.upper() != expected_prefix.upper():
            raise ValueError(f"asset_code {self.asset_code} ne sootvetstvuet {security_prefix}")
        object.__setattr__(self, "logical_symbol", expected_symbol)
        object.__setattr__(self, "security_prefix", expected_prefix)
        for field_name in (
            "asset_code",
            "logical_symbol",
            "security_prefix",
            "engine",
            "market",
            "primary_board",
        ):
            value = getattr(self, field_name)
            if not value or value.strip() != value:
                raise ValueError(f"Pustoe ili nestabil'noe pole FuturesAssetSpec: {field_name}")
            if any(symbol in value for symbol in ("/", "?", "#")):
                raise ValueError(f"Nedopustimyi simvol v {field_name}: {value!r}")

    @classmethod
    def from_symbol(cls, logical_symbol: str) -> FuturesAssetSpec:
        """Stroit proverennyi ISS-spec po torgovomu simbolu Si, RI, BR ili MIX."""
        key = logical_symbol.upper()
        if key not in FUTURES_ASSET_REGISTRY:
            raise ValueError(f"Neizvestnyi logical futures symbol: {logical_symbol!r}")
        asset_code, prefix = FUTURES_ASSET_REGISTRY[key]
        return cls(asset_code=asset_code, logical_symbol=key, security_prefix=prefix)


@dataclass(frozen=True, slots=True)
class FuturesBoardSegment:
    """Svyazyvaet kontrakt s odnim datirovannym segmentom torgovoi doski."""

    canonical_contract_id: str
    secid: str
    board_id: str
    segment_start: date
    segment_end: date

    @property
    def canonical_segment_id(self) -> str:
        """Vozvrashchaet klyuch, kotoryi razdelyaet povtor SECID v arhive."""
        return canonical_board_segment_id(
            self.canonical_contract_id,
            self.board_id,
            self.segment_start,
            self.segment_end,
        )


def canonical_contract_id(asset_code: str, secid: str, expiration_date: date) -> str:
    """Stroit klyuch postavki, obedinyaya arhivnye aliasy odnogo kontrakta."""
    if not asset_code or not secid:
        raise ValueError("asset_code i secid obyazatel'ny dlya kanonicheskogo klyucha")
    normalized_secid = ARCHIVE_SECID_SUFFIX_PATTERN.sub("", secid)
    return f"{asset_code}:{normalized_secid}:{expiration_date.isoformat()}"


def canonical_board_segment_id(
    contract_id: str,
    board_id: str,
    segment_start: date,
    segment_end: date,
) -> str:
    """Stroit odnoznachnyi klyuch istoricheskogo board-segmenta kontrakta."""
    if segment_end < segment_start:
        raise ValueError("Konec board-segmenta ran'she nachala")
    if not contract_id or not board_id:
        raise ValueError("contract_id i board_id obyazatel'ny")
    return (
        f"{contract_id}:{board_id}:{segment_start.isoformat()}:{segment_end.isoformat()}"
    )
