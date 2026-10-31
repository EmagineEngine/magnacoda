"""Scan time estimates for the wizard, and the settings that would speed things up.

probe_page loads the page once and counts what the tests will touch. The per-item costs in _COST were
measured on a slow laptop and are scaled by how fast this machine walked the page.
"""

from __future__ import annotations

import dataclasses
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import click

from magnacoda import addresses, preferences, questions
from magnacoda.browser.launcher import launch_page
from magnacoda.browser.stability import wait_for_stable
from magnacoda.config import ScanConfig
from magnacoda.exceptions import MagnacodaError, NavigationError
from magnacoda.savedcommand import SavedScan
from magnacoda.wrapping import wrap_for_stream

# One pass over the page, like the scan's own: counts, and how long the pass took (the computer's speed).
_COUNT_SCRIPT = """
() => {
    const started = performance.now();
    const all = document.body ? document.body.querySelectorAll('*') : [];
    let pointer = 0;  // also what makes the walk take as long as the scan's own (its speed is measured)
    for (const el of all) if (getComputedStyle(el).cursor === 'pointer') pointer++;
    const count = (selector) => document.querySelectorAll(selector).length;
    return {
        elements: all.length,
        images: count('img, svg, canvas, [role="img"], input[type="image"]'),
        forms: document.forms.length,
        fields: count('input:not([type="hidden"]):not([type="submit"]):not([type="button"])'
            + ':not([type="reset"]):not([type="image"]), select, textarea'),
        focusable: count('a[href], button, input:not([type="hidden"]), select, textarea, summary, '
            + '[tabindex]:not([tabindex^="-"])'),
        hover: count('[aria-haspopup]:not([aria-haspopup="false"]), [aria-describedby], [data-tooltip], '
            + '[data-bs-toggle="tooltip"], [data-toggle="tooltip"], [popovertarget]'),
        // What the widget test clicks: not a button that would send its form.
        toggles: Array.from(document.querySelectorAll('[aria-expanded], button, [role="button"]'))
            .filter((el) => !(el.localName === 'button' && el.form && el.type !== 'button')).length,
        pointer,
        walkMs: performance.now() - started,
    };
}
"""

# Seconds, measured on the slow laptop magnacoda was developed on, per scan or per item.
_COST = {
    "axe_base": 1.1,  # axe-core: fixed, per element, and more on big pages (it grows faster than the page)
    "axe_per_element": 0.0035,
    "axe_per_thousand_squared": 0.45,
    "features": 0.1,  # reading the page's features and naming the elements, plus per element
    "features_per_element": 0.0001,
    "image": 0.14,  # each screenshot (up to 30), when the scan is saved
    "layout": 1.4,  # the layout when zoomed in, plus per element
    "layout_per_element": 0.0002,
    "tab_base": 0.4,  # the Tab pass, plus per element it visits (up to 100)
    "tab_stop": 0.12,
    "fields": 0.1,  # the fields' autocomplete and pasting
    "form": 0.8,  # each form sent empty (up to 5)
    "field": 0.35,  # each field changed (up to 20)
    "motion": 6.0,  # the motion watch, less what the screenshots already took
    "hover": 1.5,  # each trigger hovered (up to 12); some show something and take longer
    "shortcuts": 2.0,  # the single keys, and finding the mouse-only controls
    "toggle": 1.1,  # each toggle clicked (up to 10)
}

# How long the walk over the page took per element on that laptop, to scale the costs for this computer.
_REFERENCE_MS_PER_ELEMENT = 0.0065  # on pages of 1,000 elements or more; smaller ones say little
# Rough seconds for the AI tiers per scan: they depend on Anthropic's servers, not this computer.
_AI_SECONDS = {"off": 0.0, "explain": 30.0, "semantic": 75.0}


@dataclass(frozen=True)
class PageProbe:
    startup: float  # starting the browser and loading the page, in seconds
    settle: float  # waiting for it to settle
    elements: int
    images: int
    forms: int
    fields: int
    focusable: int
    hover: int
    toggles: int
    speed: float  # this computer (and page) compared with the reference laptop: 2.0 = twice as slow


@dataclass(frozen=True)
class Choices:
    """What the estimate depends on: number of scans, quick or not, and AI."""

    scans: int = 1  # full scans: one per screen
    dark: bool = False  # a short dark-mode pass after each (browser/theme.py)
    quick: bool = False
    ai: str = "off"


