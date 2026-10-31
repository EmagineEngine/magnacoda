from __future__ import annotations

import contextlib
import time
from typing import Literal

from playwright.sync_api import Page
from pydantic import BaseModel

from magnacoda.config import StabilityConfig

# Installed once per page; records the timestamp of the most recent DOM mutation
# so Python-side polling can detect quiescence without relying on networkidle
# (unreliable on pages with polling/websocket traffic).
_OBSERVER_SCRIPT = """
() => {
    window.__magnacoda = window.__magnacoda || {};
    window.__magnacoda.lastMutationAt = performance.now();
    if (window.__magnacoda.observer) return;
    const observer = new MutationObserver(() => {
        window.__magnacoda.lastMutationAt = performance.now();
    });
    observer.observe(document.documentElement, {
        childList: true, subtree: true, attributes: true, characterData: true,
    });
    window.__magnacoda.observer = observer;
}
"""

StabilityReason = Literal["quiescent", "timeout", "selector_matched"]


class StabilityReport(BaseModel):
    settled: bool
    elapsed_ms: int
    reason: StabilityReason


def wait_for_stable(page: Page, config: StabilityConfig) -> StabilityReport:
    """Wait for the page's DOM to stop mutating (or a hard timeout), never hanging forever."""
    start = time.monotonic()

    if config.wait_for_selector:
        try:
            page.wait_for_selector(config.wait_for_selector, timeout=config.stability_timeout_ms)
            elapsed = int((time.monotonic() - start) * 1000)
            return StabilityReport(settled=True, elapsed_ms=elapsed, reason="selector_matched")
        except Exception:
            elapsed = int((time.monotonic() - start) * 1000)
            return StabilityReport(settled=False, elapsed_ms=elapsed, reason="timeout")

    deadline = start + (config.stability_timeout_ms / 1000)
    quiet_period_s = config.quiet_period_ms / 1000
    watching = False

    while True:
        try:
            if not watching:
                page.evaluate(_OBSERVER_SCRIPT)
                watching = True
                time.sleep(config.min_wait_ms / 1000)
            last_mutation_ms = page.evaluate("() => window.__magnacoda && window.__magnacoda.lastMutationAt")
            now_ms = page.evaluate("() => performance.now()")
        except Exception as exc:
            if "context was destroyed" not in str(exc) and "navigat" not in str(exc).lower():
                raise
            last_mutation_ms = None
        if last_mutation_ms is None:
            # The page moved on (a redirect by script): watch the new one instead.
            if time.monotonic() >= deadline:
                elapsed = int((time.monotonic() - start) * 1000)
                return StabilityReport(settled=False, elapsed_ms=elapsed, reason="timeout")
            with contextlib.suppress(Exception):
                remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                page.wait_for_load_state("domcontentloaded", timeout=remaining_ms)
            watching = False
            continue
        idle_s = (now_ms - last_mutation_ms) / 1000

        if idle_s >= quiet_period_s:
            if config.extra_wait_ms:
                time.sleep(config.extra_wait_ms / 1000)
            elapsed = int((time.monotonic() - start) * 1000)
            return StabilityReport(settled=True, elapsed_ms=elapsed, reason="quiescent")

        if time.monotonic() >= deadline:
            elapsed = int((time.monotonic() - start) * 1000)
            return StabilityReport(settled=False, elapsed_ms=elapsed, reason="timeout")

        time.sleep(min(0.1, max(0.01, quiet_period_s - idle_s)))
