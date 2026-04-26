from __future__ import annotations

import argparse
import logging
import signal
import sys

from . import __version__
from .config import load_config
from .installer import install_desktop_entries, uninstall_desktop_entries
from .notify import notify
from .poller import Poller
from .tray import Tray

log = logging.getLogger("ccstatuspanel")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ccstatuspanel", description="Claude usage tray indicator")
    p.add_argument("--version", action="version", version=f"ccstatuspanel {__version__}")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    p.add_argument("--install", action="store_true",
                   help="Write XDG desktop entry + autostart unit and exit")
    p.add_argument("--uninstall", action="store_true",
                   help="Remove XDG desktop entry + autostart unit and exit")
    return p


def _on_stale(error_msg: str) -> None:
    notify(
        "claude.ai usage unavailable",
        f"Re-login to claude.ai may be required.\n{error_msg[:160]}",
        urgency="normal",
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _setup_logging(args.verbose)

    if args.install:
        a, b = install_desktop_entries()
        print(f"Wrote {a}\nWrote {b}")
        return 0
    if args.uninstall:
        removed = uninstall_desktop_entries()
        if removed:
            for p in removed:
                print(f"Removed {p}")
        else:
            print("No desktop entries found.")
        return 0

    try:
        config = load_config()
    except Exception as e:
        log.error("Failed to load config: %s", e)
        return 2

    tray_holder: dict = {}

    def _on_snapshot(snap):
        tray = tray_holder.get("tray")
        if tray:
            tray.update_snapshot(snap)

    def _on_refresh():
        poller = tray_holder.get("poller")
        if poller:
            poller.trigger_now()

    def _on_quit():
        poller = tray_holder.get("poller")
        if poller:
            poller.stop()

    poller = Poller(config, on_snapshot=_on_snapshot, on_stale=_on_stale)
    tray = Tray(config, on_refresh=_on_refresh, on_quit=_on_quit)
    tray_holder["poller"] = poller
    tray_holder["tray"] = tray

    def _handle_signal(signum, _frame):
        log.info("Caught signal %s, shutting down", signum)
        poller.stop()
        tray.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    poller.start()
    try:
        tray.run()  # blocks
    finally:
        poller.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