@dataclass
class Estimate:
    per_scan: float  # seconds
    total: float
    parts: dict[str, float] = field(default_factory=dict)  # per scan, the larger parts by name


def probe_page(config: ScanConfig) -> PageProbe:
    """Open the page once and measure it (raises NavigationError, like a scan, if it can't be loaded)."""
    started = time.monotonic()
    with launch_page(config) as page:
        loaded = time.monotonic()
        wait_for_stable(page, config.stability)
        settled = time.monotonic()
        page.evaluate(_COUNT_SCRIPT)  # the first walk also lays the page out: time the second
        counts = page.evaluate(_COUNT_SCRIPT)
    elements = max(int(counts["elements"]), 1)
    speed = (counts["walkMs"] / elements) / _REFERENCE_MS_PER_ELEMENT if elements >= 1000 else 1.0
    return PageProbe(
        startup=loaded - started,
        settle=settled - loaded,
        elements=elements,
        images=int(counts["images"]),
        forms=int(counts["forms"]),
        fields=int(counts["fields"]),
        focusable=int(counts["focusable"]),
        hover=int(counts["hover"]),
        toggles=int(counts["toggles"]),
        speed=min(max(speed, 0.5), 2.5),  # a busy moment shouldn't double the estimate
    )


def estimate(probe: PageProbe, choices: Choices) -> Estimate:
    """Seconds for one scan and for all of them, with the larger parts of a scan named."""
    c = _COST
    speed = probe.speed
    elements = probe.elements
    images = min(probe.images, 30) * c["image"] * speed
    page = {
        "loading the page": probe.startup + probe.settle,
        "the accessibility checks": (
            c["axe_base"]
            + elements * c["axe_per_element"]
            + (elements / 1000) ** 2 * c["axe_per_thousand_squared"]
        )
        * speed,
        "reading the page": (c["features"] + elements * c["features_per_element"]) * speed,
        "the layout when zoomed in": (c["layout"] + elements * c["layout_per_element"]) * speed,
        "the Tab pass": (c["tab_base"] + min(probe.focusable, 100) * c["tab_stop"]) * speed,
        "the forms": (c["fields"] + min(probe.forms, 5) * c["form"] + min(probe.fields, 20) * c["field"])
        * speed,
    }
    if images:
        page["screenshots of images"] = images
    if not choices.quick:
        page["moving content, hovering, clicking and single keys"] = (
            max(c["motion"] - images, 0.0)
            + (min(probe.hover, 12) * c["hover"] + c["shortcuts"] + min(probe.toggles, 10) * c["toggle"])
            * speed
        )
    if choices.dark:
        # Loading the page again, contrast and image rules (about half of axe-core's time), the Tab pass
        # and the screenshots.
        page["dark mode"] = (
            page["loading the page"]
            + page["the accessibility checks"] / 2
            + page["the Tab pass"]
            + page.get("screenshots of images", 0.0)
        )
    ai = _AI_SECONDS.get(choices.ai, 0.0)
    if ai:
        page["AI"] = ai
    per_scan = sum(page.values())
    return Estimate(per_scan=per_scan, total=per_scan * max(choices.scans, 1), parts=page)


def duration(seconds: float) -> str:
    """'about 40 seconds', 'about 1 min 40 s', rounded to what an estimate can promise."""
    if round(seconds / 5) * 5 < 60:
        return f"about {max(5, round(seconds / 5) * 5)} seconds"
    minutes, rest = divmod(round(seconds / 10) * 10, 60)
    return f"about {minutes} min" + (f" {rest} s" if rest else "")


# The wizard's step before running a scan, which add-ons can use too: check the page, estimate, and offer
# the settings that make the scan faster.


def _say(text: str) -> None:
    click.echo(wrap_for_stream(text, sys.stdout))
    questions.printed(text)


def _scan_count(scan: SavedScan) -> int:
    """Full scans: one per screen (dark mode adds a short pass to each, not a scan)."""
    return 2 if scan.screen == "both" else 1


def _both_themes(scan: SavedScan) -> bool:
    return scan.color_scheme in ("system", "both")


def _is_quick(scan: SavedScan) -> bool:
    if "--quick" in scan.extras:
        return True
    return "--thorough" not in scan.extras and preferences.load().quick


