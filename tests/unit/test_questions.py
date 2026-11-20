"""Questions (questions.py): a blank line above each question, or above its explanation, never two
in a row, and a blank line after the answer; and the same rules at every question."""

import click
import pytest
from click.testing import CliRunner

from magnacoda import questions


def _run(steps, answers):
    @click.command()
    def flow():
        steps()

    return CliRunner().invoke(flow, [], input=answers).output


def test_text_then_a_question_then_text_are_set_apart():
    def steps():
        click.echo("Some text.")
        questions.printed("Some text.")
        questions.ask("Name", default="x")
        click.echo("After.")

    assert _run(steps, "Ann\n") == "Some text.\n\nName [x] » Ann\n\nAfter.\n"


def test_an_explanation_sits_right_above_its_question_with_the_blank_line_above_it():
    def steps():
        click.echo("Before.")
        questions.printed("Before.")
        questions.ask_yes_no("Go on?", intro="This explains the question.")

    assert _run(steps, "y\n") == "Before.\n\nThis explains the question.\nGo on? [y/N] » y\n\n"


def test_two_questions_in_a_row_have_one_blank_line_between_them():
    def steps():
        questions.ask_yes_no("First?")
        questions.ask_yes_no("Second?")

    output = _run(steps, "n\nn\n")
    assert "First? [y/N] » n\n\nSecond? [y/N] » n\n" in output and "\n\n\n" not in output


def test_after_a_blank_line_a_question_adds_no_second_one():
    def steps():
        click.echo("Text, then a blank line.\n")
        questions.printed("Text, then a blank line.\n")
        questions.ask_yes_no("Ready?", default=True)

    assert _run(steps, "\n") == "Text, then a blank line.\n\nReady? [Y/n] » \n\n"


# The same rules at every question: Ctrl+C or q cancels, Enter takes what the brackets show.


def _answer(function, typed: str):
    @click.command()
    def ask() -> None:
        click.echo(f"ANSWER={function()!r}")

    return CliRunner().invoke(ask, input=typed)


@pytest.mark.parametrize("typed", ["q\n", "Q\n", " q \n", "clear\n", "Clear\n", "cls\n"])
def test_q_or_clear_cancels_any_question(typed):
    for function in (
        lambda: questions.ask("Name"),
        lambda: questions.ask("Level", type=click.Choice(["A", "AA"])),
        lambda: questions.ask_yes_no("Continue?", default=True),
    ):
        result = _answer(function, typed)
        assert result.exit_code == 1 and "ANSWER" not in result.output and "Aborted!" in result.output


def test_ctrl_c_cancels_too():
    result = _answer(lambda: questions.ask_yes_no("Continue?"), "")  # end of input, like Ctrl+D/Ctrl+C
    assert result.exit_code == 1 and "ANSWER" not in result.output


@pytest.mark.parametrize(
    ("typed", "default", "expected"),
    [
        ("\n", True, True),
        ("\n", False, False),
        ("y\n", False, True),
        ("Yes\n", False, True),
        ("n\n", True, False),
    ],
)
def test_yes_no_shows_its_default_in_brackets_and_enter_takes_the_capital_letter(typed, default, expected):
    result = _answer(lambda: questions.ask_yes_no("Continue?", default=default), typed)
    assert ("Continue? [Y/n] » " if default else "Continue? [y/N] » ") in result.output
    assert f"ANSWER={expected!r}" in result.output


def test_anything_else_at_a_yes_no_question_asks_again():
    result = _answer(lambda: questions.ask_yes_no("Continue?"), "maybe\ny\n")
    assert "Error: type y or n, or press Enter." in result.output and "ANSWER=True" in result.output


def test_other_answers_and_converters_work_as_before():
    assert (
        "ANSWER='AA'"
        in _answer(lambda: questions.ask("Level", type=click.Choice(["A", "AA"])), "AA\n").output
    )
    assert "ANSWER=5" in _answer(lambda: questions.ask("Count", type=int), "5\n").output
    assert "ANSWER='kept'" in _answer(lambda: questions.ask("Name", default="kept"), "\n").output
    assert (
        "ANSWER='quiet'" in _answer(lambda: questions.ask("Name"), "quiet\n").output
    )  # only q alone cancels


def test_in_screen_reader_mode_a_question_ends_with_a_colon(monkeypatch):
    from magnacoda import screenreader

    monkeypatch.setattr(screenreader, "mode_on", lambda: True)
    output = _run(lambda: (questions.ask("Name", default="x"), questions.ask_yes_no("Go on?")), "Ann\ny\n")
    assert "Name [x]: Ann" in output and "Go on? [y/N]: y" in output and questions.CHEVRON not in output


class _Terminal:
    def isatty(self):
        return True


@pytest.mark.parametrize("columns", ["24", "41"])
def test_a_long_question_wraps_at_whole_words_with_its_brackets_beside_the_chevron(monkeypatch, columns):
    monkeypatch.setenv("COLUMNS", columns)
    text = questions._shown(
        "Add a magnacoda shortcut to",
        {"type": click.Choice(["menu", "desktop", "both", "skip"]), "default": "skip"},
    )
    lines = questions._wrapped(text, _Terminal()).splitlines()
    assert len(lines) > 1 and all(len(line) + len(" » ") <= int(columns) for line in lines[-1:])
    assert all(len(line) < int(columns) for line in lines)
    assert " ".join(lines) == "Add a magnacoda shortcut to (menu, desktop, both, skip) [skip]"
    assert lines[-1].endswith("skip) [skip]")


def test_a_question_is_left_whole_when_piped():
    assert questions._wrapped("Use your Claude plan for the AI tiers? [Y/n]", None) == (
        "Use your Claude plan for the AI tiers? [Y/n]"
    )
