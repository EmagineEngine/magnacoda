"""The shell's left and right margins (magnacoda/margin.py)."""

import io
import os

import pytest

from magnacoda import margin

PAD = " " * margin.WIDTH


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def out(monkeypatch):
    monkeypatch.delenv("COLUMNS", raising=False)
    terminal = _Terminal()
    return margin.Margined(terminal, margin._State(terminal)), terminal


def test_each_line_of_text_starts_in_from_the_edge_and_empty_lines_stay_empty(out):
    stream, terminal = out
    assert stream.write("one\n\ntwo\n") == len("one\n\ntwo\n")
    assert terminal.getvalue() == f"{PAD}one\n\n{PAD}two\n"


def test_text_written_in_pieces_gets_one_margin(out):
    stream, terminal = out
    for piece in ("mag", "nacoda » ", "\n", "next"):
        stream.write(piece)
    assert terminal.getvalue() == f"{PAD}magnacoda » \n{PAD}next"


def test_a_line_drawn_again_from_its_start_keeps_the_margin(out):
    stream, terminal = out
    stream.write("| scanning\r\x1b[2K/ scanning")  # a spinner: back to the start, erase, draw
    stream.write("\n\n\x1b[Hfresh page")  # a page feed ends at the top left
    assert terminal.getvalue() == f"{PAD}| scanning\r\x1b[2K{PAD}/ scanning\n\n\x1b[H{PAD}fresh page"


def test_color_codes_alone_do_not_start_a_line(out):
    stream, terminal = out
    stream.write("\x1b[1m\x1b[0m\n\x1b[1mbold\x1b[0m\n")
    assert terminal.getvalue() == f"\x1b[1m\x1b[0m\n\x1b[1m{PAD}bold\x1b[0m\n"


def test_nothing_is_added_outside_a_terminal(monkeypatch):
    monkeypatch.setattr("sys.stdout", io.StringIO())
    assert margin.install() is False and margin._state is None


def test_the_viewer_gets_the_whole_window(monkeypatch):
    monkeypatch.delenv("COLUMNS", raising=False)
    terminal = _Terminal()
    state = margin._State(terminal)
    monkeypatch.setattr(margin, "_state", state)
    stream = margin.Margined(terminal, state)
    stream.write("before")
    with margin.paused():
        stream.write("\x1b[?1049hfull width\x1b[?1049l")
    stream.write("after\n")
    assert terminal.getvalue() == f"{PAD}before\x1b[?1049hfull width\x1b[?1049l{PAD}after\n"


def test_the_width_everything_wraps_to_leaves_room_for_both_margins(monkeypatch):
    monkeypatch.setenv("COLUMNS", "100")
    state = margin._State(_Terminal())
    state.fit()
    assert os.environ["COLUMNS"] == str(100 - 2 * margin.WIDTH)
    state.unfit()
    assert os.environ["COLUMNS"] == "100"
