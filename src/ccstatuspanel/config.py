from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ccstatuspanel"
CONFIG_PATH = CONFIG_DIR / "config.toml"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ccstatuspanel"

DEFAULT_TOML = """\
# ccstatuspanel configuration

[plan]
tier = "max_5x"          # informational; utilization comes from the API response

[poll]
interval_seconds = 60
stale_after_failures = 3

[ui]
warn_threshold = 0.60     # battery turns amber at this fraction
crit_threshold = 0.85     # battery turns red at this fraction
show_timer_in_tooltip = true
icon_height_px = 22       # logical pixel height; GNOME pins top-bar height ~22
icon_width_px = 72        # logical pixel width; >height gives wider bars

[browser]
# First match wins. Add or remove entries to change discovery order.
order = ["chrome", "chromium", "brave", "vivaldi"]
# Absolute path to a Cookies SQLite file. Useful for snap Chromium:
#   ~/snap/chromium/common/chromium/Default/Cookies
cookie_file_override = ""
"""


@dataclass
class PollConfig:
    interval_seconds: int = 60
    stale_after_failures: int = 3


@dataclass
class UiConfig:
    warn_threshold: float = 0.60
    crit_threshold: float = 0.85
    show_timer_in_tooltip: bool = True
    icon_height_px: int = 22
    icon_width_px: int = 72


@dataclass
class BrowserConfig:
    order: List[str] = field(default_factory=lambda: ["chrome", "chromium", "brave", "vivaldi"])
    cookie_file_override: str = ""


@dataclass
class Config:
    plan_tier: str = "max_5x"
    poll: PollConfig = field(default_factory=PollConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    path: Path = CONFIG_PATH


def ensure_config_exists(path: Path = CONFIG_PATH) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TOML)
    return path


def load_config(path: Path = CONFIG_PATH) -> Config:
    ensure_config_exists(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)

    poll = PollConfig(
        interval_seconds=int(raw.get("poll", {}).get("interval_seconds", 60)),
        stale_after_failures=int(raw.get("poll", {}).get("stale_after_failures", 3)),
    )
    ui = UiConfig(
        warn_threshold=float(raw.get("ui", {}).get("warn_threshold", 0.60)),
        crit_threshold=float(raw.get("ui", {}).get("crit_threshold", 0.85)),
        show_timer_in_tooltip=bool(raw.get("ui", {}).get("show_timer_in_tooltip", True)),
        icon_height_px=int(raw.get("ui", {}).get("icon_height_px", 22)),
        icon_width_px=int(raw.get("ui", {}).get("icon_width_px", 72)),
    )
    browser = BrowserConfig(
        order=list(raw.get("browser", {}).get("order", ["chrome", "chromium", "brave", "vivaldi"])),
        cookie_file_override=str(raw.get("browser", {}).get("cookie_file_override", "")),
    )
    cfg = Config(
        plan_tier=str(raw.get("plan", {}).get("tier", "max_5x")),
        poll=poll,
        ui=ui,
        browser=browser,
        path=path,
    )

    if not (0 <= cfg.ui.warn_threshold <= cfg.ui.crit_threshold <= 1):
        raise ValueError(
            f"Invalid thresholds in {path}: must satisfy 0 <= warn <= crit <= 1 "
            f"(got warn={cfg.ui.warn_threshold}, crit={cfg.ui.crit_threshold})"
        )
    if cfg.poll.interval_seconds < 10:
        raise ValueError(f"poll.interval_seconds must be >=10 (got {cfg.poll.interval_seconds})")

    return cfg
