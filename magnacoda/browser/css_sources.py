"""The CSS rule, file and line behind a CSS-caused problem, like the Styles panel in DevTools.

The DevTools protocol lists matching rules in cascade order, so the winning declaration is the last one,
with !important and inline styles taken into account. Source maps, when present, give the original
file (e.g. src/_links.scss:12). Chromium only.
"""

from __future__ import annotations

import base64
import contextlib
import re
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlparse

from playwright.sync_api import CDPSession, Page

from magnacoda.findings.models import CssSource, Finding

# Property groups per rule, one source each. The first group is always reported (possibly the
# browser default); the rest only if the site sets them.
WATCH: dict[str, tuple[tuple[str, ...], ...]] = {
    "color-contrast": (("color",), ("background-color", "background")),
    "color-contrast-enhanced": (("color",), ("background-color", "background")),
    "link-in-text-block": (("text-decoration-line", "text-decoration"), ("color",)),
    "magnacoda/focus-not-visible": (("outline-style", "outline", "outline-width"), ("box-shadow",)),
    "magnacoda/text-spacing-clipped": (
        ("overflow", "overflow-y", "overflow-x"),
        ("height", "max-height"),
        ("line-height",),
    ),
    "magnacoda/resize-clipped": (("overflow", "overflow-y", "overflow-x"), ("height", "max-height")),
    "target-size": (
        ("width", "min-width", "inline-size"),
        ("height", "min-height", "block-size"),
        ("padding",),
    ),
}
# Shown while the element has the keyboard focus: its :focus and :focus-visible rules apply.
FOCUSED = {"magnacoda/focus-not-visible"}
# Properties an element takes from its parent when it doesn't set them itself.
_INHERITED = {"color", "line-height"}
LIMIT = 60  # elements looked up per scan: enough for a report, quick on a slow computer
_MAP_BYTES = 5_000_000  # a source map bigger than this is left alone


@dataclass
class _Candidate:
    rank: tuple[int, int, int]  # (!important, the element's own style attribute, order)
    prop: dict
    rule: dict | None  # None: the style attribute


def attach_sources(page: Page, findings: list[Finding], limit: int = LIMIT) -> None:
    """Fill in `css` for CSS-caused findings (up to `limit` elements). No-op in Firefox."""
    wanted = [f for f in findings if f.rule_id in WATCH and f.selector]
    if not wanted:
        return
    try:
        cdp: CDPSession = page.context.new_cdp_session(page)
    except Exception:  # noqa: BLE001 - not Chromium
        return
    reader = _Reader(page, cdp)
    try:
        reader.start()
        looked: dict[tuple[str, bool], dict | None] = {}
        for finding in wanted:
            focused = finding.rule_id in FOCUSED
            key = (finding.selector, focused)
            if key not in looked:
                if len(looked) >= limit:
                    break
                looked[key] = reader.matched(finding.selector, focused)
            matched = looked[key]
            if matched is None:
                continue
            sources = []
            for number, group in enumerate(WATCH[finding.rule_id]):
                source = reader.source(matched, group, focused)
                if source is None or (number and source.kind in ("not-set", "browser-default")):
                    continue
                sources.append(source)
            finding.css = sources
    except Exception:  # noqa: BLE001 - a page that won't be read: the findings keep their fixes
        pass
    finally:
        with contextlib.suppress(Exception):
            cdp.detach()


