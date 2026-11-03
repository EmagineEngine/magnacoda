"""The help pager in a real (pseudo-)terminal: alternate screen, keys, and what is left on screen."""

import fcntl
import os
import re
import select
import struct
import sys
import termios
import time

import pytest

from magnacoda.pager.screen import alternate_screen_codes

pty = pytest.importorskip("pty")  # not available on Windows

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or alternate_screen_codes({"TERM": "xterm-256color"}) is None,
    reason="needs a POSIX terminal database with an xterm entry",
)

ENTER = b"\x1b[?1049h"
LEAVE = b"\x1b[?1049l"
CMD = [sys.executable, "-m", "magnacoda"]


def _terminal_env() -> dict:
    """COLUMNS and LINES (set by pytest-xdist's workers) would win over the size set on the terminal."""
    env = {k: v for k, v in os.environ.items() if k not in ("COLUMNS", "LINES")}
    return dict(env, TERM="xterm-256color")


def _drain(fd, quiet=0.5, limit=6.0):
    """Read until the output has been quiet for a moment (or the child has exited). -> (bytes, exited)"""
    buf, last, end = b"", time.time(), time.time() + limit
    while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                return buf, True
            if not chunk:
                return buf, True
            buf, last = buf + chunk, time.time()
        elif buf and time.time() - last > quiet:
            break
    return buf, False


def run(args, keys=(), rows=12, cols=74, env=None):  # 70 columns of text inside the margins
    """Run magnacoda in a pseudo-terminal, send each key after the output settles. -> list of byte chunks"""
    child_env = _terminal_env()
    child_env.update(env or {})
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, CMD[:1] + CMD[1:] + list(args), child_env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    chunks = []
    buf, exited = _drain(fd, limit=8.0)
    chunks.append(buf)
    for key in keys:
        if exited:
            break
        os.write(fd, key)
        buf, exited = _drain(fd)
        chunks.append(buf)
    for _ in range(30):
        try:
            done, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            break
        if done:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
    os.close(fd)
    return chunks


def plain(data: bytes) -> str:
    text = data.decode(errors="replace")
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07", "", text).replace("\r", "")


def screen(data: bytes) -> dict[int, str]:
    """Rebuild the rows drawn by the pager from its cursor-positioning codes, without the left margin."""
    rows = {}
    for m in re.finditer(r"\x1b\[(\d+);1H(.*?)(?=\x1b\[\d+;1H|$)", data.decode(errors="replace"), re.S):
        rows[int(m.group(1))] = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", m.group(2)).removeprefix("  ")
    return rows


def after_leave(data: bytes) -> str:
    return plain(data.split(LEAVE, 1)[1]) if LEAVE in data else ""


def test_help_opens_a_pager_that_walks_sections_and_esc_restores_the_screen():
    chunks = run(["help"], [*[b" "] * 8, b"\x1b"])  # past the end of the overview, however it grows
    first = b"".join(chunks[:1])
    assert ENTER in first
    rows = screen(first)
    assert rows[2] == "magnacoda - Help"  # the title stays on top, under a blank row
    assert rows[max(rows) - 1].startswith("1/12 overview | g go")
    assert rows[max(rows)].startswith("Scroll: ↑ ↓ | lines 1-")
    assert any("accessibility scanner" in row for row in rows.values())
    assert "2/12 wizard" in plain(b"".join(chunks[1:9]))
    everything = b"".join(chunks)
    assert LEAVE in everything
    assert after_leave(everything).strip() == ""  # the help is gone; nothing is left behind


def test_readme_opens_in_the_same_pager_under_its_own_title():
    chunks = run(["readme"], [b"q"])
    rows = screen(chunks[0])
    assert rows[2] == "magnacoda - README"
    assert rows[max(rows) - 1].startswith("1/")
    assert LEAVE in b"".join(chunks) and after_leave(b"".join(chunks)).strip() == ""


def test_q_quits_like_esc():
    everything = b"".join(run(["help"], [b" ", b"q"]))
    assert LEAVE in everything and after_leave(everything).strip() == ""


