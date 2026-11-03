from magnacoda import uninstaller, updater
from magnacoda.report import paths
from magnacoda.updater import DEV, PIPX, SHOW, UV, VENV


def test_each_install_kind_is_removed_its_own_way():
    assert uninstaller.plan([], UV, uv="uv").commands == [["uv", "tool", "uninstall", "magnacoda"]]
    assert uninstaller.plan([], PIPX, pipx="pipx").commands == [["pipx", "uninstall", "magnacoda"]]
    venv = uninstaller.plan(["public-addon"], VENV)
    assert venv.kind == VENV and venv.commands[0][-4:] == ["uninstall", "--yes", "magnacoda", "public-addon"]
    assert "stays" in venv.note
    assert uninstaller.plan([], DEV).commands == []


def test_without_the_tool_on_the_path_or_a_known_install_the_command_is_only_shown():
    assert uninstaller.plan([], UV, uv="").kind == SHOW
    assert uninstaller.plan([], PIPX, pipx="").kind == SHOW
    assert uninstaller.plan([], SHOW).kind == SHOW


def _browsers(tmp_path, *names):
    folder = tmp_path / "ms-playwright"
    for name in names:
        (folder / name).mkdir(parents=True)
    return folder


def test_only_chromium_is_deleted_and_other_browsers_keep_the_folder(tmp_path):
    folder = _browsers(
        tmp_path, "chromium-1243", "chromium_headless_shell-1243", "ffmpeg-1011", "firefox-1543"
    )
    assert [part.name for part in uninstaller.chromium_parts(folder)] == [
        "chromium-1243",
        "chromium_headless_shell-1243",
        "ffmpeg-1011",
    ]
    assert uninstaller.delete_chromium(folder)
    assert [entry.name for entry in folder.iterdir()] == ["firefox-1543"]


def test_the_browser_folder_goes_when_only_its_bookkeeping_is_left(tmp_path):
    folder = _browsers(tmp_path, "chromium-1243", ".links")
    assert uninstaller.delete_chromium(folder)
    assert not folder.exists()


def _scans(folder, *names):
    for name in names:
        (folder / name).mkdir(parents=True)
        (folder / name / "checklist.md").write_text("# x\n")
    return folder


def test_scans_are_counted_and_deleted_with_the_folder_magnacoda_made(tmp_path):
    folder = _scans(
        tmp_path / "magnacoda-scans", "example.com_20261101-101010", "example.com_20261102-111111"
    )
    paths.make_self_ignoring(folder)
    found = uninstaller.saved_scans(folder)
    assert found.count == 2
    assert uninstaller.delete_scans(found)
    assert not folder.exists()


def test_other_files_in_the_scans_folder_stay(tmp_path):
    folder = _scans(tmp_path / "work", "example.com_20261101-101010")
    (folder / "notes.md").write_text("mine\n")
    (folder / ".gitignore").write_text("mine\n")
    assert uninstaller.delete_scans(uninstaller.saved_scans(folder))
    assert sorted(entry.name for entry in folder.iterdir()) == [".gitignore", "notes.md"]


def test_the_windows_script_speaks_of_uninstalling():
    script = updater.windows_script(
        [["uv", "tool", "uninstall", "magnacoda"]], "C:\\x", "r", words=uninstaller.UNINSTALL_WORDS
    )
    assert "'magnacoda uninstall'" in script and "Press Enter to uninstall now" in script
    assert "update now" not in script and "The update" not in script
