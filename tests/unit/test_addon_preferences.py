"""Add-on sections of preferences.ini: an add-on declares its section, magnacoda checks it, writes it and
reads it back, and never damages the file doing so."""

import pytest

from magnacoda import preferences
from magnacoda.preferences import AddonSection, Setting

SAMPLE = AddonSection(
    "sample",
    (
        Setting("count", 5, "How many to keep (1 to 9).", low=1, high=9),
        Setting("loud", False, "Say more (on or off)."),
        Setting("mode", "fast", "How to go: fast or slow.", choices=("fast", "slow")),
    ),
)


@pytest.fixture(autouse=True)
def _forget_declared(monkeypatch):
    monkeypatch.setattr(preferences, "_declared", {})


def _write(text: str) -> None:
    path = preferences.preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _text() -> str:
    return preferences.preferences_path().read_text()


def test_the_section_is_added_once_at_the_end_and_the_rest_is_kept():
    _write("# mine\n[history]\nmax = 7")  # no newline at the end
    preferences.add_section(SAMPLE)
    preferences.add_section(SAMPLE)
    text = _text()
    added = "\n[sample]\n# How many to keep (1 to 9).\ncount = 5\n"
    assert text.startswith("# mine\n[history]\nmax = 7\n" + added)
    assert text.count("[sample]") == 1 and "loud = off" in text and "mode = fast" in text
    assert preferences.load().history_max == 7


def test_a_new_file_gets_magnacodas_sections_and_the_add_ons():
    assert preferences.addon_value(SAMPLE, "count") == 5
    assert "[history]" in _text() and "[sample]" in _text()


def test_long_comments_are_wrapped_as_comment_lines():
    words = "word " * 60
    preferences.add_section(AddonSection("wordy", (Setting("on", True, words),)))
    lines = _text().split("[wordy]\n", 1)[1].splitlines()
    assert len(lines) > 2 and all(line.startswith("# ") and len(line) <= 100 for line in lines[:-1])
    assert lines[-1] == "on = on"


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("count", "7  # mine", 7),
        ("count", "0", 1),
        ("count", "50", 9),
        ("count", "lots", 5),
        ("count", "", 5),
        ("loud", "yes", True),
        ("loud", "ON", True),
        ("loud", "maybe", False),
        ("mode", "Slow", "slow"),
        ("mode", "sideways", "fast"),
        ("mode", "100%", "fast"),
    ],
)
def test_values_are_read_clamped_or_defaulted(key, value, expected):
    _write(f"[sample]\n{key} = {value}\n")
    assert preferences.addon_value(SAMPLE, key) == expected


def test_a_setting_missing_from_the_file_gives_its_default_and_is_not_added():
    _write("[sample]\ncount = 3\n")
    assert preferences.addon_value(SAMPLE, "loud") is False
    assert _text() == "[sample]\ncount = 3\n"


@pytest.mark.parametrize(
    "broken",
    [
        "[history]\nmax = 1\n[history]\nmax = 2\n",  # a section twice
        "max = 1\n",  # a value before any section
        "[history\nmax = 1\n",  # an unfinished heading
    ],
)
def test_a_file_that_cant_be_read_cleanly_is_never_touched(broken):
    _write(broken)
    preferences.add_section(SAMPLE)
    assert preferences.addon_value(SAMPLE, "count") == 5
    assert _text() == broken


def test_nothing_is_written_when_the_result_would_change_other_settings(monkeypatch):
    _write("[history]\nmax = 7\n")
    monkeypatch.setattr(preferences, "_section_text", lambda section: "\n[history]\nmax = 1\n")
    preferences.add_section(SAMPLE)
    assert _text() == "[history]\nmax = 7\n"


def test_a_value_continued_onto_the_next_line_is_kept_as_it_was():
    _write("[notes]\ntext = one\n  two")
    preferences.add_section(SAMPLE)
    assert "[sample]" in _text()
    assert preferences._parse(_text()).get("notes", "text") == "one\ntwo"