def test_paging_past_the_very_end_quits_like_q():
    everything = b"".join(run(["help"], [b" "] * 120))  # well past the end, however long the help grows
    assert LEAVE in everything and after_leave(everything).strip() == ""


def test_arrow_keys_scroll_and_do_not_quit():
    chunks = run(["help"], [b"\x1b[B", b"\x1b[A", b"\x1b[6~", b"q"])
    assert [LEAVE in c for c in chunks] == [False, False, False, False, True]


def test_plain_help_and_a_bare_dashdash_help_open_every_section_in_the_pager():
    for args in (["help"], ["--help"]):
        chunks = run(args, [b"\x1b"])
        rows = screen(chunks[0])
        assert ENTER in chunks[0] and rows[2] == "magnacoda - Help"
        assert any(row.startswith("1/12 overview") for row in rows.values())
        assert LEAVE in b"".join(chunks)


def test_a_digit_jumps_to_a_section_and_g_lists_them():
    chunks = run(["help"], [b"7", b"\r", b"g", b"u", b"s", b"\r", b"q"], rows=16)
    assert "Go to: 7" in plain(chunks[1])
    assert "Options for scan" in plain(chunks[2]) and "7/12 scan" in plain(chunks[2])
    assert "Go to:" in plain(chunks[3]) and "9  examples" in plain(chunks[3])
    assert "4/12 usage" in plain(chunks[6])  # "us", the start of its name
    assert LEAVE in chunks[7]


def test_a_document_typed_in_the_open_list_opens_there_and_a_wrong_one_says_why():
    chunks = run(["help"], [b"o", b"docs starting", b"\r", b"", b"q"], rows=24, cols=90)  # b"": more time
    assert "Open: docs starting" in plain(chunks[2])
    shown = plain(chunks[3] + chunks[4])
    assert "magnacoda - Manual" in shown and "Starting magnacoda" in shown
    assert "Opened Manual | Back: o, Enter" in shown
    everything = b"".join(chunks)
    assert LEAVE in chunks[5] and plain(everything.rsplit(LEAVE, 1)[1]).strip() == ""  # nothing left behind
    chunks = run(["help"], [b"o", b"nowhere", b"\r", b"\x1b", b"q"], rows=24, cols=90)
    assert "No document named 'nowhere'" in plain(chunks[3])


def test_slash_finds_a_phrase_across_the_help_and_n_goes_to_the_next_one():
    chunks = run(["help"], [b"/", b"checklist", b"\r", b"n", b"\x1b", b"q"], rows=24, cols=100)
    assert "Find: checklist" in plain(chunks[2])
    found = plain(chunks[3])
    assert "Find: checklist" in found and "1 of " in found and "Next: n or →" in found
    assert "2 of " in plain(chunks[4])
    assert "Find: /" in plain(chunks[5]) and LEAVE in chunks[6]


def test_the_off_switch_prints_everything_plainly():
    text = b"".join(run(["help"], rows=12, env={"MAGNACODA_PAGER": "off"}))
    assert ENTER not in text and "Options for scan" in plain(text) and "Example scans" in plain(text)


def test_the_shell_returns_to_its_prompt_after_the_pager():
    chunks = run([], [b"help\n", b"\x1b", b"exit\n"], rows=14)
    everything = b"".join(chunks)
    assert ENTER in everything and LEAVE in everything
    back = after_leave(everything)
    assert "magnacoda »" in back  # back at the prompt
    assert "accessibility scanner - type a command" not in back  # the screen as it was: no new banner
    assert "\x1b[H" not in everything.split(LEAVE, 1)[1].decode(errors="replace")  # and no page fed


def test_resizing_the_terminal_redraws_the_page():
    child_env = _terminal_env()
    pid, fd = pty.fork()
    if pid == 0:
        os.execve(sys.executable, CMD + ["help"], child_env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 12, 74, 0, 0))
    first, _ = _drain(fd, limit=8.0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 20, 64, 0, 0))
    after, _ = _drain(fd, quiet=0.8)
    os.write(fd, b"q")
    _drain(fd)
    os.close(fd)
    os.waitpid(pid, 0)
    before_rows, after_rows = screen(first), screen(after)
    assert max(before_rows) == 12 and max(after_rows) == 20
    assert before_rows[11].startswith("1/12 overview | ")
    assert before_rows[12].startswith("Scroll: ↑ ↓ | lines 1-6 of")  # less the top, title gap and gap rows
    assert after_rows[2] == "magnacoda - Help" and after_rows[20].startswith("Scroll: ↑ ↓ | lines")


