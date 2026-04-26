from datetime import datetime, timedelta, timezone

from PIL import Image

from ccstatuspanel.config import UiConfig
from ccstatuspanel.icon import render_icon
from ccstatuspanel.models import State, UsageSnapshot


UI = UiConfig()


def _snap(session: float = 0.0, week: float = 0.0, state: State = State.OK) -> UsageSnapshot:
    return UsageSnapshot(
        session_pct=session,
        week_pct=week,
        state=state,
        resets_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )


def test_render_returns_correct_size_image():
    img = render_icon(_snap(0.5, 0.5), UI, size_px=22)
    assert isinstance(img, Image.Image)
    assert img.size == (22, 22)
    assert img.mode == "RGBA"


def test_render_at_higher_size_works():
    img = render_icon(_snap(0.5, 0.5), UI, size_px=64)
    assert img.size == (64, 64)


def test_filled_icon_has_more_opaque_pixels_than_empty():
    empty = render_icon(_snap(0.0, 0.0), UI, size_px=64)
    full = render_icon(_snap(1.0, 1.0), UI, size_px=64)
    empty_pixels = sum(1 for px in empty.getdata() if px[3] > 0)
    full_pixels = sum(1 for px in full.getdata() if px[3] > 0)
    assert full_pixels > empty_pixels


def test_stale_icon_renders_without_error():
    img = render_icon(_snap(0.0, 0.0, state=State.STALE), UI, size_px=22)
    assert img.size == (22, 22)


def test_critical_threshold_changes_color():
    """At >= crit_threshold the fill should become red — verify by sampling pixels."""
    ok_img = render_icon(_snap(0.10, 0.10), UI, size_px=128)
    crit_img = render_icon(_snap(0.95, 0.95), UI, size_px=128)

    def _dominant_red_minus_green(img: Image.Image) -> int:
        # Sum (R - G) over opaque pixels — red fills push positive, green fills negative.
        total = 0
        for r, g, _b, a in img.getdata():
            if a > 100:
                total += (r - g)
        return total

    assert _dominant_red_minus_green(crit_img) > _dominant_red_minus_green(ok_img)
