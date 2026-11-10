"""Web addresses as real terminal hyperlinks (OSC 8), never broken across lines.

A terminal finds an address by looking at one line at a time, so an address that wraps only opens its
first part. Here every address is marked as a hyperlink, which the terminal opens whole, wherever it
wraps; and an address too long for a line is shown shortened in the middle ("…"), with the full
address kept in the link, so it is never broken either. Terminals without hyperlinks get the plain
text, as before. Standard library only.
"""

from __future__ import annotations

import inspect
import os
import re
import sys
from collections.abc import Callable, Mapping

from magnacoda.pager.emphasis import mark as mark_emphasis
from magnacoda.pager.emphasis import style as style_emphasis
from magnacoda.pager.tint import mark as mark_code

Wrapper = Callable[[str, int], list[str]]

OPEN = "\x1b]8;;{url}\x1b\\"
CLOSE = "\x1b]8;;\x1b\\"
UNDERLINE, NO_UNDERLINE = "\x1b[4m", "\x1b[24m"
# Starts a line of a code block: a code that changes nothing on screen ("default font"), so that
# addresses in code are never made into links.
CODE_MARK = "\x1b[10m"

# An address in running text, without the brackets or the punctuation that end a sentence around it.
URL = re.compile(r"(?<![\w/])https?://[A-Za-z0-9][^\s<>()\[\]`\"']*")
_TRAILING = ".,;:!?*_"
# Words that make an address a placeholder, never a link (https://example.com, http://mysite).
PLACEHOLDERS = ("example", "mysite")
# Escape sequences, which take no room on screen: CSI (colors, underline) and OSC (hyperlinks).
_CODE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_LEAD = re.compile(r"[ \t]*(?:(?:[-*+>]|\d+[.)])[ \t]+)*")
_FENCE = re.compile(r"^\s*(```|~~~)")
_MIN_ROOM = 20


def supported(env: Mapping[str, str] | None = None, platform: str = sys.platform) -> bool:
    """Whether the terminal is likely to understand hyperlinks. Those that don't would show the text
    only, which loses the address, so the known ones without them get plain text."""
    env = os.environ if env is None else env
    if env.get("TERM", "") in ("linux", "dumb") or env.get("TERM_PROGRAM") == "Apple_Terminal":
        return False
    if platform == "win32":
        # Windows Terminal has them, and so do VS Code's (since 1.72) and PyCharm's; the old console doesn't.
        return (
            bool(env.get("WT_SESSION"))
            or env.get("TERM_PROGRAM") == "vscode"
            or env.get("TERMINAL_EMULATOR", "").startswith("JetBrains")
        )
    return True


def found(text: str) -> list[tuple[int, int]]:
    """(start, end) of each address in `text` to make a link, without the punctuation after it.

    Addresses in inline code (`...`) and placeholders (with a word from PLACEHOLDERS, such as
    https://example.com) are left out.
    """
    code = [match.span() for match in re.finditer(r"`[^`]*`", text)]
    spans = []
    for match in URL.finditer(text):
        end = match.end()
        while end > match.start() and text[end - 1] in _TRAILING:
            end -= 1
        if any(word in text[match.start() : end].lower() for word in PLACEHOLDERS):
            continue
        if any(a <= match.start() < b for a, b in code):
            continue
        spans.append((match.start(), end))
    return spans


def shorten(url: str, room: int) -> str:
    """The address itself if it fits in `room`, else its start and end around "…"."""
    if len(url) <= room:
        return url
    room = max(room, _MIN_ROOM)
    head = room - room // 3 - 1
    site = url.find("/", url.find("//") + 2)  # keep the whole site name when there's room for it
    if head < site < room - 6:
        head = site
    return url[:head] + "…" + url[-(room - head - 1) :]


def prepare(text: str, width: int) -> tuple[str, dict[str, str]]:
    """Shorten each address too long for its line; -> (text, {shown: full address}).

    The room for an address is the width less the line's indent and list marker, and a little more
    for the marker the renderer may draw. Addresses in code (backticks or fenced blocks) are left as
    they are.
    """
    full: dict[str, str] = {}
    out = []
    in_code = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            in_code = not in_code
        if in_code or "http" not in line:
            out.append(line)
            continue
        lead = _LEAD.match(line)
        room = max(width - (lead.end() if lead else 0) - 4, _MIN_ROOM)
        pieces = re.split(r"(`[^`]*`)", line)  # odd pieces are inline code
        for n in range(0, len(pieces), 2):
            piece = pieces[n]
            for start, end in reversed(found(piece)):
                if piece[:start].endswith(("](", "<")):
                    continue  # a Markdown link's address: the renderer links it
                url = piece[start:end]
                shown = shorten(url, room)
                if shown != url:
                    full[shown] = url
                    piece = piece[:start] + shown + piece[end:]
            pieces[n] = piece
        out.append("".join(pieces))
    return "\n".join(out), full


def linkify(line: str, full: Mapping[str, str] | None = None) -> str:
    """Mark each address in a laid-out line as an underlined hyperlink, leaving any link the line
    already has (a Markdown link drawn by the renderer) as it is."""
    full = full or {}
    if line.startswith(CODE_MARK):
        return line
    pieces = _CODE.split(line)
    codes = _CODE.findall(line)
    inside = False
    out = []
    for n, piece in enumerate(pieces):
        if not inside:
            for start, end in reversed(found(piece)):
                shown = piece[start:end]
                url = full.get(shown, shown)
                link = OPEN.format(url=url) + UNDERLINE + shown + NO_UNDERLINE + CLOSE
                piece = piece[:start] + link + piece[end:]
        out.append(piece)
        if n < len(codes):
            code = codes[n]
            if code.startswith("\x1b]8;"):
                inside = not code.startswith(CLOSE)
            out.append(code)
    return "".join(out)


def visible(line: str) -> str:
    """The line as it shows on screen, without its codes."""
    return _CODE.sub("", line)


def wrapper(wrap: Wrapper, hyperlinks: bool = True, emphasis: bool = False, code: bool = False) -> Wrapper:
    """`wrap` for paging: with `hyperlinks`, addresses kept whole and made into hyperlinks. A wrapper
    that takes `hyperlinks` (the Markdown renderer) also draws its own links as hyperlinks, and marks
    its code blocks (CODE_MARK) so nothing in them becomes a link, also for Tab. With `emphasis`,
    *italic* and **bold** in text that isn't Markdown are shown as such (see emphasis.py). With `code`,
    code is marked for its own background (see tint.py)."""
    takes_links = "hyperlinks" in inspect.signature(wrap).parameters

    def wrapped(text: str, width: int) -> list[str]:
        if emphasis:
            text = mark_emphasis(text)
        prepared, full = prepare(text, width) if hyperlinks else (text, {})
        if takes_links:
            lines = wrap(prepared, width, hyperlinks=hyperlinks, mark_code=True)  # type: ignore[call-arg]
        else:
            lines = wrap(prepared, width)
        if emphasis:
            lines = style_emphasis(lines)
        if code:
            lines = mark_code(lines)
        return [linkify(line, full) for line in lines] if hyperlinks else lines

    return wrapped