def test_c_chooses_a_color_that_fills_the_screen_and_is_saved_for_next_time():
    from magnacoda import preferences

    chunks = run(["help"], [b"c", b"\x1b[B", b"\r", b"q"], env={"COLORTERM": "truecolor"})
    rows = screen(chunks[1])
    assert "Colors:" in rows.values() and any(row.startswith("› 1  default") for row in rows.values())
    amber = b"\x1b[38;2;224;154;0;48;2;0;0;0m"
    assert amber + b"\x1b[2J" in chunks[2]  # the preview: the whole screen in amber at once
    assert "colors = amber" in preferences.preferences_path().read_text()
    again = run(["help"], [b"q"], env={"COLORTERM": ""})
    assert b"\x1b[38;5;172;48;5;16m" in again[0]  # without COLORTERM: the 256-color amber


def test_a_long_address_is_one_whole_hyperlink_never_split_across_rows(tmp_path):
    address = "https://dequeuniversity.com/rules/axe/4.10/color-contrast?application=magnacoda"
    page = tmp_path / "notes.md"
    page.write_text(f"# Notes\n\n## Links\n\nThe rule is explained at {address} in full.\n")
    chunks = run(["view", str(page)], [b"q"], cols=50)
    drawn = chunks[0]  # one section: it opens on its page
    assert f"\x1b]8;;{address}\x1b\\".encode() in drawn  # Ctrl+click opens the whole address
    rows = screen(drawn)
    shown = [row for row in rows.values() if "dequeuniversity" in row]
    assert len(shown) == 1 and "…" in shown[0]  # shortened to fit one row, never split over two


def test_tab_and_enter_follow_a_section_link_and_say_when_a_page_cant_open(tmp_path):
    page = tmp_path / "notes.md"
    page.write_text(
        "# Notes\n\nSee [the second part](#part-two) or https://docs.test/page.\n\n"
        "## Part one\n\nOne.\n\n## Part two\n\nTwo is here.\n\n## Part three\n\n"
        + "Long enough for pages. "
        * 200
    )
    no_display = {"DISPLAY": "", "WAYLAND_DISPLAY": ""}
    chunks = run(["view", str(page), "introduction"], [b"\t", b"\r", b"q"], env=no_display)
    assert "Links 1/2: section 3 | Enter go" in plain(chunks[1])
    assert "Two is here." in plain(chunks[2])
    chunks = run(["view", str(page), "introduction"], [b"\t", b"\t", b"\r", b"q"], env=no_display)
    assert "No browser to open it in here." in plain(chunks[3])


def test_arrows_in_the_section_list_cross_its_columns(tmp_path):
    page = tmp_path / "parts.md"
    page.write_text(
        "# Parts\n\n" + "".join(f"## Part {n}\n\nThis is part {n}.{' More.' * 100}\n\n" for n in range(1, 9))
    )
    right = b"\x1b[C"
    chunks = run(["view", str(page)], [b"\t", right, b"\r", b"q"])  # opens on the g list, 2 columns
    assert "Links: 1, Part 1" in plain(chunks[1])
    assert "Links: 5, Part 5" in plain(chunks[2])  # same row, next column
    assert "This is part 5." in plain(chunks[3])


def test_the_manual_s_g_list_shows_its_groups_and_subsections():
    chunks = run(["docs"], [b"g", b"\x1b", b"q"], rows=40, cols=104)
    shown = plain(chunks[1])
    assert "magnacoda - Manual" in shown
    assert "What do the results show?" in shown and "How do I choose what to scan?" in shown
    assert "Top-10 ranking" in shown and "GitLab CI" in shown


def test_help_shows_its_italic_and_bold_on_screen():
    chunks = run(["help"], [b"q"])
    assert b"\x1b[3mmagnacoda" in chunks[0]  # *magnacoda*, in italics
