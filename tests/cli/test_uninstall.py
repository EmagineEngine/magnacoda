from pathlib import Path

import pytest
from click.testing import CliRunner

from magnacoda import shortcuts, uninstaller, updater, userdir
from magnacoda.cli import main


@pytest.fixture
def installed(monkeypatch, tmp_path):
    """A VENV install with settings, Chromium beside Firefox, two scans and a shortcut, all in tmp."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "ms-playwright"))
    monkeypatch.setattr(updater, "install_kind", lambda: updater.VENV)
    ran = []
    monkeypatch.setattr(updater, "run", lambda commands, log: ran.append(commands) or True)
    settings = userdir.config_dir()
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "history.md").write_text("x\n")
    for name in ("chromium-1243", "firefox-1543"):
        (tmp_path / "ms-playwright" / name).mkdir(parents=True)
    scans = Path.cwd() / "magnacoda-scans"  # where the tests look for scans
    for name in ("example.com_20261101-101010", "example.com_20261102-111111"):
        (scans / name).mkdir(parents=True)
        (scans / name / "checklist.md").write_text("# x\n")
    shortcuts.places().desktop.parent.mkdir(parents=True, exist_ok=True)
    shortcuts.places().desktop.write_text("x")
    return ran, settings, tmp_path / "ms-playwright" / "chromium-1243", scans


def _uninstall(*args, answers=""):
    return CliRunner().invoke(main, ["uninstall", *args], input=answers)


def test_it_asks_first_and_no_changes_nothing(installed):
    ran, settings, chromium, scans = installed
    result = _uninstall(answers="n\n")
    assert "Uninstall magnacoda?" in result.output and "help uninstall" in result.output
    assert "Nothing was changed." in result.output
    assert not ran and settings.exists() and chromium.exists() and scans.exists()
    assert shortcuts.existing()


def test_enter_keeps_your_files_and_removes_the_program_and_shortcut(installed):
    ran, settings, chromium, scans = installed
    result = _uninstall(answers="y\n\n\n\ny\n")
    assert "Delete your settings and history too?" in result.output
    assert "Delete Chromium too?" in result.output and "2 saved scans" in result.output
    assert "Remove the shortcut." in result.output and "magnacoda is uninstalled." in result.output
    assert ran and ran[0][0][-3:] == ["uninstall", "--yes", "magnacoda"]
    assert settings.exists() and chromium.exists() and scans.exists()
    assert not shortcuts.existing()


def test_yes_to_each_deletes_it(installed):
    ran, settings, chromium, scans = installed
    result = _uninstall(answers="y\ny\ny\ny\ny\n")
    assert "Delete 2 saved scans." in result.output
    assert not settings.exists() and not chromium.exists() and not scans.exists()
    assert (chromium.parent / "firefox-1543").exists()


def test_the_last_question_still_lets_you_back_out(installed):
    ran, settings, chromium, scans = installed
    result = _uninstall(answers="y\ny\ny\ny\n\n")
    assert "This will:" in result.output and "Nothing was changed." in result.output
    assert not ran and settings.exists() and scans.exists() and shortcuts.existing()


def test_in_a_script_yes_keeps_the_data_unless_named(installed):
    ran, settings, chromium, scans = installed
    _uninstall("--yes")
    assert ran and settings.exists() and chromium.exists() and scans.exists()
    _uninstall("--yes", "--scans")
    assert not scans.exists() and settings.exists() and chromium.exists()


def test_a_development_install_keeps_the_program(installed, monkeypatch):
    ran, *_ = installed
    monkeypatch.setattr(updater, "install_kind", lambda: updater.DEV)
    result = _uninstall("--yes")
    assert not ran and "development install" in result.output and not shortcuts.existing()


def test_when_removing_the_program_fails_it_says_how_to_finish(installed, monkeypatch):
    monkeypatch.setattr(updater, "run", lambda commands, log: False)
    result = _uninstall("--yes")
    assert result.exit_code == 1 and "To finish it yourself, run:" in result.output


def test_a_pipx_install_is_removed_with_pipx(installed, monkeypatch):
    ran, *_ = installed
    monkeypatch.setattr(updater, "install_kind", lambda: updater.PIPX)
    monkeypatch.setattr(uninstaller.shutil, "which", lambda name: f"/bin/{name}")
    result = _uninstall(answers="y\n\n\n\ny\n")
    assert "Remove magnacoda: /bin/pipx uninstall magnacoda" in result.output and "uv" not in result.output
    assert ran == [[["/bin/pipx", "uninstall", "magnacoda"]]]


def test_without_pipx_on_the_path_it_says_so_first_and_shows_both_ways(installed, monkeypatch):
    ran, *_ = installed
    monkeypatch.setattr(updater, "install_kind", lambda: updater.PIPX)
    monkeypatch.setattr(uninstaller.shutil, "which", lambda name: None)
    result = _uninstall(answers="y\n\n\n\ny\n")
    summary = result.output.index("This will:")
    assert result.output.index("which it can't run here") > summary
    assert "  pipx uninstall magnacoda" in result.output and "-m pipx uninstall magnacoda" in result.output
    assert not ran and not shortcuts.existing()
