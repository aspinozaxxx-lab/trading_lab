"""Proverka UTF-8 BOM i otsutstviya tipichnyh krakozyabrov."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren proverki kodirovki.
TEXT_SUFFIXES = {  # Tekstovye rasshireniya dlya proverki kodirovki.
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".csv",
    ".txt",
    ".lock",
    ".sha256",
}
EXCLUDED_DIRECTORIES = {  # Generiruemye katalogi, ne yavlyayushchiesya ishodnikami.
    ".venv",
    ".pytest_cache",
    ".pytest_tmp",
    ".ruff_cache",
    ".cache",
    "data",
    "runs",
}
MOJIBAKE_MARKERS = (  # Tipichnye sledy nevernoi dekodirovki.
    "\ufffd",
    "\u00d0",
    "\u00d1",
    "\u0420\u045f",
    "\u0420\u040e",
)
BYTE_SEALED_NO_BOM_EXCEPTIONS = {  # Identity-pinned files cannot be rewritten post-outcome.
    "configs/futures_v10_triangular_relative_value.sha256",
    "configs/futures_v10_triangular_relative_value.yaml",
    "configs/futures_v11_liquidity_buffered_open.sha256",
    "configs/futures_v11_liquidity_buffered_open.yaml",
    "configs/futures_v9_event_timing_hybrid.sha256",
    "configs/futures_v9_event_timing_hybrid.yaml",
    "configs/futures_v9_intraday_timing.sha256",
    "configs/futures_v9_intraday_timing.yaml",
    "configs/futures_v9_intraday_timing_v2.sha256",
    "configs/futures_v9_intraday_timing_v2.yaml",
    "configs/futures_v9_structural_execution.sha256",
    "configs/market_graph_v2_long_only.sha256",
    "configs/market_graph_v2_long_only.yaml",
    "scripts/analyze_futures_v9_intraday_scores.py",
    "scripts/build_futures_v9_intraday_timing_tensor.py",
    "scripts/doc_llm_deploy/README.md",
    "scripts/doc_llm_deploy/doc_extract.py",
    "scripts/doc_llm_deploy/download_model.py",
    "scripts/doc_llm_deploy/make_smoke_page.py",
    "scripts/run_futures_v9_event_timing_hybrid.py",
    "scripts/run_futures_v9_intraday_timing.py",
    "scripts/run_futures_v9_intraday_timing_v2.py",
    "scripts/run_futures_v9_structural_execution.py",
    "scripts/run_futures_v9_structural_robustness.py",
    "scripts/run_market_graph_v1.py",
    "scripts/run_market_graph_v2_long_only.py",
    "src/market_lab/futures_v8/admission_build.py",
    "src/market_lab/futures_v9_event_timing_hybrid.py",
    "src/market_lab/futures_v9_intraday_timing/__init__.py",
    "src/market_lab/futures_v9_intraday_timing/data.py",
    "src/market_lab/futures_v9_intraday_timing/experiment.py",
    "src/market_lab/futures_v9_intraday_timing/experiment_v2.py",
    "src/market_lab/futures_v9_intraday_timing/model.py",
    "src/market_lab/futures_v9_structural/__init__.py",
    "src/market_lab/futures_v9_structural/execution.py",
    "src/market_lab/futures_v9_structural/robustness.py",
    "src/market_lab/futures_v9_structural/run.py",
    "src/market_lab/futures_v9_structural/structural.py",
    "src/market_lab/market_graph_v1/__init__.py",
    "src/market_lab/market_graph_v1/data.py",
    "src/market_lab/market_graph_v1/experiment.py",
    "src/market_lab/market_graph_v1/model.py",
    "src/market_lab/market_graph_v1/portfolio.py",
    "src/market_lab/market_graph_v2/__init__.py",
    "src/market_lab/market_graph_v2/experiment.py",
    "tests/test_futures_v9_event_timing_hybrid.py",
    "tests/test_futures_v9_structural.py",
    "tests/test_futures_v9_structural_execution.py",
    "tests/test_futures_v9_structural_robustness.py",
    "tests/test_market_graph_v1.py",
    "tests/test_market_graph_v2.py",
}


def _tracked_text_files() -> list[Path]:
    """Sobiraet tekstovye ishodniki bez okruzheniya i artefaktov."""
    files: list[Path] = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(PROJECT_ROOT).parts
        if any(
            part in EXCLUDED_DIRECTORIES or part.endswith(".egg-info")
            for part in relative_parts
        ):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name == ".gitignore":
            files.append(path)
    return files


def test_all_text_files_have_expected_bom() -> None:
    """Proveryaet BOM, ne perepisyvaya perechislennye byte-sealed identity."""
    for path in _tracked_text_files():
        has_bom = path.read_bytes().startswith(b"\xef\xbb\xbf")
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if path.name == "pyproject.toml" or relative in BYTE_SEALED_NO_BOM_EXCEPTIONS:
            assert not has_bom, path
        else:
            assert has_bom, path


def test_text_files_do_not_contain_mojibake() -> None:
    """Proveryaet otsutstvie tipichnyh posledovatelnostei krakozyabrov."""
    for path in _tracked_text_files():
        encoding = "utf-8" if path.name == "pyproject.toml" else "utf-8-sig"
        content = path.read_text(encoding=encoding)
        for marker in MOJIBAKE_MARKERS:
            assert marker not in content, f"{marker!r} found in {path}"
