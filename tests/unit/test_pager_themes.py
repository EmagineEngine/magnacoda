"""Color themes from pager-colors.ini (magnacoda/pager/themes.py) and how the pager offers them."""

import io

import pytest

from magnacoda.pager import colors, options, screen, themes

SLATE = "[slate]\ndescription = pale yellow on slate blue\ntext = #ffe8a6\nbackground = #293955\n"


def _load(tmp_path, text):
    path = tmp_path / themes.FILE_NAME
    path.write_text(text, encoding="utf-8")
    return themes.load(path)


def test_a_theme_is_read_with_its_colors_and_a_256_color_match(tmp_path):
    loaded = _load(tmp_path, "# my themes\n" + SLATE + "accent = #ffffff    ; for headings\n")
    assert loaded.problems == []
    (slate,) = loaded.themes
    assert (slate.name, slate.description, slate.fg, slate.bg, slate.accent) == (
        "slate",
        "pale yellow on slate blue",
        "#ffe8a6",
        "#293955",
        "#ffffff",
    )
    for color, number in ((slate.fg, slate.fg256), (slate.accent, slate.accent256)):
        assert colors.contrast(colors.xterm256(number), colors.xterm256(slate.bg256)) >= 7
        assert number != 0 and color


def test_no_file_means_no_themes_and_nothing_to_report(tmp_path):
    assert themes.load(tmp_path / "missing.ini") == themes.Loaded()
    assert themes.load(None) == themes.Loaded()


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("[dim]\ntext = #555555\nbackground = #000000\n", "dim: text on background is 2.8:1, needs 7:1"),
        (SLATE + "accent = #68217a\n", "slate: accent on background is 1.2:1, needs 7:1"),
        ("[x]\ntext = white\nbackground = #000000\n", "x: text must be a color like #1a2b3c"),
        ("[x]\ntext = #ffffff\n", "x: background must be a color like #1a2b3c"),
        ("[9lives]\ntext = #ffffff\nbackground = #000000\n", "line 1: a name is a letter"),
        ("[x]\ntext = #ffffff\nbackground = #000000\ncolour = red\n", "line 4: no setting named colour"),
        ("text = #ffffff\n", "line 1: not understood"),
        ("[x]\njust words\n", "line 2: not understood"),
    ],
)
def test_a_theme_that_cant_be_used_is_left_out_with_a_reason_and_the_rest_load(tmp_path, text, problem):
    loaded = _load(tmp_path, text + "\n" + SLATE)
    assert loaded.problems and loaded.problems[0].startswith(problem)
    assert loaded.themes[-1].name == "slate"


def test_names_used_twice_or_already_built_in_get_a_number(tmp_path):
    text = SLATE + SLATE + SLATE.replace("slate", "amber") + SLATE.replace("[slate]", "[Slate-Two]")
    loaded = _load(tmp_path, text)
    assert [theme.name for theme in loaded.themes] == ["slate_1", "slate_2", "amber_2", "slate_two"]


def test_a_long_or_odd_description_is_tidied_and_a_missing_one_named(tmp_path):
    loaded = _load(
        tmp_path,
        SLATE.replace("pale yellow on slate blue", "x " * 50)
        + SLATE.replace("[slate]\ndescription = pale yellow on slate blue\n", "[plain]\n"),
    )
    assert len(loaded.themes[0].description) <= 60
    assert loaded.themes[1].description == "your own theme"


def test_a_file_too_large_or_unreadable_is_reported(tmp_path):
    big = tmp_path / themes.FILE_NAME
    big.write_text("#" * 70_000)
    assert themes.load(big).problems == ["pager-colors.ini is larger than 64 KB"]
    big.write_bytes(b"\xff\xfe\x00bad")
    assert themes.load(big).problems == ["pager-colors.ini can't be read"]


def test_the_color_setting_keeps_a_theme_name_from_the_file(tmp_path):
    settings = tmp_path / "app.ini"
    settings.write_text("[pager]\ncolors = Slate 2\n")
    found = options.resolve(settings, title_bar="x")
    assert found.colors == "slate_2"
    assert found.colors_file == tmp_path / themes.FILE_NAME


def test_the_list_shows_numbered_names_with_spaces_and_the_problems_below():
    state = screen.PagerState([("One", ["text"])], 20)
    state.colors = [("default", "own"), ("slate_2", "mine")]
    state.color_notes = ["dim: text on background is 2.8:1, needs 7:1"]
    state.handle("c")
    rows = state.render(70)
    assert any("slate 2" in row and "mine" in row for row in rows)
    assert "Left out of pager-colors.ini:" in rows
    assert any("dim: text on background" in row for row in rows)


def test_show_offers_the_files_themes_after_the_built_in_ones(tmp_path, monkeypatch):
    (tmp_path / themes.FILE_NAME).write_text(SLATE + "[dim]\ntext = #555555\nbackground = #000000\n")
    seen = {}

    def fake(sections, **kwargs):
        seen.update(kwargs)

    from magnacoda import pager

    monkeypatch.setattr(pager, "page_sections", fake)
    monkeypatch.setattr(pager, "pager_available", lambda off_switch=None: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    found = options.resolve(tmp_path / "app.ini")
    pager.show([("One", "text")], found, out=io.StringIO())
    assert [choice[0] for choice in seen["colors"]] == [*colors.NAMES, "slate"]
    assert seen["color_notes"] == ["dim: text on background is 2.8:1, needs 7:1"]
