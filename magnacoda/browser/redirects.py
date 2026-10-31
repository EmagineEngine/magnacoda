"""Redirects: where a page actually ends up, and pages that move on by themselves (WCAG 2.2.1)."""

from __future__ import annotations

import ssl
import time
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from magnacoda import __version__
from magnacoda.findings.models import FeatureExample, InteractionResult, PageProblem

if TYPE_CHECKING:  # report code imports this module without Playwright
    from playwright.sync_api import Page, Request, Route

# Anything quicker is part of loading (a script that checks something and sends you on).
TIMED_AFTER = 2.0
CHECK_TIMEOUT = 10


def host(url: str) -> str:
    """Lower-case host without a leading "www."."""
    name = (urlsplit(url).hostname or "").lower()
    return name.removeprefix("www.")


def same_site(a: str, b: str) -> bool:
    """Same host and port; http vs. https and "www." don't matter."""
    parts_a, parts_b = urlsplit(a), urlsplit(b)
    if {parts_a.scheme, parts_b.scheme} <= {"http", "https"}:
        return host(a) == host(b) and _port(parts_a.port) == _port(parts_b.port)
    return (parts_a.scheme, host(a), parts_a.port) == (parts_b.scheme, host(b), parts_b.port)


def _port(port: int | None) -> int | None:
    return None if port in (None, 80, 443) else port


def from_elsewhere(url: str, requested: str | None) -> str | None:
    """`requested`, if it led to a different site; otherwise None."""
    return requested if requested and not same_site(url, requested) else None


def check_address(url: str, *, ignore_https_errors: bool = False) -> str | None:
    """Follow the server's redirects with a plain GET and return the final URL.

    Doesn't see redirects done by scripts. None if the request fails or the URL isn't http(s).
    """
    if urlsplit(url).scheme not in ("http", "https"):
        return None
    context = ssl._create_unverified_context() if ignore_https_errors else None  # noqa: S323 - opted in
    request = urllib.request.Request(url, headers={"User-Agent": f"magnacoda/{__version__.split('+')[0]}"})
    try:
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT, context=context) as response:  # noqa: S310
            return str(response.geturl())
    except Exception:  # noqa: BLE001 - the scan itself reports the real error
        return None


@dataclass
class TimedRedirect:
    from_url: str
    to_url: str
    after: float  # seconds after from_url appeared


@dataclass
class _Watch:
    shown: list[tuple[float, str]] = field(default_factory=list)  # (monotonic time, url)
    held: bool = False
    held_at: float = 0.0
    tried: list[TimedRedirect] = field(default_factory=list)


_WATCHES: dict[int, _Watch] = {}


def watch(page: Page) -> None:
    """Record every page the main frame shows. Call before the first goto()."""
    record = _WATCHES[id(page)] = _Watch()

    def shown(frame: object) -> None:
        url = page.main_frame.url
        if frame is not page.main_frame or url.startswith("about:"):
            return
        # Same page with a new #fragment (a skip link, say) isn't a navigation.
        if record.shown and _without_fragment(record.shown[-1][1]) == _without_fragment(url):
            return
        record.shown.append((time.monotonic(), url))

    page.on("framenavigated", shown)


def forget(page: Page) -> None:
    _WATCHES.pop(id(page), None)


def _without_fragment(url: str) -> str:
    return url.split("#", 1)[0]


def landed(page: Page) -> str:
    return page.url


def hold(page: Page) -> None:
    """Keep the page from navigating away by itself.

    Main-frame navigations get an empty 204 and are recorded; everything else falls through. This is
    a context route on purpose: blocking.py's route is added later, so it wins while the interaction
    tests run, and navigations the tests cause never reach this one.
    """
    record = _WATCHES.setdefault(id(page), _Watch())
    if record.held:
        return
    record.held, record.held_at = True, time.monotonic()

    def route(route: Route, request: Request) -> None:
        if request.is_navigation_request() and request.frame is page.main_frame:
            since = record.shown[-1] if record.shown else (time.monotonic(), page.url)
            record.tried.append(
                TimedRedirect(from_url=since[1], to_url=request.url, after=time.monotonic() - since[0])
            )
            route.fulfill(status=204, body="")
            return
        route.fallback()

    page.context.route("**/*", route)


def timed_redirects(page: Page) -> list[TimedRedirect]:
    """Navigations that came at least TIMED_AFTER seconds after the page appeared, one per target."""
    record = _WATCHES.get(id(page))
    if record is None:
        return []
    # Pages shown after hold() came from the tests, not from the page.
    by_itself = [shown for shown in record.shown if not record.held or shown[0] <= record.held_at]
    found = [
        TimedRedirect(from_url=before[1], to_url=after[1], after=after[0] - before[0])
        for before, after in zip(by_itself, by_itself[1:], strict=False)
        if after[0] - before[0] >= TIMED_AFTER
    ]
    found += [tried for tried in record.tried if tried.after >= TIMED_AFTER]
    unique: dict[str, TimedRedirect] = {}
    for redirect in found:
        unique.setdefault(redirect.to_url, redirect)
    return list(unique.values())


def note_timed(page: Page, interaction: InteractionResult) -> None:
    """Add each timed redirect to the interaction problems (rule timed-redirect, 2.2.1)."""
    for redirect in timed_redirects(page):
        seconds = max(1, round(redirect.after))
        interaction.problems.append(
            PageProblem(
                element=FeatureExample(selector=""),
                kind="timed-redirect",
                detail=f"{redirect.to_url} after {seconds} second{'s' if seconds != 1 else ''}",
            )
        )
