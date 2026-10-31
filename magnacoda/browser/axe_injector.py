from __future__ import annotations

import contextlib
import json
from importlib import resources

from playwright.sync_api import CDPSession, Page

from magnacoda.exceptions import AxeInjectionError
from magnacoda.findings.wcag_map import axe_tags_for

_AXE_SOURCE_CACHE: str | None = None


def _axe_resource(name: str) -> str:
    return (resources.files("magnacoda") / "vendor" / "axe-core" / name).read_text(encoding="utf-8")


def _load_axe_source() -> str:
    global _AXE_SOURCE_CACHE
    if _AXE_SOURCE_CACHE is None:
        _AXE_SOURCE_CACHE = _axe_resource("axe.min.js")
    return _AXE_SOURCE_CACHE


def axe_core_version() -> str:
    return _axe_resource("VERSION").strip()


# Sets ?application=magnacoda on the Deque help links in the results (default: axeAPI).
_BRANDING = "axe.configure({branding: {application: 'magnacoda'}});"


def run_axe(
    page: Page, wcag_version: str, level: str, include_best_practice: bool, rules: list[str] | None = None
) -> dict:
    """Run axe-core on the page as it is now; with `rules`, only those (for a recheck).

    In Chromium it runs in an isolated world, so pages that patch built-ins (Prototype.js and the like)
    can't break it ("Result for unknown rule") and CSP can't block it. Firefox gets a script tag.
    """
    run_only = (
        {"type": "rule", "values": rules}
        if rules
        else {"type": "tag", "values": axe_tags_for(wcag_version, level, include_best_practice)}
    )
    try:
        cdp: CDPSession | None = page.context.new_cdp_session(page)
    except Exception:  # noqa: BLE001 - not Chromium
        cdp = None
    if cdp is not None:
        try:
            return _run_isolated(cdp, run_only)
        finally:
            with contextlib.suppress(Exception):
                cdp.detach()
    page.add_script_tag(content=_load_axe_source())
    try:
        page.evaluate(_BRANDING)
        raw = page.evaluate("(runOnly) => axe.run(document, { runOnly })", run_only)
    except Exception as exc:
        raise AxeInjectionError(f"axe-core failed to run: {exc}") from exc
    return raw


def _run_isolated(cdp: CDPSession, run_only: dict) -> dict:
    try:
        frame_id = cdp.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        world = cdp.send("Page.createIsolatedWorld", {"frameId": frame_id, "worldName": "magnacoda-axe"})
        context = world["executionContextId"]
        _evaluate(cdp, context, _load_axe_source())
        _evaluate(cdp, context, _BRANDING)
        options = json.dumps({"runOnly": run_only})
        raw = _evaluate(cdp, context, f"axe.run(document, {options})")
        if not isinstance(raw, dict):
            raise AxeInjectionError("axe-core failed to run: it returned no results")
        return raw
    except AxeInjectionError:
        raise
    except Exception as exc:
        raise AxeInjectionError(f"axe-core failed to run: {exc}") from exc


def _evaluate(cdp: CDPSession, context: int, expression: str) -> object:
    result = cdp.send(
        "Runtime.evaluate",
        {"expression": expression, "contextId": context, "awaitPromise": True, "returnByValue": True},
    )
    if "exceptionDetails" in result:
        details = result["exceptionDetails"]
        message = (details.get("exception") or {}).get("description") or details.get("text", "")
        raise AxeInjectionError(f"axe-core failed to run: {message.splitlines()[0] if message else 'error'}")
    return result["result"].get("value")
