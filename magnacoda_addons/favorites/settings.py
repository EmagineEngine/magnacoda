"""The favorites add-on's settings: its own [favorites] section of magnacoda's preferences.ini. The
add-on only declares the section; magnacoda checks it, writes it into the file and reads it back."""

from __future__ import annotations

from magnacoda import preferences

DEFAULT_FAVORITES_MAX = 10

SECTION = preferences.AddonSection(
    "favorites",
    (
        preferences.Setting(
            "max",
            DEFAULT_FAVORITES_MAX,
            "How many favorites to keep in favorites.md (1 to 100).",
            low=1,
            high=100,
        ),
    ),
)


def ensure_section() -> None:
    """Add the [favorites] section to preferences.ini if missing. Never raises."""
    preferences.add_section(SECTION)


def favorites_max() -> int:
    """How many favorites to keep. A missing or invalid value gives the default; out of range is clamped."""
    return int(preferences.addon_value(SECTION, "max"))