class _Reader:
    def __init__(self, page: Page, cdp: CDPSession) -> None:
        self.page = page
        self.cdp = cdp
        self.sheets: dict[str, dict] = {}
        self.maps: dict[str, object | None] = {}
        self.root = 0

    def start(self) -> None:
        self.cdp.on(
            "CSS.styleSheetAdded",
            lambda event: self.sheets.__setitem__(event["header"]["styleSheetId"], event["header"]),
        )
        self.cdp.send("DOM.enable")
        self.cdp.send("CSS.enable")
        self.root = self.cdp.send("DOM.getDocument", {"depth": 0})["root"]["nodeId"]

    def matched(self, selector: str, focused: bool) -> dict | None:
        """Matching rules for the element (focused if asked), or None if it's gone or in a frame."""
        try:
            node = self.cdp.send("DOM.querySelector", {"nodeId": self.root, "selector": selector}).get(
                "nodeId"
            )
        except Exception:  # noqa: BLE001 - not a selector the page understands
            return None
        if not node:
            return None
        if focused:
            self.cdp.send(
                "CSS.forcePseudoState", {"nodeId": node, "forcedPseudoClasses": ["focus", "focus-visible"]}
            )
        try:
            matched = self.cdp.send("CSS.getMatchedStylesForNode", {"nodeId": node})
        finally:
            if focused:
                self.cdp.send("CSS.forcePseudoState", {"nodeId": node, "forcedPseudoClasses": []})
        attributes = self.cdp.send("DOM.getAttributes", {"nodeId": node}).get("attributes", [])
        names = dict(zip(attributes[::2], attributes[1::2], strict=False))
        matched["classes"] = names.get("class", "").split()
        return matched

    def source(self, matched: dict, group: tuple[str, ...], focused: bool) -> CssSource | None:
        """Where the winning declaration for these properties comes from."""
        own = _candidates(matched.get("matchedCSSRules", []), matched.get("inlineStyle"), group)
        inherited_from = False
        if not own and group[0] in _INHERITED:
            for entry in matched.get("inherited", []):  # the nearest ancestor first
                own = _candidates(entry.get("matchedCSSRules", []), entry.get("inlineStyle"), group)
                if own:
                    inherited_from = True
                    break
        if not own:
            return CssSource(property=group[0], kind="not-set")
        best = max(own, key=lambda c: c.rank)
        declaration = _declaration(best.prop)
        state = ":focus" if focused else ""
        if best.rule is None:
            return CssSource(
                property=group[0],
                declaration=declaration,
                kind="style-attribute",
                inherited=inherited_from,
                state=state,
            )
        rule = best.rule
        if rule.get("origin") == "user-agent":
            return CssSource(property=group[0], declaration=declaration, kind="browser-default", state=state)
        selector = rule.get("selectorList", {}).get("text", "")
        header = self.sheets.get(rule.get("style", {}).get("styleSheetId", ""), {})
        found = CssSource(
            property=group[0],
            declaration=declaration,
            selector=selector,
            kind="stylesheet",
            inherited=inherited_from,
            state=state,
            utility_class=not inherited_from and _is_own_class(selector, matched.get("classes", [])),
        )
        where = best.prop.get("range") or rule.get("style", {}).get("range") or {}
        line, column = where.get("startLine"), where.get("startColumn", 0)
        if header.get("isConstructed") or (not header.get("sourceURL") and not header.get("isInline")):
            found.kind = "script"
        elif header.get("isInline"):
            found.kind = "style-element"
            found.file = self._short(header.get("sourceURL") or self.page.url)
            if line is not None:
                found.line = int(header.get("startLine", 0)) + int(line) + 1
        else:
            found.file = self._short(header["sourceURL"])
            if line is not None:
                found.line = int(line) + 1
        if line is not None and header.get("sourceMapURL"):
            self._original(found, header, int(line), int(column))
        return found

    def _short(self, url: str) -> str:
        """A stylesheet on the scanned site by its path; one elsewhere by its full address."""
        # A sheet a script added names itself relative to the page (`/*# sourceURL=css/a.css */`).
        page, sheet = urlparse(self.page.url), urlparse(urljoin(self.page.url, url))
        if sheet.scheme in ("http", "https") and (sheet.scheme, sheet.netloc) == (page.scheme, page.netloc):
            return sheet.path + (f"?{sheet.query}" if sheet.query else "")
        return url

    def _original(self, found: CssSource, header: dict, line: int, column: int) -> None:
        """Through the stylesheet's source map: the file and line the developer edits."""
        base = header.get("sourceURL") or self.page.url
        address = urljoin(base, header["sourceMapURL"])
        if address not in self.maps:
            self.maps[address] = self._load_map(address)
        index = self.maps[address]
        if index is None:
            return
        if header.get("isInline"):  # positions in the map are within the <style> element's text
            line -= int(header.get("startLine", 0))
            if line == 0:
                column -= int(header.get("startColumn", 0))
        try:
            token = index.lookup(line=line, column=column)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a position the map doesn't cover
            return
        if token is None or not getattr(token, "src", None):
            return
        found.original_file = self._source_path(str(token.src), address)
        found.original_line = int(token.src_line) + 1

    def _source_path(self, src: str, map_address: str) -> str:
        """Source map path as the developer knows it: webpack:///./src/a.scss -> src/a.scss."""
        tidy = _tidy_source(src)
        if tidy != src or urlparse(src).scheme or map_address.startswith("data:"):
            return tidy
        return self._short(urljoin(map_address, src))

    def _load_map(self, address: str) -> object | None:
        import sourcemap

        try:
            if address.startswith("data:"):
                head, _, body = address.partition(",")
                text = base64.b64decode(body).decode("utf-8") if ";base64" in head else unquote(body)
            elif urlparse(address).scheme in ("http", "https"):
                response = self.page.request.get(address, timeout=5000)
                if not response.ok or len(response.body()) > _MAP_BYTES:
                    return None
                text = response.text()
            else:
                return None
            return sourcemap.loads(text)
        except Exception:  # noqa: BLE001 - missing, unreadable or broken map: the built file is shown
            return None


def _candidates(rules: list[dict], inline: dict | None, group: tuple[str, ...]) -> list[_Candidate]:
    found = []
    for order, match in enumerate(rules):
        rule = match.get("rule", {})
        for prop in rule.get("style", {}).get("cssProperties", []):
            if _counts(prop, group, rule.get("origin") == "user-agent"):
                found.append(_Candidate((int(bool(prop.get("important"))), 0, order), prop, rule))
    for prop in (inline or {}).get("cssProperties", []):
        if _counts(prop, group, False):
            found.append(_Candidate((int(bool(prop.get("important"))), 1, len(rules)), prop, None))
    return found


def _counts(prop: dict, group: tuple[str, ...], user_agent: bool) -> bool:
    """An active, valid declaration of one of these properties."""
    if prop.get("name") not in group or prop.get("disabled") or prop.get("parsedOk") is False:
        return False
    return user_agent or "range" in prop or bool(prop.get("text"))


def _declaration(prop: dict) -> str:
    text = str(prop.get("text") or f"{prop.get('name')}: {prop.get('value')}").strip()
    return " ".join(text.rstrip(";").split())


def _is_own_class(selector: str, classes: list[str]) -> bool:
    """A single-class rule like Tailwind's `.no-underline`: the fix goes in the HTML, not the CSS."""
    text = selector.strip()
    if not text.startswith(".") or any(c in text[1:] for c in " >+~,[#") or text.count(".") > 1:
        return False
    name = re.split(r"(?<!\\):", text[1:])[0]  # without :hover and the like
    return re.sub(r"\\(.)", r"\1", name) in classes


def _tidy_source(path: str) -> str:
    """`webpack:///./src/_links.scss` -> `src/_links.scss`."""
    for prefix in ("webpack:///", "webpack://", "vite://"):
        if path.startswith(prefix):
            path = path[len(prefix) :]
    while path.startswith("./"):
        path = path[2:]
    return path
