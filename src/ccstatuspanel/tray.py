from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import webbrowser
from typing import Callable, Optional

import pystray

from .config import Config
from .icon import render_icon
from .models import State, UsageSnapshot

log = logging.getLogger(__name__)

_DASHBOARD_URL = "https://claude.ai/settings/usage"


def _format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "—"
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def _format_tooltip(snap: UsageSnapshot, ui_show_timer: bool) -> str:
    # Use ASCII-only separators — pystray's X11 fallback backend speaks Latin-1
    # for WM_NAME and chokes on em-dash / middle-dot.
    if snap.state == State.STALE:
        head = "ccstatuspanel - stale"
        if snap.error_msg:
            return f"{head}\n{snap.error_msg[:140]}"
        return head
    parts = [
        f"Session {int(round(snap.session_pct * 100))}%",
        f"Week {int(round(snap.week_pct * 100))}%",
    ]
    if ui_show_timer and snap.resets_at:
        parts.append(f"Resets in {_format_duration(snap.time_to_reset_seconds())}")
    suffix = " (degraded)" if snap.state == State.DEGRADED else ""
    return " | ".join(parts) + suffix


def _open_dashboard(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
    try:
        webbrowser.open(_DASHBOARD_URL)
    except Exception as e:
        log.warning("Failed to open dashboard: %s", e)


def _open_config(config_path: str) -> Callable[[pystray.Icon, pystray.MenuItem], None]:
    def _act(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        binary = shutil.which("xdg-open")
        if binary:
            try:
                subprocess.Popen([binary, config_path])
                return
            except Exception as e:
                log.warning("xdg-open failed for %s: %s", config_path, e)
        try:
            webbrowser.open(f"file://{config_path}")
        except Exception as e:
            log.warning("Failed to open config %s: %s", config_path, e)
    return _act


class Tray:
    """pystray wrapper. Owns the icon image + tooltip.

    update_snapshot() is thread-safe and is called from the poller.
    Internally runs a tick thread to refresh the countdown text once per minute.
    """

    def __init__(self, config: Config, on_refresh: Callable[[], None], on_quit: Callable[[], None]) -> None:
        self._config = config
        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self._lock = threading.Lock()
        self._snapshot = UsageSnapshot(state=State.STALE, error_msg="initialising…")
        self._stop = threading.Event()
        self._tick_thread: Optional[threading.Thread] = None

        # _noop is invoked when the user clicks one of the status lines;
        # it intentionally does nothing, but its presence ensures pystray's
        # AppIndicator backend renders the item (pure-label items can be
        # hidden by some GNOME extensions).
        menu = pystray.Menu(
            pystray.MenuItem(self._session_text, self._noop),
            pystray.MenuItem(self._week_text, self._noop),
            pystray.MenuItem(self._reset_text, self._noop),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Refresh now", self._refresh),
            pystray.MenuItem("Open dashboard", _open_dashboard),
            pystray.MenuItem("Open config", _open_config(str(self._config.path))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )
        self._icon = pystray.Icon(
            "ccstatuspanel",
            icon=render_icon(self._snapshot, self._config.ui, self._icon_size()),
            title=_format_tooltip(self._snapshot, self._config.ui.show_timer_in_tooltip),
            menu=menu,
        )

    def _icon_size(self) -> tuple[int, int]:
        return (self._config.ui.icon_width_px, self._config.ui.icon_height_px)

    def _noop(self, _icon, _item) -> None:
        pass

    def _session_text(self, _item) -> str:
        with self._lock:
            snap = self._snapshot
        if snap.state == State.STALE:
            return "Session: stale"
        return f"Session: {int(round(snap.session_pct * 100))}%"

    def _week_text(self, _item) -> str:
        with self._lock:
            snap = self._snapshot
        if snap.state == State.STALE:
            return "Week: stale"
        return f"Week: {int(round(snap.week_pct * 100))}%"

    def _reset_text(self, _item) -> str:
        with self._lock:
            snap = self._snapshot
        if snap.state == State.STALE or snap.resets_at is None:
            return "Resets in: —"
        return f"Resets in: {_format_duration(snap.time_to_reset_seconds())}"

    def update_snapshot(self, snap: UsageSnapshot) -> None:
        with self._lock:
            self._snapshot = snap
        self._refresh_icon_and_title()

    def _refresh_icon_and_title(self) -> None:
        with self._lock:
            snap = self._snapshot
        try:
            self._icon.icon = render_icon(snap, self._config.ui, self._icon_size())
            self._icon.title = _format_tooltip(snap, self._config.ui.show_timer_in_tooltip)
            # Force the menu to redraw so the live status line picks up new values
            # the next time the user opens it.
            try:
                self._icon.update_menu()
            except Exception:
                pass
        except Exception as e:
            log.warning("Failed to update tray icon/title: %s", e)

    def _refresh(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        try:
            self._on_refresh()
        except Exception as e:
            log.warning("Refresh callback failed: %s", e)

    def _quit(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        log.info("Quit requested via tray menu")
        self._stop.set()
        try:
            self._icon.stop()
        finally:
            try:
                self._on_quit()
            except Exception as e:
                log.warning("Quit callback failed: %s", e)

    def _tick_loop(self) -> None:
        # Refresh tooltip every 30s so the countdown text stays current
        # without re-rendering the icon image.
        while not self._stop.wait(30):
            with self._lock:
                snap = self._snapshot
            try:
                self._icon.title = _format_tooltip(snap, self._config.ui.show_timer_in_tooltip)
            except Exception as e:
                log.debug("Tooltip refresh failed: %s", e)

    def run(self) -> None:
        self._tick_thread = threading.Thread(target=self._tick_loop, name="ccstatuspanel-tick", daemon=True)
        self._tick_thread.start()
        self._icon.run()  # blocks until self._icon.stop()
        self._stop.set()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._icon.stop()
        except Exception:
            pass
