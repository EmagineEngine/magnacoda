"""The title screen on the first shell of the day (title.py)."""

import io

import pytest
from rich.console import Console

from magnacoda import title
from magnacoda.pager.colors import contrast


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def at_a_terminal(monkeypatch):
    title.state_path().unlink()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    return Console(file=Terminal(), force_terminal=True, width=80, height=24)


def test_it_shows_once_a_day(at_a_terminal):
    assert title.due(at_a_terminal, today="2026-11-01")
    title.mark_shown("2026-11-01")
    assert not title.due(at_a_terminal, today="2026-11-01")
    assert title.due(at_a_terminal, today="2026-11-02")


@pytest.mark.parametrize(("setting", "after_shown"), [("always", True), ("never", False), ("daily", False)])
def test_the_title_setting_says_how_often(at_a_terminal, setting, after_shown):
    from magnacoda import preferences

    preferences.set_value("display", "title", setting)
    title.mark_shown("2026-11-01")
    assert title.due(at_a_terminal, today="2026-11-01") is after_shown
    assert title.due(at_a_terminal, forced=True, today="2026-11-01")


def test_not_with_typing_off_or_without_a_terminal(at_a_terminal, monkeypatch):
    monkeypatch.setenv("MAGNACODA_TYPING", "off")
    assert not title.due(at_a_terminal)
    monkeypatch.delenv("MAGNACODA_TYPING")
    assert not title.due(Console(file=io.StringIO()))


def test_the_lines_are_centered_a_third_of_the_way_down():
    top, lines = title.lines("magnacoda", 80, 24)
    assert top == (24 - len(lines)) // 3
    assert lines[0].strip() == "magnacoda" and lines[-1].strip() == title.PRESS
    assert all(len(line) - len(line.lstrip()) == (80 - len(line.strip())) // 2 for line in lines if line)
    assert "magnacoda.dev" in lines[4]


def test_a_short_or_narrow_terminal_gets_just_the_lines():
    top, short = title.lines("magnacoda", 80, 10)
    assert top == 0 and len(short) < len(title.lines("magnacoda", 80, 24)[1])
    assert all(len(line) <= 20 for line in title.lines("magnacoda", 20, 24)[1])


@pytest.mark.parametrize("background", ["#000000", "#1e1e1e", "#ffffff", "#fdf6e3"])
def test_the_glow_only_raises_the_contrast_and_ends_on_the_plain_name(background):
    from magnacoda.pager.screen import title_blue

    back = tuple(bytes.fromhex(background[1:]))
    base = title_blue(back)
    frames = title.glow_colors(base, back, 9)
    hexes = {"#{:02x}{:02x}{:02x}".format(*c) for frame in frames for c in frame}
    assert all(contrast(color, background) >= 7 for color in hexes)
    assert frames[-1] == [base] * 9 and len(hexes) > 1
    brightest = [max(range(9), key=lambda n, f=f: abs(sum(f[n]) - sum(base))) for f in frames[2:-3]]
    assert brightest == sorted(brightest)  # the band travels left to right


def test_what_is_typed_at_the_title_is_returned(monkeypatch):
    console = Console(file=io.StringIO(), force_terminal=True, width=80, height=24)
    monkeypatch.setattr(console, "input", lambda prompt: "  scan https://x  ")
    assert title.show(console, "magnacoda", "bold", "#000000") == "scan https://x"
    out = console.file.getvalue()
    assert "Learn to fix them." in out and "magnacoda.dev" in out


def test_the_glow_runs_where_typing_is_on_and_ends_on_the_plain_name():
    from magnacoda.pager.screen import title_blue

    console = Console(file=Terminal(), force_terminal=True, color_system="truecolor", width=80)
    title.glow(console, "magnacoda", "bold", "#000000")
    out = console.file.getvalue()
    r, g, b = title_blue((0, 0, 0))
    assert out.count("\r") == title.GLOW_FRAMES + 1
    assert f"38;2;{r};{g};{b}m" in out.split("\r")[-1]
    assert out.startswith("\x1b[?25l") and out.rstrip().endswith("\x1b[?25h")  # cursor hidden, then back
    plain = Console(file=io.StringIO(), force_terminal=True, color_system="truecolor", width=80)
    title.glow(plain, "magnacoda", "bold", "#000000")
    assert "\r" not in plain.file.getvalue() and "?25l" not in plain.file.getvalue()


def test_news_comes_under_the_version_with_its_command_in_bold():
    top, lines = title.lines("magnacoda", 80, 24, ["magnacoda 0.5.0 is available - type update"])
    assert lines[5] == "" and lines[6].strip() == "magnacoda 0.5.0 is available - type update"
    assert title._styled(lines[6]).endswith("type [bold]update[/bold]")
    assert title._styled(lines[4]).startswith("[dim]")  # the version line
