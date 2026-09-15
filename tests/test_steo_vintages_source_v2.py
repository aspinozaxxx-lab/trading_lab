"""Directory ownership and no-overwrite checks using synthetic temporary files."""

import pytest

from market_lab.futures import steo_vintages_source_v2 as source


@pytest.mark.skipif(not hasattr(source.os, "getuid"), reason="POSIX service ownership")
def test_owned_empty_leaf_only(tmp_path):
    source.empty_leaf(tmp_path.resolve())
    (tmp_path / "existing.json").touch()
    with pytest.raises(ValueError, match="empty"):
        source.empty_leaf(tmp_path.resolve())


def test_absent_leaf_is_not_silently_created(tmp_path):
    with pytest.raises(ValueError, match="unprepared"):
        source.empty_leaf(tmp_path / "absent")
