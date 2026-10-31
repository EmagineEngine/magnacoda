import io

import pytest
from rich.console import Console

from magnacoda import preferences, teletype


class _Terminal(io.StringIO):
    """A stream that says it's a terminal, recording each write separately."""

    def __init__(self):
        super().__init__()
        self.writes: list[str] = []

    def isatty(self):
        return True

    def write(self, text):
        self.writes.append(text)
        return super().write(text)


@pytest.fixture
def no_waiting(monkeypatch):
    pauses = []
    monkeypatch.setattr(teletype.time, "sleep", pauses.append)
    monkeypatch.delenv("MAGNACODA_TYPING", raising=False)
    return pauses


def test_typing_is_only_for_a_terminal_and_can_be_switched_off(no_waiting):
    assert teletype.enabled(_Terminal(), env={}) is True
    assert teletype.enabled(io.StringIO(), env={}) is False  # piped or redirected
    assert teletype.enabled(_Terminal(), env={"MAGNACODA_TYPING": "off"}) is False
    preferences.ensure_file()
    path = preferences.preferences_path()
    path.write_text(path.read_text(encoding="utf-8").replace("typing = on", "typing = off"), encoding="utf-8")
    assert teletype.enabled(_Terminal(), env={}) is False


def test_short_text_arrives_in_chunks_and_never_takes_longer_than_the_limit(no_waiting):
    stream = _Terminal()
    text = "Saved to /home/someone/.config/magnacoda/favorites.md\n"
    teletype.write(stream, text)
    assert stream.getvalue() == text
    assert len(stream.writes) > 1 and all(
        len(piece) <= teletype.chunk_size(len(text)) for piece in stream.writes
    )
    for length in (1, 100, teletype.MAX_TYPED_CHARS):
        chunks = -(-length // teletype.chunk_size(length))
        assert chunks * teletype.CHUNK_DELAY <= teletype.MAX_SECONDS + 1e-9


def test_long_text_and_non_terminals_get_everything_at_once(no_waiting):
    stream = _Terminal()
    teletype.write(stream, "x" * (teletype.MAX_TYPED_CHARS + 1))
    assert len(stream.writes) == 1 and no_waiting == []
    piped = io.StringIO()
    teletype.write(piped, "short")
    assert piped.getvalue() == "short" and no_waiting == []


def test_a_higher_limit_types_longer_text_in_bigger_chunks_in_the_same_time(no_waiting):
    stream = _Terminal()
    console = Console(file=stream, force_terminal=True, color_system=None, width=200)
    text = "a line of the about screen\n" * 32  # 864 characters, about as long as the about screen
    teletype.say(console, text, max_chars=1500)
    assert stream.getvalue() == text + "\n" and len(stream.writes) > 2
    assert len(no_waiting) * teletype.CHUNK_DELAY <= teletype.MAX_SECONDS + 1e-9
    once = _Terminal()
    teletype.say(Console(file=once, force_terminal=True, color_system=None, width=200), text)
    assert len(once.writes) == 1  # the usual limit: at once


def test_a_listing_types_in_bigger_chunks_and_the_pace_comes_back_after(no_waiting):
    line = "  12. example.com  2026-10-15 09:00  - 3 of 52 checked\n"
    usual = _Terminal()
    teletype.write(usual, line)
    listed = _Terminal()
    with teletype.listing():
        teletype.write(listed, line)
    assert listed.getvalue() == usual.getvalue() == line
    assert max(len(piece) for piece in usual.writes) == teletype.MIN_CHUNK
    assert max(len(piece) for piece in listed.writes) == teletype.LISTING_CHUNK
    assert teletype.chunk_size(len(line)) == teletype.MIN_CHUNK  # back to the usual pace


def test_typed_styled_text_keeps_its_styles(no_waiting):
    stream = _Terminal()
    console = Console(file=stream, force_terminal=True, color_system="standard", width=80)
    teletype.say(console, "[bold]News:[/bold] 2 news items - type news")
    out = stream.getvalue()
    assert "\x1b[1m" in out and out.endswith("\n") and len(stream.writes) > 2
    plain = Console(file=io.StringIO(), width=80)
    teletype.say(plain, "[bold]News:[/bold] plain")
    assert plain.file.getvalue() == "News: plain\n"


def test_page_feed_does_nothing_without_a_terminal():
    out = io.StringIO()
    teletype.page_feed(Console(file=out))
    assert out.getvalue() == ""
