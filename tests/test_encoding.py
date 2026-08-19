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
    """Proveryaet BOM vezde krome soglasovannogo TOML-isklyucheniya."""
    for path in _tracked_text_files():
        has_bom = path.read_bytes().startswith(b"\xef\xbb\xbf")
        if path.name == "pyproject.toml":
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
