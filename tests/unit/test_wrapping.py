import io

from magnacoda.wrapping import wrap_for_stream, wrap_text


def test_wraps_at_spaces_and_never_inside_a_word():
    text = "alpha beta gamma delta epsilon zeta eta theta"
    wrapped = wrap_text(text, 20)
    assert all(len(line) <= 20 for line in wrapped.splitlines())
    assert " ".join(wrapped.split()) == text


def test_long_unbreakable_word_is_kept_whole():
    url = "https://example.com/" + "a" * 60
    assert url in wrap_text(f"see {url} now", 30).split()


def test_hyphenated_words_are_not_split():
    wrapped = wrap_text("run the magnacoda tool now please", 14)
    assert "magnacoda" in wrapped.split()


def test_numbered_items_get_a_hanging_indent():
    wrapped = wrap_text("  1. Run setup again and answer y to save it for you.", 24)
    lines = wrapped.splitlines()
    assert lines[0].startswith("  1. Run")
    assert all(line.startswith("     ") for line in lines[1:])


def test_blank_lines_are_preserved():
    assert wrap_text("one\n\ntwo", 40) == "one\n\ntwo"


def test_indented_command_lines_are_not_wrapped():
    line = "       export ANTHROPIC_API_KEY=sk-ant-something-quite-long"
    assert wrap_text(line, 20) == line
    assert wrap_text("  magnacoda https://example.com --ai explain --level AA", 20).count("\n") == 0


def test_unindented_text_starting_with_the_program_name_still_wraps():
    assert "\n" in wrap_text("magnacoda wizard - Ctrl+C to cancel anytime, then more words", 25)


def test_non_terminal_streams_are_left_unwrapped():
    text = "word " * 60
    assert wrap_for_stream(text, io.StringIO()) == text
