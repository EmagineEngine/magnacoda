"""Colors for the pager, after old monitors (amber, green, light blue, paper white) and print, each
on a background of its own, so they read well whatever theme the terminal uses. A scheme may have a
third color, an accent, for the title row, headings, links and the key hints (none has one now).
"default" sends no colors at all, which leaves the terminal's own. Standard library only.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT = "default"


@dataclass(frozen=True)
class Scheme:
    name: str
    description: str
    fg: str = ""  # "#rrggbb"; empty for default
    bg: str = ""
    fg256: int = 0  # the nearest of the 256 colors, for terminals without full color
    bg256: int = 0
    accent: str = ""  # the title row's color; empty: the text color (one-color monitors)
    accent256: int = 0
    code: str = ""  # code's background; empty: worked out from fg and bg (code_colors)
    code256: int = 0


SCHEMES = (
    Scheme(DEFAULT, "your terminal's own colors"),
    Scheme("amber", "orange on black, like the old amber monitors", "#e09a00", "#000000", 172, 16),
    Scheme("green", "green on black, the classic green screen", "#2fd85a", "#000000", 41, 16),
    Scheme(
        "blue", "light blue on dark blue, as in old-school word processing", "#8ccfff", "#061530", 117, 17
    ),
    Scheme("paper", "warm white on near black, like paper-white monitors", "#e8e4d8", "#101010", 254, 233),
    Scheme("print", "near black on warm white, like a printed page", "#101010", "#e8e4d8", 233, 254),
)
NAMES = tuple(scheme.name for scheme in SCHEMES)


def scheme(name: str) -> Scheme:
    """The scheme by name; an unknown name gives the default."""
    return next((s for s in SCHEMES if s.name == name), SCHEMES[0])


def enabled(env: Mapping[str, str] | None = None) -> bool:
    """Colors are left out when NO_COLOR is set (no-color.org)."""
    env = os.environ if env is None else env
    return not env.get("NO_COLOR")


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def codes(name: str | Scheme, env: Mapping[str, str] | None = None) -> str:
    """The codes that set this scheme's text and background colors; "" for default or with NO_COLOR.

    Full color where the terminal says it has it (COLORTERM=truecolor or 24bit), else the 256 colors.
    """
    env = os.environ if env is None else env
    chosen = name if isinstance(name, Scheme) else scheme(name)
    if chosen.name == DEFAULT or not enabled(env):
        return ""
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        (r, g, b), (br, bgr, bb) = _rgb(chosen.fg), _rgb(chosen.bg)
        return f"\x1b[38;2;{r};{g};{b};48;2;{br};{bgr};{bb}m"
    return f"\x1b[38;5;{chosen.fg256};48;5;{chosen.bg256}m"


def accent_codes(name: str | Scheme, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """The scheme's third color, for the title row, headings and links, and its reverse (the
    background color on the accent), for the key hints and the link Tab is on; ("", "") when it has
    none (or with NO_COLOR), and those take the text color."""
    env = os.environ if env is None else env
    chosen = name if isinstance(name, Scheme) else scheme(name)
    if not chosen.accent or not enabled(env):
        return "", ""
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        accent, back = ";".join(map(str, _rgb(chosen.accent))), ";".join(map(str, _rgb(chosen.bg)))
        return f"\x1b[38;2;{accent}m", f"\x1b[38;2;{back};48;2;{accent}m"
    return f"\x1b[38;5;{chosen.accent256}m", f"\x1b[38;5;{chosen.bg256};48;5;{chosen.accent256}m"


MIN_CODE_CONTRAST = 7.0  # the text on code's background, as for the schemes themselves
CODE_LIFT = 0.25  # code's text, toward white (black on a light background), so its background can be stronger
CODE_STEPS = tuple(
    n / 100 for n in range(25, 7, -1)
)  # the background toward the text; the first that keeps 7:1


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{round(c):02x}" for c in rgb)


def _mix(toward: str, color: str, amount: float) -> str:
    return _hex(tuple(c + (t - c) * amount for t, c in zip(_rgb(toward), _rgb(color), strict=True)))  # type: ignore[arg-type]


def code_colors(fg: str, bg: str, lift: bool = True) -> tuple[str, str] | None:
    """Code's (text, background): the text a step brighter (darker on a light background) if `lift`,
    the background as far toward the text as keeps 7:1. None if no step does."""
    dark = contrast(bg, "#ffffff") >= contrast(bg, "#000000")
    text = _mix("#ffffff" if dark else "#000000", fg, CODE_LIFT) if lift else fg
    for step in CODE_STEPS:
        color = _mix(fg, bg, step)
        if contrast(text, color) >= MIN_CODE_CONTRAST:
            return text, color
    return None


def nearest256(color: str, candidates: range = range(16, 256)) -> list[int]:
    """The 256 colors, nearest to `color` first."""
    target = _rgb(color)

    def distance(number: int) -> int:
        return sum((s - c) ** 2 for s, c in zip(_rgb(xterm256(number)), target, strict=True))

    return sorted(candidates, key=distance)


def code256(color: str, fg256: int, bg256: int) -> int | None:
    """The nearest 256 color to `color` that differs from the background and keeps 7:1."""
    text = xterm256(fg256)
    return next(
        (n for n in nearest256(color) if n != bg256 and contrast(text, xterm256(n)) >= MIN_CODE_CONTRAST),
        None,
    )


def _code_pair(
    text: str, color: str, fg: str, bg: str, fg256: int, bg256: int, code256_: int, env: Mapping[str, str]
) -> tuple[str, str]:
    """(on, off) codes for code's text and background; the text only when it differs from `fg`, so an
    accent (headings, links) is kept. Empty `bg`: the terminal's own colors."""
    lifted = text != fg
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        on = f"48;2;{';'.join(map(str, _rgb(color)))}"
        off = f"48;2;{';'.join(map(str, _rgb(bg)))}" if bg else "49"
        if lifted:
            on = f"38;2;{';'.join(map(str, _rgb(text)))};{on}"
            off = (f"38;2;{';'.join(map(str, _rgb(fg)))};" if bg else "39;") + off
        return f"\x1b[{on}m", f"\x1b[{off}m"
    text256 = nearest256(text)[0] if lifted else fg256
    number = code256_ or code256(color, text256, bg256)
    if number is None:
        return "", ""
    on, off = f"48;5;{number}", f"48;5;{bg256}" if bg else "49"
    if lifted:
        on, off = f"38;5;{text256};{on}", (f"38;5;{fg256};" if bg else "39;") + off
    return f"\x1b[{on}m", f"\x1b[{off}m"


