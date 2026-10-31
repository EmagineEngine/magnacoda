from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from magnacoda.browser import redirects
from magnacoda.config import ScanConfig
from magnacoda.exceptions import BrowserNotInstalledError, NavigationError

# Ctrl+C mid-load leaves Playwright's internal asyncio tasks pending, and Python complains about them
# later ("Task was destroyed but it is pending!"), often in the middle of other output. Nothing here uses
# asyncio directly; real errors still arrive as NavigationError.
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

_NET_ERROR_HINTS = {
    "ERR_NAME_NOT_RESOLVED": "could not resolve the host name '{host}' - check the URL spelling",
    "ERR_CONNECTION_REFUSED": "connection refused by '{host}' - is the server running?",
    "ERR_CONNECTION_TIMED_OUT": "connection to '{host}' timed out",
    "ERR_INTERNET_DISCONNECTED": "no internet connection",
    "ERR_CERT_": "TLS certificate problem (use --ignore-https-errors to scan anyway)",
    "ERR_SSL_": "TLS/SSL problem (use --ignore-https-errors to scan anyway)",
}


# Errors where plain http might still work (no https, or a bad certificate). DNS errors aren't here.
_CONNECTION_FAILURES = (
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_EMPTY_RESPONSE",
    "ERR_SSL_",
    "ERR_CERT_",
    "NS_ERROR_CONNECTION_REFUSED",
    "NS_ERROR_NET_RESET",
    "SSL_ERROR_",
)


def could_not_connect(exc: Exception) -> bool:
    raw = str(exc)
    return any(code in raw for code in _CONNECTION_FAILURES)


def describe_navigation_error(exc: Exception, url: str, nav_timeout_ms: int) -> str:
    """Turn a Playwright goto error into one short, actionable line (no call log)."""
    raw = str(exc)
    host = urlparse(url).hostname or url
    for code, hint in _NET_ERROR_HINTS.items():
        if code in raw:
            return f"Could not load {url}: {hint.format(host=host)}."
    if "invalid URL" in raw:
        return f"Invalid URL {url!r}: include the scheme, e.g. https://{url}."
    if "Timeout" in raw:
        return (
            f"Could not load {url}: no response within {nav_timeout_ms // 1000}s "
            "(if the site is just slow, scan again with --wait 30, in seconds)."
        )
    first_line = raw.strip().splitlines()[0] if raw.strip() else "unknown error"
    return f"Could not load {url}: {first_line.removeprefix('Page.goto: ')}"


DEFAULT_VIEWPORT = (1280, 720)
DEFAULT_MOBILE_DEVICE = "Pixel 8 Pro"


@contextmanager
def _ctrl_c_ends_the_browser() -> Iterator[None]:
    """Ctrl+C while the browser is open: stop cleanly instead of hanging.

    Ctrl+C reaches Playwright's driver too, and it closes the browser. A KeyboardInterrupt raised in the
    middle of a Playwright call would leave Playwright waiting forever, so the first Ctrl+C only notes
    it: the call in progress then fails as the browser goes, and KeyboardInterrupt is raised here
    instead. A second Ctrl+C interrupts at once. Only in the main thread (signals can't be set elsewhere).
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    pressed = False

    def on_ctrl_c(signum: int, frame: object) -> None:
        nonlocal pressed
        if pressed:
            raise KeyboardInterrupt
        pressed = True

    previous = signal.signal(signal.SIGINT, on_ctrl_c)
    try:
        yield
    except Exception:
        if pressed:
            raise KeyboardInterrupt from None  # the browser went because of Ctrl+C: not an error
        raise
    finally:
        signal.signal(signal.SIGINT, previous)
    if pressed:
        raise KeyboardInterrupt


@contextmanager
def launch_page(config: ScanConfig) -> Iterator[Page]:
    """Launch a browser, open config.url and yield the page; close everything on exit.

    Waits for domcontentloaded only. SPA readiness is stability.py's job.
    """
    with _ctrl_c_ends_the_browser(), sync_playwright() as pw:
        browser_type = getattr(pw, config.browser_name)
        try:
            browser: Browser = browser_type.launch(headless=config.headless)
        except Exception as exc:
            if "Executable doesn't exist" in str(exc):
                raise BrowserNotInstalledError(
                    f"{config.browser_name} browser binary not found. Run `magnacoda setup` "
                    f"(or `playwright install {config.browser_name}`) first."
                ) from exc
            raise

        context_kwargs: dict = {}
        # --device wins; --screen mobile only supplies a default phone.
        device_name = config.device or (DEFAULT_MOBILE_DEVICE if config.screen == "mobile" else None)
        if device_name:
            device = pw.devices.get(device_name)
            if device is None:
                browser.close()
                raise NavigationError(f"Unknown --device: {device_name!r}")
            context_kwargs.update(device)
        # --viewport wins over the device's size.
        if config.viewport_width and config.viewport_height:
            context_kwargs["viewport"] = {"width": config.viewport_width, "height": config.viewport_height}
        elif not device_name:
            context_kwargs["viewport"] = {"width": DEFAULT_VIEWPORT[0], "height": DEFAULT_VIEWPORT[1]}
        if config.color_scheme:
            context_kwargs["color_scheme"] = config.color_scheme
        if config.user_agent:
            context_kwargs["user_agent"] = config.user_agent
        if config.ignore_https_errors:
            context_kwargs["ignore_https_errors"] = True
        if config.storage_state:
            context_kwargs["storage_state"] = str(config.storage_state)

        context: BrowserContext = browser.new_context(**context_kwargs)
        if config.extra_http_headers:
            context.set_extra_http_headers(config.extra_http_headers)
        if config.cookies:
            context.add_cookies(
                [{"name": c["name"], "value": c["value"], "url": c["url"]} for c in config.cookies]
            )

        page = context.new_page()
        page.set_default_navigation_timeout(config.stability.nav_timeout_ms)
        redirects.watch(page)  # before goto(), to catch the first redirect

        try:
            page.goto(config.url, wait_until="domcontentloaded")
        except Exception as exc:
            redirects.forget(page)
            context.close()
            browser.close()
            message = describe_navigation_error(exc, config.url, config.stability.nav_timeout_ms)
            if config.verbosity > 0:
                message += f"\n\nDetails:\n{exc}"
            raise NavigationError(message, could_not_connect=could_not_connect(exc)) from exc

        try:
            yield page
        finally:
            redirects.forget(page)
            context.close()
            browser.close()
