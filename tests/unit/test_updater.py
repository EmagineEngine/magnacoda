import subprocess
import sys

import pytest

from magnacoda import updater
from magnacoda.updater import DEV, PIPX, SHOW, UV, VENV


@pytest.mark.parametrize(
    "prefix,base,editable,kind",
    [
        ("/home/a/.local/share/pipx/venvs/magnacoda", "/usr", False, PIPX),
        ("/Users/a/.local/pipx/venvs/magnacoda", "/usr/local", False, PIPX),
        (r"C:\Users\a\pipx\venvs\magnacoda", r"C:\Python312", False, PIPX),
        ("/home/a/.local/share/uv/tools/magnacoda", "/usr", False, UV),
        ("/home/a/project/.venv", "/usr", False, VENV),
        ("/usr", "/usr", False, SHOW),  # system Python
        ("/home/a/project/.venv", "/usr", True, DEV),  # editable always wins
    ],
)
def test_how_it_was_installed(prefix, base, editable, kind):
    assert updater.install_kind(prefix=prefix, base_prefix=base, editable=editable) == kind


def test_a_uv_tool_in_a_folder_of_its_own_is_known_by_its_receipt(tmp_path):
    (tmp_path / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    assert updater.install_kind(str(tmp_path), "/usr", editable=False) == UV


def test_this_checkout_is_a_development_install():
    assert updater.install_kind() == DEV


def test_a_development_install_is_never_updated():
    plan = updater.plan(["magnacoda"], DEV)
    assert plan.commands == [] and "git pull" in plan.note


def test_pipx_upgrades_magnacoda_then_addons_inside_its_environment():
    plan = updater.plan(["magnacoda", "public-addon"], PIPX, pipx="/usr/bin/pipx")
    assert plan.kind == PIPX
    assert plan.commands == [
        ["/usr/bin/pipx", "upgrade", "magnacoda"],
        ["/usr/bin/pipx", "runpip", "magnacoda", "install", "--upgrade", "public-addon"],
    ]


def test_without_pipx_on_the_path_the_command_is_only_shown():
    plan = updater.plan(["magnacoda"], PIPX, pipx="")
    assert plan.kind == SHOW and plan.commands == [["pipx", "upgrade", "magnacoda"]]


def test_a_virtual_environment_uses_its_own_pip():
    plan = updater.plan(["magnacoda", "public-addon"], VENV)
    assert plan.commands == [
        [sys.executable, "-m", "pip", "install", "--upgrade", "magnacoda", "public-addon"]
    ]


def test_uv_upgrades_the_whole_tool_which_brings_its_add_ons_along():
    plan = updater.plan(["magnacoda", "public-addon"], UV, uv="/home/a/.local/bin/uv")
    assert plan.kind == UV
    assert plan.commands == [["/home/a/.local/bin/uv", "tool", "upgrade", "magnacoda"]]


def test_without_uv_on_the_path_the_command_is_only_shown():
    plan = updater.plan(["public-addon"], UV, uv="")
    assert plan.kind == SHOW and plan.commands == [["uv", "tool", "upgrade", "magnacoda"]]


def test_unknown_installs_are_only_shown_and_nothing_uses_sudo():
    other = updater.plan(["magnacoda"], SHOW)
    assert other.kind == SHOW and other.note
    for kind in (DEV, PIPX, UV, VENV, SHOW):
        for command in updater.plan(["magnacoda", "x"], kind, pipx="pipx", uv="uv").commands:
            assert "sudo" not in command


def test_running_stops_at_the_first_failure(monkeypatch, tmp_path):
    ran = []

    def fake_run(command, check, stdout, stderr):
        ran.append(command)
        stdout.write(f"output of {command[0]}\n")
        return subprocess.CompletedProcess(command, 1 if command == ["bad"] else 0)

    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    log = tmp_path / "update.log"
    assert updater.run([["good"], ["bad"], ["never"]], log) is False and ran == [["good"], ["bad"]]
    assert updater.tail(log) == ["$ good", "output of good", "$ bad", "output of bad"]
    assert updater.run([["good"]], log) is True


def test_real_output_goes_to_the_log_not_the_screen(tmp_path, capfd):
    log = tmp_path / "update.log"
    assert updater.run([[sys.executable, "-c", "print('pip says a lot')"]], log) is True
    assert "pip says a lot" not in capfd.readouterr().out
    assert updater.tail(log)[-1] == "pip says a lot"


def test_only_the_last_lines_are_shown(tmp_path):
    log = tmp_path / "update.log"
    log.write_text("".join(f"line {n}\n" for n in range(40)), encoding="utf-8")
    assert updater.tail(log) == [f"line {n}" for n in range(25, 40)]
    assert updater.tail(tmp_path / "missing.log") == []


def test_a_missing_program_counts_as_a_failure(monkeypatch, tmp_path):
    def missing(command, check, stdout, stderr):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(updater.subprocess, "run", missing)
    log = tmp_path / "update.log"
    assert updater.run([["pipx", "upgrade", "magnacoda"]], log) is False
    assert updater.tail(log)[-1] == "pipx"


def test_the_repair_for_pipx_and_uv_is_a_reinstall_which_also_restores_add_ons():
    plan = updater.plan(["magnacoda", "public-addon"], PIPX, pipx="C:/pipx.exe")
    repair = updater.repair_command(PIPX, plan.commands).splitlines()
    assert repair[0] == "C:/pipx.exe reinstall magnacoda"
    assert repair[1].startswith("If that fails: C:/pipx.exe uninstall magnacoda, then install magnacoda")
    uv = updater.plan(["magnacoda"], UV, uv="uv")
    assert updater.repair_command(UV, uv.commands).splitlines()[0] == "uv tool upgrade --reinstall magnacoda"
    venv = updater.plan(["magnacoda"], VENV)
    assert updater.repair_command(VENV, venv.commands) == updater.shown(venv.commands[0])


def _windows(
    commands=None, folder=r"C:\Users\Zoë O'Brien\pipx\venvs\magnacoda", repair="pipx reinstall magnacoda"
):
    commands = commands or [
        [r"C:\Users\Zoë O'Brien\.local\bin\pipx.exe", "upgrade", "magnacoda"],
        ["pipx", "runpip", "magnacoda", "install", "--upgrade", "public-addon"],
    ]
    return updater.windows_script(commands, folder, repair)


def test_the_windows_script_waits_until_magnacoda_has_stopped_everywhere():
    script = _windows()
    assert script.endswith("\r\n") and "\n" not in script.replace("\r\n", "")
    assert "$folder = 'C:\\Users\\Zoë O''Brien\\pipx\\venvs\\magnacoda\\'" in script  # quote doubled
    assert "$_.ProcessName -like 'magnacod*'" in script  # every copy, any command or add-on command
    assert "$_.Path.StartsWith($folder" in script  # and anything run from the install folder
    assert "$_.Id -ne $PID" in script
    assert "while ((Running).Count -gt 0)" in script and "Start-Sleep" in script
    assert "Type exit at each magnacoda prompt" in script
    assert script.index("while ((Running)") < script.index("The update is starting")
    assert "Nothing has been changed yet: to cancel, just close this window." in script


def test_the_windows_script_asks_before_changing_anything_and_checks_again():
    script = _windows()
    go = script.index("Press Enter to update now (or close this window to cancel)")
    assert script.index("while ((Running)") < go < script.index("The update is starting")
    recheck = script.index("magnacoda was started again, so nothing was changed.")
    assert go < recheck < script.index("The update is starting")


def test_the_windows_script_runs_each_command_only_if_the_last_worked_and_offers_the_repair():
    lines = _windows().split("\r\n")
    runs = [line for line in lines if line.startswith("if ($ok) { & ")]
    assert runs[0] == (
        "if ($ok) { & 'C:\\Users\\Zoë O''Brien\\.local\\bin\\pipx.exe' 'upgrade' 'magnacoda' 2>&1 | "
        'ForEach-Object { "$_" } | Out-File -FilePath $log -Append -Encoding utf8'
    )
    assert lines[lines.index(runs[0]) + 1] == "    if ($LASTEXITCODE -ne 0) { $ok = $false } }"
    assert len(runs) == 2
    assert "    Write-Host 'If magnacoda no longer starts, repair it with:'" in lines
    assert "    Write-Host '  pipx reinstall magnacoda'" in lines
    assert "still works" not in "".join(lines)  # a half-finished update may have broken it
    assert lines[-3] == "Ask 'Press Enter to close this window'"
    assert lines[-2].startswith("Remove-Item -LiteralPath $PSCommandPath")


def test_the_windows_script_switches_off_quick_edit_and_throws_away_early_keys():
    script = _windows()
    assert "SetConsoleMode" in script and "-band 0xFFBF" in script and "-bor 0x80" in script
    ask = script[script.index("function Ask(") : script.index("Read-Host $question")]
    assert "FlushInputBuffer()" in ask and "[Console]::ReadKey($true)" in ask
    assert "Read-Host" not in script.replace(
        "    Read-Host $question | Out-Null", ""
    )  # every question uses Ask


# What Windows showed on 2026-10-01: one magnacoda in another tab, and this one running `update`. Each
# copy is the magnacoda.exe launcher -> the environment's python.exe stand-in -> the real python.exe.
WINDOWS_TABS = {
    1: (0, "explorer.exe"),
    10: (1, "WindowsTerminal.exe"),
    20: (10, "powershell.exe"),  # tab 1
    21: (20, "magnacode.exe"),
    22: (21, "python.exe"),
    23: (22, "python.exe"),
    30: (10, "powershell.exe"),  # tab 2, running update
    31: (30, "magnacoda.exe"),
    32: (31, "python.exe"),
    33: (32, "python.exe"),  # this process
}


def test_the_other_tab_counts_once_and_this_copy_not_at_all():
    assert updater.count_others(WINDOWS_TABS, me=33) == 1


def test_no_other_copies_and_several():
    alone = {k: v for k, v in WINDOWS_TABS.items() if k < 20 or k >= 30}
    assert updater.count_others(alone, me=33) == 0
    more = {**WINDOWS_TABS, 40: (10, "powershell.exe"), 41: (40, "MAGNACODE.EXE"), 42: (41, "python.exe")}
    assert updater.count_others(more, me=33) == 2


def test_a_broken_or_looping_process_list_does_not_hang():
    assert updater.count_others({5: (5, "magnacoda.exe")}, me=5) == 0  # its own parent
    assert updater.count_others({}, me=33) == 0
    assert updater.count_others({1: (2, "magnacoda.exe"), 2: (1, "python.exe")}, me=2) == 0
