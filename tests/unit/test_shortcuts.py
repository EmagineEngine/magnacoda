import hashlib
import sys

import pytest
from click.testing import CliRunner

from magnacoda import cli, shortcuts
from magnacoda.cli import main

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="the shortcut files checked are Linux's")


@pytest.fixture
def gio(monkeypatch, tmp_path):
    launcher = tmp_path / "my tools" / "magnacoda"
    monkeypatch.setattr(shortcuts, "_launcher", lambda: launcher)
    calls = []
    monkeypatch.setattr(shortcuts.subprocess, "run", lambda args, **kw: calls.append(args))
    return calls


def test_the_menu_entry_opens_the_shell_in_a_terminal_even_from_a_path_with_spaces(gio, tmp_path):
    assert shortcuts.add() == [shortcuts.places().menu]
    entry = shortcuts.places().menu.read_text().splitlines()
    assert f'Exec="{tmp_path}/my tools/magnacoda" shell --from-shortcut' in entry
    assert "Terminal=true" in entry and "Categories=Development;" in entry
    assert shortcuts.existing() == [shortcuts.places().menu] and gio == []
    icon = next(line for line in entry if line.startswith("Icon="))
    assert icon.endswith("magnacoda.svg") and shortcuts._icon().exists()


def test_the_desktop_copy_is_trusted_and_remove_takes_both_away(gio):
    shortcuts.add(desktop=True)
    desktop = shortcuts.places().desktop
    checksum = hashlib.sha256(desktop.read_bytes()).hexdigest()
    assert [call[-2:] for call in gio] == [
        ["metadata::trusted", "true"],
        ["metadata::xfce-exe-checksum", checksum],
    ]
    assert len(shortcuts.remove()) == 2 and shortcuts.existing() == []


def test_the_command_adds_removes_and_says_how_to_take_it_away(gio):
    added = CliRunner().invoke(main, ["shortcut", "Both"]).output
    assert "your app menu and your desktop. To take them away, type `magnacoda shortcut remove`" in added
    assert CliRunner().invoke(main, ["shortcut", "remove"]).output == "Removed the shortcuts.\n"
    assert "your desktop. To take it away" in CliRunner().invoke(main, ["shortcut", "desktop"]).output
    assert shortcuts.existing() == [shortcuts.places().desktop]
    assert CliRunner().invoke(main, ["shortcut", "remove"]).output == "Removed the shortcut.\n"
    assert "no shortcut" in CliRunner().invoke(main, ["shortcut", "remove"]).output


@pytest.fixture
def setup(gio, monkeypatch):
    monkeypatch.setattr(cli, "_chromium_already_installed", lambda: True)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    return lambda answer: CliRunner().invoke(main, ["setup"], input=answer).output


def test_setup_offers_shortcuts_and_then_to_remove_them(setup):
    assert "Add a magnacoda shortcut to (menu, desktop, both, skip) [skip]:" in setup("both\n")
    assert len(shortcuts.existing()) == 2
    assert "in your app menu and on your desktop.\nRemove them? [y/N]" in setup("\n")
    assert len(shortcuts.existing()) == 2
    assert "Removed the shortcuts." in setup("y\n") and shortcuts.existing() == []


def test_with_one_shortcut_setup_offers_the_other_or_removing_it(setup):
    shortcuts.add(menu=False, desktop=True)
    added = setup("menu\n")
    assert (
        "on your desktop.\nAdd one to your app menu too, or remove it? (menu, remove, keep) [keep]:" in added
    )
    assert len(shortcuts.existing()) == 2
    shortcuts.remove()
    shortcuts.add()
    assert "Removed the shortcut." in setup("remove\n") and shortcuts.existing() == []


@pytest.mark.parametrize("terminal", [None, r"C:\Users\me\AppData\Local\Microsoft\WindowsApps\wt.exe"])
def test_on_windows_the_program_is_left_unquoted_and_the_start_menu_s_shortcut_gets_the_key(
    monkeypatch, tmp_path, terminal
):
    import types

    links = {}

    class Link:
        def __init__(self, path):
            self.path, self.Hotkey, self.TargetPath, self.Arguments = path, "", None, None

        def save(self):
            links[self.path] = self

    shell = types.SimpleNamespace(CreateShortCut=Link)
    client = types.SimpleNamespace(Dispatch=lambda name: shell)
    monkeypatch.setitem(sys.modules, "win32com", types.SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    made = {}
    monkeypatch.setattr(
        shortcuts._pyshortcuts(), "make_shortcut", lambda script, **kw: made.update(kw, script=script)
    )
    monkeypatch.setattr(shortcuts, "_launcher", lambda: tmp_path / "Phillip Honstein" / "magnacoda.exe")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: terminal if name == "wt" else None)
    menu, desktop = shortcuts.add(desktop=True)
    assert (
        made["executable"] == str(tmp_path / "Phillip Honstein" / "magnacoda.exe")
        and made["script"] == "shell --from-shortcut"
    )
    assert made["icon"].endswith("magnacoda.ico")
    assert {path: (link.WindowStyle, link.Hotkey) for path, link in links.items()} == {
        str(menu): (1, "CTRL+ALT+M"),
        str(desktop): (1, ""),
    }
    launcher = tmp_path / "Phillip Honstein" / "magnacoda.exe"
    in_terminal = (
        (terminal, f'--title magnacoda "{launcher}" shell --from-shortcut') if terminal else (None, None)
    )
    assert all((link.TargetPath, link.Arguments) == in_terminal for link in links.values())
