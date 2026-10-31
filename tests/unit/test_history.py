import stat
import sys
from datetime import datetime

import pytest

from magnacoda import history, preferences


def _limit(history_max: int) -> None:
    path = preferences.preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"[history]\nmax = {history_max}\n")


def test_newest_first_with_a_timestamp():
    history.record("scan https://a.test", now=datetime(2026, 1, 2, 3, 4))
    history.record("scan https://b.test", now=datetime(2026, 1, 2, 3, 5))
    entries = history.read()
    assert [e.command for e in entries] == ["scan https://b.test", "scan https://a.test"]
    assert entries[1].when == "2026-01-02 03:04"
    assert [e.command for e in history.recent(1)] == ["scan https://b.test"]


def test_the_oldest_entries_are_dropped_beyond_the_cap():
    _limit(3)
    for n in range(5):
        history.record(f"scan https://{n}.test")
    assert [e.command for e in history.read()] == [
        "scan https://4.test",
        "scan https://3.test",
        "scan https://2.test",
    ]


def test_a_cap_of_zero_turns_history_off_and_creates_no_file():
    _limit(0)
    history.record("scan https://a.test")
    history.ensure_file()
    assert not history.history_path().exists()


def test_ensure_file_creates_a_header_only_file_when_history_is_on():
    history.ensure_file()
    assert history.history_path().read_text().startswith("# magnacoda history")
    assert history.read() == []


def test_commands_containing_quotes_and_ampersands_survive():
    command = "scan 'https://a.test/?x=1&y=2' --level AA"
    history.record(command)
    assert history.read()[0].command == command


def test_hand_written_lines_that_do_not_match_are_ignored():
    history.ensure_file()
    history.history_path().write_text(
        history.HEADER + "random text\n- 2026-01-01 10:00 `scan https://a.test`\n"
    )
    assert [e.command for e in history.read()] == ["scan https://a.test"]


def test_an_unwritable_folder_never_raises(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(history, "write_private", refuse)
    history.record("scan https://a.test")  # must not raise


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_the_file_is_owner_only():
    history.record("scan https://a.test")
    assert stat.S_IMODE(history.history_path().stat().st_mode) == 0o600
