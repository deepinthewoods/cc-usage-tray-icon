"""Write XDG desktop entry + autostart unit so the tray launches on login."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

DESKTOP_FILE_NAME = "ccstatuspanel.desktop"

_DESKTOP_TEMPLATE = """[Desktop Entry]
Type=Application
Name=ccstatuspanel
Comment=Claude usage status indicator
Exec={exec_cmd}
Icon=utilities-system-monitor
Terminal=false
Categories=Utility;Monitor;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _resolve_exec() -> str:
    # Prefer pipx-installed binary on PATH; fall back to python -m for dev installs.
    for name in ("ccstatuspanel",):
        located = shutil.which(name)
        if located:
            return located
    return f"{sys.executable} -m ccstatuspanel.app"


def install_desktop_entries() -> tuple[Path, Path]:
    exec_cmd = _resolve_exec()
    contents = _DESKTOP_TEMPLATE.format(exec_cmd=exec_cmd)

    apps_dir = _xdg_data_home() / "applications"
    autostart_dir = _xdg_config_home() / "autostart"
    apps_dir.mkdir(parents=True, exist_ok=True)
    autostart_dir.mkdir(parents=True, exist_ok=True)

    apps_path = apps_dir / DESKTOP_FILE_NAME
    auto_path = autostart_dir / DESKTOP_FILE_NAME
    apps_path.write_text(contents)
    auto_path.write_text(contents)
    apps_path.chmod(0o644)
    auto_path.chmod(0o644)
    return apps_path, auto_path


def uninstall_desktop_entries() -> list[Path]:
    removed = []
    for p in (
        _xdg_data_home() / "applications" / DESKTOP_FILE_NAME,
        _xdg_config_home() / "autostart" / DESKTOP_FILE_NAME,
    ):
        if p.exists():
            p.unlink()
            removed.append(p)
    return removed
