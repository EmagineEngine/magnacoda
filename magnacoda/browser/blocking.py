"""Block every request while the interaction tests run, and record what the page tried.

Page loads get an empty 204 so the browser stays put, everything else is aborted, and `window.open` is a
no-op that only counts calls. That's what makes the tests safe on live sites.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass, field

from playwright.sync_api import Page, Route

_UNMARK_SCRIPT = (
    "(marks) => { for (const mark of marks)"
    " document.querySelectorAll('[' + mark + ']').forEach((el) => el.removeAttribute(mark)); }"
)


@dataclass
class Watch:
    """What the page tried to do while blocked."""

    page: Page
    events: list[str] = field(default_factory=list)  # "submitted the form", ...
    calls: int = 0  # fetch/XHR, e.g. a form sent by script

    def clear(self) -> None:
        self.events.clear()
        self.calls = 0

    def windows_opened(self) -> bool:
        opened = bool(self.page.evaluate("() => window.__magnacodaOpened || 0"))
        if opened:
            self.page.evaluate("() => { window.__magnacodaOpened = 0; }")
        return opened


@contextlib.contextmanager
def blocked(page: Page, marks: tuple[str, ...] = ()) -> Iterator[Watch]:
    """Block all requests in the browser context; on exit, remove the `marks` attributes from the page."""
    watch = Watch(page)

    def block(route: Route) -> None:
        # Whatever goes wrong below, the request must not get through.
        request = route.request
        try:
            if request.is_navigation_request():
                try:
                    in_this_page = request.frame == page.main_frame
                except Exception:  # noqa: BLE001 - a new window's frame doesn't exist yet
                    in_this_page = False
                if in_this_page:
                    watch.events.append(
                        "submitted the form" if request.method != "GET" else "started loading another page"
                    )
                # 204 rather than abort: an aborted navigation shows an error page instead.
                route.fulfill(status=204, body="")
                return
            if request.resource_type in ("fetch", "xhr"):
                watch.calls += 1
        except Exception:  # noqa: BLE001 - never let a request through because of a problem here
            pass
        with contextlib.suppress(Exception):
            route.abort()

    def popup(new_page: Page) -> None:
        watch.events.append("opened a new window")
        with contextlib.suppress(Exception):
            new_page.close()

    page.evaluate(
        "() => { window.__magnacodaOpened = 0;"
        " window.open = () => { window.__magnacodaOpened++; return null; }; }"
    )
    context = page.context  # not just the page: popups and frames too
    context.route("**/*", block)
    page.on("popup", popup)
    try:
        yield watch
    finally:
        page.remove_listener("popup", popup)
        with contextlib.suppress(Exception):
            page.evaluate(_UNMARK_SCRIPT, list(marks))
        with contextlib.suppress(Exception):
            context.unroute("**/*", block)
