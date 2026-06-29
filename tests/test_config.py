from pathlib import Path

import pytest

from ccstatuspanel.config import load_config, ensure_config_exists


def test_defaults_round_trip(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    ensure_config_exists(cfg_path)
    assert cfg_path.exists()
    cfg = load_config(cfg_path)
    assert cfg.poll.interval_seconds == 60
    assert cfg.poll.stale_after_failures == 3
    assert cfg.ui.warn_threshold == 0.60
    assert cfg.ui.crit_threshold == 0.85
    assert "chrome" in [b.lower() for b in cfg.browser.order]


def test_load_with_user_overrides(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[poll]
interval_seconds = 120
[ui]
warn_threshold = 0.5
crit_threshold = 0.9
[browser]
order = ["firefox"]
"""
    )
    cfg = load_config(cfg_path)
    assert cfg.poll.interval_seconds == 120
    assert cfg.ui.warn_threshold == 0.5
    assert cfg.ui.crit_threshold == 0.9
    assert cfg.browser.order == ["firefox"]


def test_invalid_thresholds_rejected(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[ui]
warn_threshold = 0.9
crit_threshold = 0.5
"""
    )
    with pytest.raises(ValueError):
        load_config(cfg_path)


def test_invalid_interval_rejected(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[poll]
interval_seconds = 1
"""
    )
    with pytest.raises(ValueError):
        load_config(cfg_path)
