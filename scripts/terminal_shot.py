"""A picture of what the terminal shows: runs a command in a pseudo-terminal, types keys into it, and
saves the screen as HTML and PNG (pyte draws the screen, Playwright takes the picture). POSIX only.

    python scripts/terminal_shot.py OUT [--size 90x30] [--background 1e1e1e] [--wait 4]
        [--key KEYS]... -- COMMAND...

Each --key is typed after the screen settles (escapes such as \\r and \\x1b work); OUT gets .html and
.png. The terminal answers magnacoda's question about its colors with --background, so the name's blue
shows as in a real terminal.
"""

from __future__ import annotations

import argparse
import fcntl
import html
import os
import pty
import select
import struct
import sys
import termios
import time

import pyte

_NAMED = {
    "black": "#000000", "red": "#cd3131", "green": "#0dbc79", "brown": "#e5e510", "blue": "#2472c8",
    "magenta": "#bc3fbc", "cyan": "#11a8cd", "white": "#e5e5e5",
}  # fmt: skip


def _color(value: str, default: str) -> str:
    if value == "default":
        return default
    return "#" + value if len(value) == 6 else _NAMED.get(value, default)


def _html(screen: pyte.Screen, background: str, foreground: str) -> str:
    rows = []
    for y in range(screen.lines):
        cells = []
        for x in range(screen.columns):
            ch = screen.buffer[y][x]
            fg, bg = _color(ch.fg, foreground), _color(ch.bg, background)
            if ch.reverse:
                fg, bg = bg, fg
            style = f"color:{fg};background:{bg};"
            style += "font-weight:bold;" * ch.bold + "font-style:italic;" * ch.italics
            style += "text-decoration:underline;" * ch.underscore
            cells.append(f'<span style="{style}">{html.escape(ch.data or " ")}</span>')
        rows.append("".join(cells))
    return (
        f"<html><body style='margin:0;background:{background}'><pre style='font:15px/1.25 "
        f"DejaVu Sans Mono,monospace;margin:8px'>" + "\n".join(rows) + "</pre></body></html>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out")
    parser.add_argument("--size", default="90x30")
    parser.add_argument("--background", default="1e1e1e")
    parser.add_argument("--wait", type=float, default=4.0, help="seconds before the first key")
    parser.add_argument("--key", action="append", default=[])
    argv = sys.argv[1:]
    if "--" not in argv:
        parser.error("put the command after --")
    split = argv.index("--")
    args = parser.parse_args(argv[:split])
    command = argv[split + 1 :]
    columns, lines = (int(n) for n in args.size.split("x"))
    back = args.background.lstrip("#")
    light = sum(int(back[i : i + 2], 16) for i in (0, 2, 4)) > 384
    foreground = "#333333" if light else "#cccccc"

    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(COLORTERM="truecolor", TERM="xterm-256color")
        os.execvp(command[0], command)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", lines, columns, 0, 0))
    screen = pyte.Screen(columns, lines)
    stream = pyte.ByteStream(screen)
    hexes = "/".join(back[i : i + 2] * 2 for i in (0, 2, 4))
    fore = "/".join(foreground[1:][i : i + 2] * 2 for i in (0, 2, 4))
    answer = f"\x1b]10;rgb:{fore}\x1b\\\x1b]11;rgb:{hexes}\x1b\\\x1b[?62c".encode()

    def pump(seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if not ready:
                continue
            try:
                data = os.read(fd, 65536)
            except OSError:
                return
            if b"\x1b]11;?" in data:
                os.write(fd, answer)
            stream.feed(data)

    pump(args.wait)
    for key in args.key:
        os.write(fd, key.encode().decode("unicode_escape").encode("latin-1"))
        pump(2.5)
    with open(args.out + ".html", "w", encoding="utf-8") as page:
        page.write(_html(screen, "#" + back, foreground))
    os.kill(pid, 15)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        tab = browser.new_page(viewport={"width": columns * 9 + 40, "height": int(lines * 18.75) + 40})
        tab.goto("file://" + os.path.abspath(args.out + ".html"))
        tab.screenshot(path=args.out + ".png")
        browser.close()


if __name__ == "__main__":
    main()
