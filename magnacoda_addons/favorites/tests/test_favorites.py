import stat
import sys

import pytest

from magnacoda.savedcommand import SavedScan
from magnacoda_addons.favorites import store
from magnacoda_addons.favorites.store import Favorite


def test_render_then_parse_round_trips_with_notes():
    original = [
        Favorite("Home page", "scan https://example.com --level AA", "Checked monthly."),
        Favorite("Blog (dark)", "scan https://example.com/blog --color-scheme dark"),
    ]
    parsed, problems = store.parse(store.render(original))
    assert problems == []
    assert parsed == original


def test_text_outside_the_entries_is_ignored_and_bad_entries_are_reported():
    text = "# Title\nSome intro.\n\n## Good\n\n```\nscan https://a.test\n```\n\n## Empty\n\nno code here\n"
    parsed, problems = store.parse(text)
    assert [f.name for f in parsed] == ["Good"]
    assert len(problems) == 1 and "Empty" in problems[0]


def test_a_command_wrapped_over_several_lines_is_joined():
    parsed, _ = store.parse("## Wrapped\n\n```\nscan https://a.test\n  --level AAA\n```\n")
    assert parsed[0].command == "scan https://a.test --level AAA"


def test_load_of_a_missing_file_is_empty_and_creates_nothing():
    assert store.load() == ([], [])
    assert not store.favorites_path().exists()


def test_ensure_file_creates_the_header_only_once():
    store.ensure_file()
    path = store.favorites_path()
    assert path.read_text().startswith("# magnacoda favorites")
    store.save_all([Favorite("Keep", "scan https://a.test")])
    store.ensure_file()
    assert "## Keep" in path.read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_files_are_owner_only_and_no_temporary_file_is_left():
    store.save_all([Favorite("A", "scan https://a.test")])
    path = store.favorites_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["favorites.md"]


def test_lookups_by_name_ignore_case_and_by_command_ignore_how_it_was_typed():
    saved = [Favorite("Home", "scan https://a.test --level AA")]
    assert store.find_by_name(saved, "HOME") == 0
    assert store.find_by_name(saved, "Other") is None
    assert store.find_by_command(saved, "magnacoda https://a.test") == 0
    assert store.find_by_command(saved, "scan https://b.test") is None


def test_name_helpers():
    assert store.sanitize_name("  ## My `site`\n  ") == "My 'site'"
    assert store.sanitize_name("###") == "Untitled"
    assert len(store.sanitize_name("x" * 200)) == 80
    scan = SavedScan(url="https://example.com/a", color_scheme="dark", ai="explain")
    assert store.default_name(scan) == "example.com (dark, AI explain)"
