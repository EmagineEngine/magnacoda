"""The Mac shortcut's parts that don't need a Mac: its launcher, and the desktop link to the app."""

from magnacoda import shortcuts


def _app(tmp_path):
    app = tmp_path / "Applications" / "magnacoda.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "magnacoda").write_text("made by pyshortcuts")
    return app


def test_the_app_gets_our_launcher_and_the_desktop_a_link_to_it(tmp_path):
    app, desktop = _app(tmp_path), tmp_path / "Desktop" / "magnacoda.app"
    desktop.parent.mkdir()
    desktop.mkdir()  # a second copy of the app, as earlier versions made
    shortcuts._finish_mac(app, desktop, tmp_path / "my tools" / "magnacoda")
    script = (app / "Contents" / "MacOS" / "magnacoda").read_text()
    assert script.count("activate") == 2  # Terminal comes to the front
    assert (
        "do script \"'"
        + str(tmp_path / "my tools" / "magnacoda")
        + "' shell --from-shortcut; exit\" in window 1"
        in script
    )
    assert desktop.is_symlink() and desktop.resolve() == app.resolve()


def test_removing_takes_the_link_and_leaves_what_it_points_to(tmp_path, monkeypatch):
    app, desktop = _app(tmp_path), tmp_path / "magnacoda-link.app"
    desktop.symlink_to(app)
    monkeypatch.setattr(shortcuts, "places", lambda: shortcuts.Places(tmp_path / "gone.app", desktop))
    assert shortcuts.remove() == [desktop]
    assert not desktop.is_symlink() and app.is_dir()


def test_a_link_whose_app_is_gone_is_still_found_and_removed(tmp_path, monkeypatch):
    desktop = tmp_path / "magnacoda.app"
    desktop.symlink_to(tmp_path / "gone.app")
    monkeypatch.setattr(shortcuts, "places", lambda: shortcuts.Places(tmp_path / "gone.app", desktop))
    assert shortcuts.remove() == [desktop] and not desktop.is_symlink()


def test_quotes_in_the_command_are_escaped_for_applescript():
    assert 'do script "say \\"hi\\"; exit"' in shortcuts.mac_launcher('say "hi"')
