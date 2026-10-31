"""Block every request while the interaction tests run, and record what the page tried.

In the page itself, a load of another page is cancelled before it starts (the Navigation API), a form
submission is stopped after the page's own submit handlers have run, and `form.submit()` and `window.open`
are no-ops that only record the attempt. Behind that, every request is blocked: a page load gets an empty
204 so the browser stays put, everything else is aborted. That's what makes the tests safe on live sites.

Stopping loads in the page matters since Playwright 1.64: after a load answered with a 204, its next action
on the page waits for that load to finish, which it never does.
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


# Runs in the page: records and stops what would leave it, only while window.__magnacodaBlocking is set.
_STOP_SCRIPT = """() => {
    window.__magnacodaBlocking = true;
    window.__magnacodaTried = window.__magnacodaTried || [];
    if (window.__magnacodaStopping) return;
    window.__magnacodaStopping = true;
    const tried = (method) => window.__magnacodaTried.push(
        (method || "get").toLowerCase() === "get" ? "started loading another page" : "submitted the form");
    if (window.navigation) {
        navigation.addEventListener("navigate", (event) => {
            if (!window.__magnacodaBlocking || !event.cancelable || event.hashChange
                || event.destination.sameDocument || event.downloadRequest !== null) return;
            tried(event.formData ? "post" : "get");
            event.preventDefault();
        });
    }
    window.addEventListener("submit", (event) => {
        if (!window.__magnacodaBlocking || event.defaultPrevented) return;
        const method = (event.submitter && event.submitter.getAttribute("formmethod")) || event.target.method;
        if (method.toLowerCase() === "dialog") return;  // only closes a dialog
        tried(method);
        event.preventDefault();
    });
    const submit = HTMLFormElement.prototype.submit;
    HTMLFormElement.prototype.submit = function () {
        if (!window.__magnacodaBlocking) return submit.call(this);
        tried(this.method);
    };
}"""


@dataclass
class Watch:
    """What the page tried to do while blocked."""

    page: Page
    _events: list[str] = field(default_factory=list)
    calls: int = 0  # fetch/XHR, e.g. a form sent by script

    @property
    def events(self) -> list[str]:
        """What the page tried, such as "submitted the form", including what was stopped in the page."""
        with contextlib.suppress(Exception):
            self._events.extend(self.page.evaluate("() => (window.__magnacodaTried || []).splice(0)"))
        return self._events

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
                    watch._events.append(
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
    page.evaluate(_STOP_SCRIPT)
    context = page.context  # not just the page: popups and frames too
    context.route("**/*", block)
    page.on("popup", popup)
    try:
        yield watch
    finally:
        page.remove_listener("popup", popup)
        with contextlib.suppress(Exception):
            page.evaluate("() => { window.__magnacodaBlocking = false; }")
        with contextlib.suppress(Exception):
            page.evaluate(_UNMARK_SCRIPT, list(marks))
        with contextlib.suppress(Exception):
            context.unroute("**/*", block)
