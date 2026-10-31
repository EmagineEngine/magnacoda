"""Stored scan commands (history.md, add-ons) and their round trip with the wizard's answers.

Stored as `scan ...` without the program name, so they paste straight into the shell. A leading
"magnacoda" is accepted when reading.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass, field

PROGRAM_WORDS = {"magnacoda", "scan"}
REDACTED = "<redacted>"
SECRET_FLAGS = ("--cookie", "--extra-http-header")

# The wizard's questions and the values each accepts ("system" means: leave the flag out).
CHOICES: dict[str, tuple[str, ...]] = {
    "level": ("A", "AA", "AAA"),
    "ai": ("off", "explain", "semantic"),
    "color_scheme": ("system", "light", "dark", "both"),
    "screen": ("system", "desktop", "mobile", "both"),
    "fail_on": ("none", "minor", "moderate", "serious", "critical"),
}
# Options magnacoda no longer has, and whether each took a value. Older saved commands (history,
# favorites) may still have them: they're stripped when read, with their values, and nothing is said.
_REMOVED = {
    "--save": False,
    "--format": True,
    "--checklist": True,
    "--force": False,
    "--hide-passed": False,
    "--no-color": False,
    "--api-key-env": True,
    "--fixes": True,
    "--quiet-period-ms": True,
    "--min-wait-ms": True,
    "--stability-timeout-ms": True,
    "--extra-wait-ms": True,
    "--nav-timeout-ms": True,
}
_FLAGS = {
    "--level": "level",
    "--ai": "ai",
    "--fail-on": "fail_on",
    "--color-scheme": "color_scheme",
    "--screen": "screen",
}


@dataclass
class SavedScan:
    """The wizard's answers, plus any options the wizard has no question for (kept as they were)."""

    url: str = ""
    level: str = "AA"
    ai: str = "off"
    color_scheme: str = "system"
    screen: str = "system"
    fail_on: str = "serious"
    extras: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # things left out or ignored while reading
    # The stored command it was started from (a favorite, a recent scan), so an add-on can tell its
    # own entry was changed. Empty for a new scan.
    origin: str = ""


def _mask(value: str) -> str:
    key, sep, _ = value.partition("=")
    return f"{key}={REDACTED}" if sep else REDACTED


def redact(tokens: list[str]) -> list[str]:
    """Mask --cookie and --extra-http-header values so secrets are never saved."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        name, eq, inline = token.partition("=")
        if name in SECRET_FLAGS and eq:
            out.append(f"{name}={_mask(inline)}")
        elif token in SECRET_FLAGS and i + 1 < len(tokens):
            out.extend([token, _mask(tokens[i + 1])])
            i += 1
        else:
            out.append(token)
        i += 1
    return out


def _looks_like_a_value(token: str) -> bool:
    return not token.startswith("-") and "://" not in token


def parse(command: str, takes_value: Callable[[str], bool] | None = None) -> SavedScan | None:
    """Parse a stored command, or None. `takes_value(flag)` says which unknown options take a value
    (by default, a following plain word is assumed to be one)."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    while tokens and tokens[0].lower() in PROGRAM_WORDS:
        tokens.pop(0)
    if not tokens:
        return None

    scan = SavedScan()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-") and len(token) > 1:
            name, eq, inline = token.partition("=")
            if name in _REMOVED:
                i += 2 if _REMOVED[name] and not eq else 1
            elif name in _FLAGS:
                if eq:
                    value, i = inline, i + 1
                elif i + 1 < len(tokens):
                    value, i = tokens[i + 1], i + 2
                else:
                    scan.notes.append(f"Ignored {name}: it had no value.")
                    i += 1
                    continue
                attribute = _FLAGS[name]
                if value in CHOICES[attribute]:
                    setattr(scan, attribute, value)
                else:
                    scan.notes.append(f"Ignored {name} {value!r}: not a valid choice.")
            elif name in SECRET_FLAGS:
                if eq:
                    value, i = inline, i + 1
                elif i + 1 < len(tokens):
                    value, i = tokens[i + 1], i + 2
                else:
                    i += 1
                    continue
                if value.endswith(REDACTED):
                    scan.notes.append(f"Left out {name}: its value was never stored.")
                else:
                    scan.extras += [name, value] if not eq else [token]
            else:
                scan.extras.append(token)
                i += 1
                wants_value = (
                    takes_value(name) if takes_value else (i < len(tokens) and _looks_like_a_value(tokens[i]))
                )
                if not eq and wants_value and i < len(tokens):
                    scan.extras.append(tokens[i])
                    i += 1
        else:
            if not scan.url:
                scan.url = token
            else:
                scan.extras.append(token)
            i += 1
    return scan if scan.url else None


def to_tokens(scan: SavedScan) -> list[str]:
    """`scan URL ...` as words, in the wizard's order; fixes and fail-on only when not the default."""
    tokens = ["scan", scan.url, "--level", scan.level, "--ai", scan.ai]
    if scan.fail_on != "serious":
        tokens += ["--fail-on", scan.fail_on]
    if scan.color_scheme != "system":
        tokens += ["--color-scheme", scan.color_scheme]
    if scan.screen != "system":
        tokens += ["--screen", scan.screen]
    return tokens + scan.extras


def to_command(scan: SavedScan) -> str:
    """The stored form: starts with `scan`, redacted, quoted so it is safe to paste."""
    return shlex.join(redact(to_tokens(scan)))


def display_command(scan: SavedScan, program: str = "magnacoda") -> str:
    """What the wizard shows: the program name, then the same words."""
    return f"{program} {shlex.join(to_tokens(scan))}"


def canonical(command: str) -> str:
    """A form for comparing two commands (same words and options, however they were typed)."""
    scan = parse(command)
    return to_command(scan) if scan else command.strip()