def setting(**changes):
    values = {"key": "count", "default": 5, "comment": "Fine.", "low": 1, "high": 9} | changes
    return Setting(**values)


@pytest.mark.parametrize(
    ("name", "settings", "complaint"),
    [
        ("history", (setting(),), "magnacoda's own"),
        ("ai", (setting(),), "magnacoda's own"),
        ("Sample", (setting(),), "can't name a section"),
        ("x", (setting(),), "can't name a section"),
        ("a]\n[history", (setting(),), "can't name a section"),
        ("sample", (), "1 to 20"),
        ("sample", [setting()], "1 to 20"),
        ("sample", tuple(setting(key=f"k{n}") for n in range(21)), "1 to 20"),
        ("sample", (setting(), setting()), "twice"),
        ("sample", ("count = 5",), "not a Setting"),
        ("sample", (setting(key="count\nmax"),), "can't name a setting"),
        ("sample", (setting(key="max = 1"),), "can't name a setting"),
        ("sample", (setting(comment=""),), "1 to 400"),
        ("sample", (setting(comment="x" * 401),), "1 to 400"),
        ("sample", (setting(comment="One.\n[history]\nmax = 0"),), "one paragraph"),
        ("sample", (setting(comment="Tab\there"),), "one paragraph"),
        ("sample", (setting(default=10),), "low and high"),
        ("sample", (setting(low=None),), "low and high"),
        ("sample", (setting(low=1.5),), "low and high"),
        ("sample", (setting(default=True),), "no range"),
        ("sample", (setting(default="fast"),), "no range"),
        ("sample", (setting(default="fast", low=None, high=None),), "one word"),
        ("sample", (setting(default="fast", low=None, high=None, choices=("fast", "a b")),), "one word"),
        ("sample", (setting(default="x\ny", low=None, high=None, choices=("fast",)),), "one of the choices"),
        ("sample", (setting(default=1.5, low=None, high=None),), "the default must be"),
        ("sample", (setting(default=None, low=None, high=None),), "the default must be"),
    ],
)
def test_a_section_that_could_harm_the_file_is_refused_when_declared(name, settings, complaint):
    with pytest.raises(ValueError, match=complaint):
        AddonSection(name, settings)


def test_two_add_ons_cant_use_the_same_section_name():
    preferences.add_section(SAMPLE)
    preferences.add_section(AddonSection("sample", SAMPLE.settings))  # the same declaration: fine
    other = AddonSection("sample", (Setting("size", 3, "Size.", low=1, high=5),))
    with pytest.raises(ValueError, match="already uses"):
        preferences.add_section(other)


def test_asking_for_a_setting_that_was_not_declared_is_an_error():
    with pytest.raises(KeyError):
        preferences.addon_value(SAMPLE, "colour")


def test_setting_the_ai_engine_keeps_other_settings_and_never_touches_an_unreadable_file():
    _write("[history]\nmax = 7\n[review]\nwindow = new\n")
    preferences.set_ai_engine("api")
    assert preferences.load().ai_engine == "api" and preferences.load().history_max == 7
    assert _text().count("[review]") == 1  # only [ai] was added
    preferences.set_ai_engine("claude-code")
    assert preferences.load().ai_engine == "claude-code"
    broken = "[ai]\nengine = ask\n[ai]\nengine = api\n"
    _write(broken)
    with pytest.raises(OSError, match="left as it is"):
        preferences.set_ai_engine("api")
    assert _text() == broken


def test_setting_a_value_adds_a_missing_line_or_section_and_keeps_the_rest():
    preferences.ensure_file()
    path = preferences.preferences_path()
    path.write_text("[display]\ntips = off\n", encoding="utf-8")
    preferences.set_value("display", "typing", "off")
    preferences.set_value("pager", "paging", "off")
    current = preferences.load()
    assert not (current.typing or current.paging or current.tips) and current.spinner