def code_codes(name: str | Scheme, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """(on, off) for code's text and background; ("", "") for the default scheme or with NO_COLOR.
    A theme's own code background, or an accent, keeps the text as it is."""
    env = os.environ if env is None else env
    chosen = name if isinstance(name, Scheme) else scheme(name)
    if chosen.name == DEFAULT or not enabled(env):
        return "", ""
    pair = (chosen.fg, chosen.code) if chosen.code else code_colors(chosen.fg, chosen.bg, not chosen.accent)
    if pair is None:
        return "", ""
    return _code_pair(*pair, chosen.fg, chosen.bg, chosen.fg256, chosen.bg256, chosen.code256, env)


def own_code_codes(
    own: tuple[tuple[int, int, int], tuple[int, int, int]] | None, env: Mapping[str, str] | None = None
) -> tuple[str, str]:
    """code_codes for the terminal's own (text, background), if it said."""
    env = os.environ if env is None else env
    if own is None or not enabled(env):
        return "", ""
    fg, bg = _hex(own[0]), _hex(own[1])
    pair = code_colors(fg, bg)
    if pair is None:
        return "", ""
    return _code_pair(*pair, fg, "", nearest256(fg)[0], nearest256(bg)[0], 0, env)


def xterm256(number: int) -> str:
    """One of the 256 colors as "#rrggbb" (for checking the fallback's contrast)."""
    if number < 16:
        basic = ["000000", "800000", "008000", "808000", "000080", "800080", "008080", "c0c0c0"]
        bright = ["808080", "ff0000", "00ff00", "ffff00", "0000ff", "ff00ff", "00ffff", "ffffff"]
        return "#" + (basic + bright)[number]
    if number < 232:
        steps = [0, 95, 135, 175, 215, 255]
        n = number - 16
        return "#" + "".join(f"{steps[c]:02x}" for c in (n // 36, n // 6 % 6, n % 6))
    level = 8 + 10 * (number - 232)
    return f"#{level:02x}{level:02x}{level:02x}"


def contrast(fg: str, bg: str) -> float:
    """The WCAG contrast ratio of two "#rrggbb" colors, from 1 to 21."""

    def luminance(color: str) -> float:
        def channel(value: int) -> float:
            c = value / 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = (channel(v) for v in _rgb(color))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    lighter, darker = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)
