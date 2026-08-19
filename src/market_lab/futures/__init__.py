"""Fundament causal'nogo issledovaniya futures bez skrytoi skleyki kontraktov."""

from typing import TYPE_CHECKING, Any

from market_lab.futures.continuous import build_causal_forward_adjusted_series
from market_lab.futures.iss import (
    FuturesSeriesCatalog,
    futures_boards_url,
    futures_candles_url,
    futures_daily_url,
    futures_open_interest_url,
    futures_series_url,
    parse_futures_boards_payload,
    parse_futures_series_catalog,
    parse_futures_series_payload,
    resolve_canonical_board_segments,
    resolve_canonical_contract_segment,
    resolve_contract_segment,
)
from market_lab.futures.market_data import (
    IssPageCursor,
    parse_futures_candles_payload,
    parse_futures_daily_payload,
    parse_futures_participant_oi_payload,
    parse_iss_page_cursor,
)
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)
from market_lab.futures.roll import (
    RollPlannerConfig,
    normalize_roll_observations,
    plan_causal_rolls,
)
from market_lab.futures.specs import FuturesAssetSpec, FuturesBoardSegment

if TYPE_CHECKING:
    from market_lab.futures.download import (
        FetchedIssTable,
        FuturesAssetDownloadResult,
        FuturesDownloadSettings,
        FuturesIssDownloader,
    )

DOWNLOAD_EXPORTS = frozenset(  # Lazy-imena downloader bez preimporta pri `python -m`.
    {
        "FetchedIssTable",
        "FuturesAssetDownloadResult",
        "FuturesDownloadSettings",
        "FuturesIssDownloader",
        "download_futures_asset",
    }
)


def __getattr__(name: str) -> Any:
    """Lenivo eksportiruet downloader i ne meshaet ego module CLI."""
    if name in DOWNLOAD_EXPORTS:
        from market_lab.futures import download

        return getattr(download, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [  # Publichnyi tipizirovannyi API futures-fundamenta.
    "FuturesAssetSpec",
    "FuturesAssetDownloadResult",
    "FuturesBoardSegment",
    "FuturesDownloadSettings",
    "FuturesIssDownloader",
    "FuturesPortfolioLedgerConfig",
    "FuturesPortfolioLedgerResult",
    "FuturesSeriesCatalog",
    "FetchedIssTable",
    "IssPageCursor",
    "RollPlannerConfig",
    "build_causal_forward_adjusted_series",
    "download_futures_asset",
    "futures_boards_url",
    "futures_candles_url",
    "futures_daily_url",
    "futures_open_interest_url",
    "futures_series_url",
    "normalize_roll_observations",
    "parse_futures_boards_payload",
    "parse_futures_candles_payload",
    "parse_futures_daily_payload",
    "parse_futures_participant_oi_payload",
    "parse_futures_series_catalog",
    "parse_futures_series_payload",
    "parse_iss_page_cursor",
    "plan_causal_rolls",
    "resolve_canonical_board_segments",
    "resolve_canonical_contract_segment",
    "resolve_contract_segment",
    "run_futures_portfolio_ledger",
]
