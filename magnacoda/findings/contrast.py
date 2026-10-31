from __future__ import annotations

import colorsys
import re

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


def _parse_hex(value: str) -> tuple[int, int, int] | None:
    match = _HEX_RE.match(value.strip())
    if not match:
        return None
    digits = match.group(1)
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def _to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    lighter, darker = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _with_lightness(hls: tuple[float, float, float], lightness: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(hls[0], lightness, hls[2])
    return round(r * 255), round(g * 255), round(b * 255)


def _closest_passing(
    hls: tuple[float, float, float], bg: tuple[int, int, int], target: float, toward: float
) -> tuple[int, int, int] | None:
    """Smallest lightness move from the original towards `toward` (0=black, 1=white) that passes."""
    if contrast_ratio(_with_lightness(hls, toward), bg) < target:
        return None
    low, high = hls[1], toward
    for _ in range(30):
        mid = (low + high) / 2
        if contrast_ratio(_with_lightness(hls, mid), bg) >= target:
            high = mid
        else:
            low = mid
    return _with_lightness(hls, high)


def suggest_passing_color(fg_hex: str, bg_hex: str, target: float) -> str | None:
    """Nearest shade of the foreground (same hue and saturation) meeting `target` contrast on bg."""
    fg, bg = _parse_hex(fg_hex), _parse_hex(bg_hex)
    if fg is None or bg is None:
        return None
    hls = colorsys.rgb_to_hls(fg[0] / 255, fg[1] / 255, fg[2] / 255)
    candidates = [
        c for c in (_closest_passing(hls, bg, target, 0.0), _closest_passing(hls, bg, target, 1.0)) if c
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda c: abs(colorsys.rgb_to_hls(*(v / 255 for v in c))[1] - hls[1]))
    return _to_hex(best)


def parse_expected_ratio(value: object) -> float | None:
    """axe reports the requirement as a string like '4.5:1'."""
    try:
        return float(str(value).split(":")[0])
    except ValueError:
        return None
