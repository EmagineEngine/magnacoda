"""Color themes a person adds in a text file, pager-colors.ini, beside the pager's settings file.

    [slate]
    description = pale yellow on slate blue
    text = #ffe8a6
    background = #293955
    accent = #d59be4    ; optional: the title row, headings, links and the key hints
    code = #34466a      ; optional: code's background

The file is only read, never written. A theme that can't be used is left out with a reason, and the
rest still load: each color must be #rrggbb, the text and the accent must reach 7:1 contrast
against the background, and the text 7:1 against code. A name used twice, or one the pager already
has, gets a number: slate 1, slate 2 (a built-in theme keeps its own name). The 256-color fallback
is worked out from the colors.
Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from magnacoda.pager.colors import SCHEMES, Scheme, code256, contrast, nearest256, xterm256

FILE_NAME = "pager-colors.ini"
MIN_CONTRAST = 7.0  # WCAG AAA, as for the built-in themes
_MAX_BYTES = 64_000
_MAX_THEMES = 50
_NAME = re.compile(r"[a-z][a-z0-9_]{0,23}")
_COLOR = re.compile(r"#[0-9a-f]{6}")
_DESCRIPTION_MAX = 60
_KEYS = ("description", "text", "background", "accent", "code")
_HEADER = re.compile(r"\[\s*([^\]]*?)\s*\]")
_SETTING = re.compile(r"([A-Za-z]+)\s*[=:]\s*(.*)")
_INLINE_COMMENT = re.compile(r"\s;.*$")


@dataclass
class Loaded:
    themes: list[Scheme] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # one short line each, for the color list


@dataclass
class _Entry:
    name: str
    line: int
    values: dict[str, str] = field(default_factory=dict)


def _entries(text: str, problems: list[str]) -> list[_Entry]:
    """The file's sections in order, duplicates included (configparser would refuse or merge them)."""
    entries: list[_Entry] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        header = _HEADER.fullmatch(line)
        if header:
            entries.append(_Entry(header.group(1).lower().replace("-", "_").replace(" ", "_"), number))
            continue
        setting = _SETTING.fullmatch(_INLINE_COMMENT.sub("", line))
        if setting is None or not entries:
            problems.append(f"line {number}: not understood")
            continue
        key, value = setting.group(1).lower(), setting.group(2).strip()
        if key not in _KEYS:
            problems.append(f"line {number}: no setting named {key}")
            continue
        entries[-1].values[key] = value
    return entries


def _readable256(color: str, background256: int) -> int | None:
    """The nearest of the 256 colors to `color` that still reaches 7:1 on the background."""
    back = xterm256(background256)
    return next((n for n in nearest256(color) if contrast(xterm256(n), back) >= MIN_CONTRAST), None)


def _theme(entry: _Entry) -> Scheme | str:
    """The theme, or why it can't be used."""
    values = entry.values
    if not _NAME.fullmatch(entry.name):
        return f"line {entry.line}: a name is a letter, then up to 23 letters, digits or _"
    colors = {}
    for key in ("text", "background", "accent", "code"):
        value = values.get(key, "").lower()
        if not value and key in ("accent", "code"):
            continue
        if not _COLOR.fullmatch(value):
            return f"{entry.name}: {key} must be a color like #1a2b3c"
        colors[key] = value
    text, background, accent = colors["text"], colors["background"], colors.get("accent", "")
    code = colors.get("code", "")
    for key, color in (("text", text), ("accent", accent)):
        if color and (ratio := contrast(color, background)) < MIN_CONTRAST:
            return f"{entry.name}: {key} on background is {ratio:.1f}:1, needs {MIN_CONTRAST:.0f}:1"
    if code and (ratio := contrast(text, code)) < MIN_CONTRAST:
        return f"{entry.name}: text on code is {ratio:.1f}:1, needs {MIN_CONTRAST:.0f}:1"
    background256 = nearest256(background)[0]
    text256 = _readable256(text, background256)
    accent256 = _readable256(accent, background256) if accent else 0
    code_number = (code256(code, text256, background256) or 0) if code and text256 is not None else 0
    if text256 is None or accent256 is None:
        return f"{entry.name}: no readable match among the 256 colors"
    description = " ".join(values.get("description", "").split())[:_DESCRIPTION_MAX] or "your own theme"
    if not description.isprintable():
        description = "your own theme"
    return Scheme(
        entry.name,
        description,
        text,
        background,
        text256,
        background256,
        accent,
        accent256,
        code,
        code_number,
    )


def _numbered(themes: list[Scheme], taken: set[str]) -> list[Scheme]:
    """Names used twice, or already the pager's, get a number: slate_1, slate_2 (shown as slate 1)."""
    counts: dict[str, int] = {}
    for theme in themes:
        counts[theme.name] = counts.get(theme.name, 0) + 1
    used = set(taken) | {name for name, count in counts.items() if count == 1 and name not in taken}
    next_number: dict[str, int] = {}
    out = []
    for theme in themes:
        name = theme.name
        if counts[name] > 1 or name in taken:
            number = next_number.get(name, 2 if name in taken else 1)
            while f"{name}_{number}" in used:
                number += 1
            next_number[name] = number + 1
            name = f"{name}_{number}"
            used.add(name)
        out.append(replace(theme, name=name))
    return out


def load(path: Path | None) -> Loaded:
    """The themes in the file, after the checks in the module docstring. No file: none, no problems."""
    loaded = Loaded()
    if path is None:
        return loaded
    try:
        if not path.is_file():
            return loaded
        if path.stat().st_size > _MAX_BYTES:
            loaded.problems.append(f"{path.name} is larger than {_MAX_BYTES // 1000} KB")
            return loaded
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        loaded.problems.append(f"{path.name} can't be read")
        return loaded
    entries = _entries(text, loaded.problems)
    if len(entries) > _MAX_THEMES:
        loaded.problems.append(f"only the first {_MAX_THEMES} themes are used")
        entries = entries[:_MAX_THEMES]
    themes = []
    for entry in entries:
        theme = _theme(entry)
        if isinstance(theme, str):
            loaded.problems.append(theme)
        else:
            themes.append(theme)
    loaded.themes = _numbered(themes, {scheme.name for scheme in SCHEMES})
    return loaded
