"""Scales the whole UI with the screen resolution, so Lintask covers about the same
share of a 720p screen as of a 4K or 8K one.

The layout is designed for 1080p. Qt can only take a scale factor before the
application object exists, so a short-lived QGuiApplication reads the screens first;
each screen then gets its own factor via QT_SCREEN_SCALE_FACTORS (moving the window
to another screen rescales it). The desktop's own scaling is already part of the
logical screen size, so a 4K screen at 200 % desktop scaling gets no extra factor."""
from __future__ import annotations

import os

REFERENCE_HEIGHT = 1080
MIN_FACTOR = 0.75   # below this the text gets unreadable on small screens
MAX_FACTOR = 4.0
STEP = 0.25         # coarse steps keep lines and icons sharp
CHOICES = [0, 75, 100, 125, 150, 175, 200, 250, 300, 400]  # 0 = automatic

_USER_VARIABLES = ("QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS")
_HEADLESS = ("offscreen", "minimal", "vnc")


def factor_for(width: int, height: int) -> float:
    """Factor for a screen of this logical size; the short side counts, so a portrait
    or ultrawide screen is treated like its landscape 16:9 counterpart."""
    short_side = min(width, height)
    if short_side <= 0:
        return 1.0
    raw = short_side / REFERENCE_HEIGHT
    stepped = round(raw / STEP) * STEP
    return max(MIN_FACTOR, min(MAX_FACTOR, stepped))


def _format(value: float) -> str:
    return f"{value:g}"


def screen_factors_variable(screens: list[tuple[str, int, int]]) -> str:
    """QT_SCREEN_SCALE_FACTORS value for (name, logical width, logical height) tuples."""
    return ";".join(f"{name}={_format(factor_for(w, h))}" for name, w, h in screens if name)


def _probe_screens() -> list[tuple[str, int, int]]:
    from PySide6.QtGui import QGuiApplication

    probe = QGuiApplication(["lintask-screen-probe"])
    try:
        return [(s.name(), s.geometry().width(), s.geometry().height())
                for s in probe.screens()]
    finally:
        probe.shutdown()
        del probe


def apply(percent: int) -> None:
    """Sets the Qt scale variables; call before QApplication is created.
    `percent` 0 means automatic, anything else a fixed factor on top of the desktop's
    own scaling. Factors the user exported themselves always win."""
    if any(os.environ.get(name) for name in _USER_VARIABLES):
        return
    if percent:
        if percent != 100:
            os.environ["QT_SCALE_FACTOR"] = _format(percent / 100)
        return
    platform = os.environ.get("QT_QPA_PLATFORM", "").split(":")[0]
    if platform in _HEADLESS:
        return
    try:
        screens = _probe_screens()
    except Exception:  # noqa: BLE001 - no display or a broken platform: keep Qt's default
        return
    if any(factor_for(w, h) != 1.0 for _name, w, h in screens):
        os.environ["QT_SCREEN_SCALE_FACTORS"] = screen_factors_variable(screens)
