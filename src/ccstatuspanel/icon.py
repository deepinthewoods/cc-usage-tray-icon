"""Render a system-tray icon: two stacked battery indicators.

Top  bar = 5-hour session usage.
Bottom bar = 7-day weekly usage.
The countdown timer lives in the tooltip, not the icon.
"""
from __future__ import annotations

from typing import Tuple

from PIL import Image, ImageDraw

from .config import UiConfig
from .models import State, UsageSnapshot


# Material-ish colours that read well on dark and light top bars.
_OK = (76, 175, 80, 255)        # green
_WARN = (255, 167, 38, 255)     # amber
_CRIT = (229, 57, 53, 255)      # red
_OUTLINE_LIGHT = (220, 220, 220, 255)
_OUTLINE_DARK = (40, 40, 40, 255)
_STALE = (140, 140, 140, 200)


def _fill_for(pct: float, ui: UiConfig) -> Tuple[int, int, int, int]:
    if pct >= ui.crit_threshold:
        return _CRIT
    if pct >= ui.warn_threshold:
        return _WARN
    return _OK


def _draw_bar(
    draw: ImageDraw.ImageDraw,
    bbox: Tuple[int, int, int, int],
    pct: float,
    fill: Tuple[int, int, int, int],
    outline: Tuple[int, int, int, int],
    *,
    stale: bool,
    stroke_w: int,
) -> None:
    """Draw one horizontal usage bar within bbox. bbox = (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = bbox

    if stale:
        _draw_dashed_rect(draw, (x0, y0, x1, y1), outline, stroke_w)
        return

    draw.rectangle((x0, y0, x1, y1), outline=outline, width=stroke_w)

    gutter = stroke_w
    inner_x0 = x0 + gutter
    inner_y0 = y0 + gutter
    inner_x1 = x1 - gutter
    inner_y1 = y1 - gutter
    inner_w = inner_x1 - inner_x0
    if inner_w <= 0:
        return
    fill_w = int(inner_w * max(0.0, min(1.0, pct)))
    if fill_w > 0:
        draw.rectangle((inner_x0, inner_y0, inner_x0 + fill_w, inner_y1), fill=fill)


def _draw_dashed_rect(
    draw: ImageDraw.ImageDraw,
    bbox: Tuple[int, int, int, int],
    color: Tuple[int, int, int, int],
    width: int,
    dash: int = 3,
    gap: int = 2,
) -> None:
    x0, y0, x1, y1 = bbox

    def _hline(y: int) -> None:
        x = x0
        while x < x1:
            x_end = min(x + dash, x1)
            draw.line((x, y, x_end, y), fill=color, width=width)
            x = x_end + gap

    def _vline(x: int) -> None:
        y = y0
        while y < y1:
            y_end = min(y + dash, y1)
            draw.line((x, y, x, y_end), fill=color, width=width)
            y = y_end + gap

    _hline(y0)
    _hline(y1)
    _vline(x0)
    _vline(x1)


def render_icon(
    snapshot: UsageSnapshot,
    ui: UiConfig,
    size_px: int | tuple[int, int] = 22,
    *,
    dark_background: bool = True,
) -> Image.Image:
    """Render the icon at logical size, internally drawing at 2x for crispness.

    `size_px` is either an int (square icon) or `(width, height)` for a wider
    indicator. GNOME's top bar pins the height to ~22 px and lets width vary,
    so passing e.g. (44, 22) gives roughly twice the horizontal space.
    """
    if isinstance(size_px, int):
        out_w = out_h = size_px
    else:
        out_w, out_h = size_px

    scale = 2
    w, h = out_w * scale, out_h * scale
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    outline = _OUTLINE_LIGHT if dark_background else _OUTLINE_DARK
    stale = snapshot.state == State.STALE
    if stale:
        outline = _STALE

    # Layout: two horizontal batteries stacked vertically with a small gap.
    margin_x = max(2, w // 12)
    margin_y = max(2, h // 12)
    gap = max(2, h // 14)
    bar_h = (h - 2 * margin_y - gap) // 2
    stroke = max(2, scale)

    top_bbox = (margin_x, margin_y, w - margin_x, margin_y + bar_h)
    bot_bbox = (margin_x, margin_y + bar_h + gap, w - margin_x, h - margin_y)

    sess_fill = _fill_for(snapshot.session_pct, ui)
    week_fill = _fill_for(snapshot.week_pct, ui)

    _draw_bar(draw, top_bbox, snapshot.session_pct, sess_fill, outline, stale=stale, stroke_w=stroke)
    _draw_bar(draw, bot_bbox, snapshot.week_pct, week_fill, outline, stale=stale, stroke_w=stroke)

    # Downscale to logical size with alpha-aware filter.
    return img.resize((out_w, out_h), Image.LANCZOS)
