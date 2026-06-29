from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)


def notify(summary: str, body: str = "", *, urgency: str = "normal") -> None:
    """Show a desktop notification. No-op (with log) if notify-send is missing."""
    binary = shutil.which("notify-send")
    if binary is None:
        log.info("notify-send not found; would have notified: %s — %s", summary, body)
        return
    try:
        subprocess.run(
            [binary, "-a", "ccstatuspanel", "-u", urgency, summary, body],
            check=False,
            timeout=5,
        )
    except Exception as e:
        log.warning("notify-send failed: %s", e)