def _choices(scan: SavedScan) -> Choices:
    return Choices(scans=_scan_count(scan), dark=_both_themes(scan), quick=_is_quick(scan), ai=scan.ai)


def _probe(scan: SavedScan) -> PageProbe:
    """Check the page as the scan's first pass will see it, falling back to http:// like a scan."""
    address = addresses.interpret(scan.url)
    first = {
        "color_scheme": "light" if _both_themes(scan) else scan.color_scheme,
        "screen": None if scan.screen in ("system", "both") else scan.screen,
    }
    if scan.screen == "both":
        first["screen"] = "desktop"
    try:
        return probe_page(ScanConfig(url=address.url, **first))  # type: ignore[arg-type]
    except NavigationError as exc:
        if address.added != "https" or not exc.could_not_connect:
            raise
        return probe_page(ScanConfig(url=addresses.as_http(address.url), **first))  # type: ignore[arg-type]


def _quick_version(scan: SavedScan) -> SavedScan:
    extras = [e for e in scan.extras if e != "--thorough"]
    if not preferences.load().quick:
        extras.append("--quick")
    return dataclasses.replace(scan, extras=extras)


Change = Callable[[SavedScan], SavedScan]


def _faster_ways(scan: SavedScan) -> list[tuple[str, Change]]:
    """The settings that would make this scan faster: (what changes, how)."""
    ways: list[tuple[str, Change]] = []
    if not _is_quick(scan):
        ways.append(
            ("Quick scan (no watching for moving content, hovering, clicking or single keys)", _quick_version)
        )
    if scan.screen == "both":
        ways.append(("Desktop only, not mobile too", lambda s: dataclasses.replace(s, screen="system")))
    if _both_themes(scan):
        ways.append(
            ("Light mode only, not dark mode too", lambda s: dataclasses.replace(s, color_scheme="light"))
        )
    if scan.ai != "off":
        ways.append(
            (
                "No AI",
                lambda s: dataclasses.replace(s, ai="off"),
            )
        )
    return ways


def offer_faster(scan: SavedScan, echo: Callable[[str], None] | None = None) -> SavedScan:
    """Probe the page, show the estimate and offer faster settings; returns the (maybe changed) scan.

    Also stores the estimate in the Click context's meta for the spinner.
    """
    _echo = echo or _say
    _echo("Checking the page, to say how long the scan will take (a few seconds)...")
    try:
        probe = _probe(scan)
    except (MagnacodaError, addresses.NotAnAddress) as exc:
        _echo(f"Couldn't check the page first ({str(exc).splitlines()[0]}); the scan will say more.")
        return scan
    while True:
        result = estimate(probe, _choices(scan))
        click.get_current_context().meta["magnacoda.estimate"] = result.total  # for the spinner
        count = _scan_count(scan)
        scans = f" (desktop and mobile, {duration(result.per_scan)} each)" if count > 1 else ""
        slowest = sorted(
            ((name, seconds) for name, seconds in result.parts.items() if seconds >= 3), key=lambda p: -p[1]
        )[:2]
        _echo(f"\nEstimated time: {duration(result.total)}{scans}.")
        if slowest:
            _echo(
                "Slowest: "
                + "; ".join(f"{name}, {duration(seconds)} a scan" for name, seconds in slowest)
                + "."
            )
        ways = _faster_ways(scan)
        if not ways or result.total < 20:
            return scan
        _echo("\nTo go faster:")
        for number, (what, change) in enumerate(ways, start=1):
            saved = result.total - estimate(probe, _choices(change(scan))).total
            _echo(f"  {number}. {what}: {duration(saved)} less")
        picked = _pick_numbers("Changes to make (one or more numbers)", len(ways))
        if not picked:
            return scan
        for index in picked:
            scan = ways[index][1](scan)


def _pick_numbers(text: str, count: int) -> list[int]:
    """Several of 1..count, separated by spaces or commas, or Enter for none (0-based). Re-asks."""

    def check(value: str) -> list[int]:
        parts = [p for p in value.replace(",", " ").split() if p]
        if all(p.isdigit() and 1 <= int(p) <= count for p in parts):
            return sorted({int(p) - 1 for p in parts})
        raise click.BadParameter(f"type numbers from the list above (1 to {count}), or press Enter.")

    # Enter: none, so the scan runs as it is.
    return questions.ask(  # type: ignore[no-any-return]
        f"{text} [run as-is]", default="", show_default=False, value_proc=check
    )
