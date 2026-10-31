"""The time on a scan's spinner (cli._ScanTime)."""

from magnacoda.cli import _ScanTime


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_estimate_stays_as_made_and_the_time_so_far_grows_beside_it():
    clock = _Clock()
    time = _ScanTime(150.0, clock)
    assert time.text() == "about 2 min 30 s estimated"
    clock.now = 47
    assert time.text() == "about 2 min 30 s estimated, 45 s so far"  # in steps of 5 seconds
    clock.now = 192
    assert time.text() == "about 2 min 30 s estimated, 3 min 10 s so far"  # past it, still counting


def test_without_an_estimate_only_the_time_so_far():
    clock = _Clock()
    time = _ScanTime(None, clock)
    assert time.text() == ""  # too early
    clock.now = 60
    assert time.text() == "1 min so far"
