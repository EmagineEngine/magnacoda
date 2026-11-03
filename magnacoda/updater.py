"""The `update` command's plan: how magnacoda was installed, and the commands that update it.

- A development install (editable, from a checkout) is never updated: that's `git pull`.
- pipx: `pipx upgrade magnacoda`, and `pipx runpip magnacoda install --upgrade <add-on>` for add-ons
  (pipx's own "include injected" option would also try private add-ons, which aren't on PyPI).
- uv: `uv tool upgrade magnacoda`, which upgrades the whole tool environment, so add-ons installed
  with `--with` come along.
- pip in a virtual environment: that environment's `python -m pip install --upgrade ...`.
- Anything else (a system or Homebrew Python, an install that needs admin rights, or one that can't be
  recognized), or pipx or uv not on the PATH: the command is only shown. magnacoda never runs `sudo`.

On Windows the files are locked while magnacoda runs, so the commands go into a PowerShell script in a
new window that waits for every copy to exit first.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

DEV, PIPX, UV, VENV, SHOW = "development", "pipx", "uv tool", "virtual environment", "show only"


@dataclass(frozen=True)
class Plan:
    kind: str  # DEV, PIPX, UV, VENV (run), or SHOW (only shown)
    commands: list[list[str]]  # what to run (or, for SHOW, what to suggest)
    note: str = ""


def is_editable(name: str = "magnacoda") -> bool:
    try:
        raw = metadata.distribution(name).read_text("direct_url.json")
        return bool(raw and json.loads(raw).get("dir_info", {}).get("editable"))
    except (metadata.PackageNotFoundError, ValueError, AttributeError):
        return False


def install_kind(
    prefix: str | None = None, base_prefix: str | None = None, editable: bool | None = None
) -> str:
    """How magnacoda was installed, judged from the running environment's folders."""
    if is_editable() if editable is None else editable:
        return DEV
    # Forward slashes work everywhere, so Windows folders are read the same way on any system.
    here = (sys.prefix if prefix is None else prefix).replace("\\", "/")
    path = Path(here)
    parts = [part.lower() for part in path.parts]
    if path.parent.name.lower() == "venvs" and any("pipx" in part for part in parts):
        return PIPX
    # uv writes a receipt into every tool's folder; the folder names cover a receipt that's gone.
    if (path / "uv-receipt.toml").is_file() or (path.parent.name.lower() == "tools" and "uv" in parts):
        return UV  # its environment has no pip, so uv itself must do it
    if (sys.base_prefix if base_prefix is None else base_prefix).replace("\\", "/") != here:
        return VENV
    return SHOW


def plan(
    packages: list[str], kind: str | None = None, pipx: str | None = None, uv: str | None = None
) -> Plan:
    """The commands that update `packages` (magnacoda and/or add-on names) for this install."""
    kind = install_kind() if kind is None else kind
    addons = [name for name in packages if name != "magnacoda"]
    if kind == DEV:
        return Plan(DEV, [], "This is a development install: update it with git pull.")
    if kind == PIPX:
        pipx = shutil.which("pipx") if pipx is None else pipx
        commands = []
        if "magnacoda" in packages:
            commands.append([pipx or "pipx", "upgrade", "magnacoda"])
        if addons:
            commands.append([pipx or "pipx", "runpip", "magnacoda", "install", "--upgrade", *addons])
        if pipx:
            return Plan(PIPX, commands)
        return Plan(SHOW, commands, "pipx isn't on your PATH here, so run this yourself:")
    if kind == UV:
        uv = shutil.which("uv") if uv is None else uv
        commands = [[uv or "uv", "tool", "upgrade", "magnacoda"]]  # add-ons included
        if uv:
            return Plan(UV, commands)
        return Plan(SHOW, commands, "uv isn't on your PATH here, so run this yourself:")
    if kind == VENV:
        return Plan(VENV, [[sys.executable, "-m", "pip", "install", "--upgrade", *packages]])
    commands = [["python", "-m", "pip", "install", "--upgrade", *packages]]
    if "magnacoda" in packages:
        commands.insert(0, ["pipx", "upgrade", "magnacoda"])
    return Plan(
        SHOW,
        commands,
        "magnacoda can't tell how it was installed here, so it won't change anything itself. Run the "
        "command that matches how you installed it: pipx, or pip for the Python you used (that may need "
        "administrator rights).",
    )


def shown(command: list[str]) -> str:
    """A command as the user would type it in their own terminal."""
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    import shlex

    return shlex.join(command)


TAIL_LINES = 15  # how much of the log is shown when an update fails


def log_path() -> Path:
    """Log for pip's output; only its tail is shown, and only on failure."""
    return Path(tempfile.gettempdir()) / "magnacoda-update.log"


def run(commands: list[list[str]], log: Path) -> bool:
    """Run the commands in turn, output to `log`. False at the first failure."""
    with log.open("w", encoding="utf-8") as file:
        for command in commands:
            file.write(f"$ {shown(command)}\n")
            file.flush()
            try:
                if (
                    subprocess.run(command, check=False, stdout=file, stderr=subprocess.STDOUT).returncode
                    != 0
                ):
                    return False
            except OSError as exc:
                file.write(f"{exc}\n")
                return False
    return True


def tail(log: Path, lines: int = TAIL_LINES) -> list[str]:
    """The last lines of the log, where the reason for a failure usually is."""
    try:
        return log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def repair_command(kind: str, commands: list[list[str]]) -> str:
    """Recovery commands for a half-finished update. pipx reinstall fails while an add-on's requirement
    isn't on PyPI, hence the fallback."""
    if kind == PIPX and commands:
        pipx = commands[0][0]
        return (
            f"{shown([pipx, 'reinstall', 'magnacoda'])}\n"
            f"If that fails: {shown([pipx, 'uninstall', 'magnacoda'])}, then install magnacoda (and any "
            "add-ons) again the way you did the first time."
        )
    if kind == UV and commands:
        uv = commands[0][0]
        return (
            f"{shown([uv, 'tool', 'upgrade', '--reinstall', 'magnacoda'])}\n"
            f"If that fails: {shown([uv, 'tool', 'uninstall', 'magnacoda'])}, then install magnacoda (and "
            "any add-ons) again the way you did the first time."
        )
    return "\n".join(shown(command) for command in commands)


def _ps(text: str) -> str:
    """A PowerShell string literal: single quotes, with any single quote doubled."""
    return "'" + text.replace("'", "''") + "'"


def _with_separator(folder: str) -> str:
    """The folder with a trailing separator, so a sibling with the same prefix doesn't match."""
    separator = "/" if "/" in folder and "\\" not in folder else "\\"
    return folder.rstrip("/\\") + separator


@dataclass(frozen=True)
class Words:
    """What the Windows script says, for an update or an uninstall."""

    action: str  # the window title's last word, and the log's name
    waiting: str
    go: str
    again: str
    starting: tuple[str, ...]
    done: str
    failed: str
    fix: str


UPDATE_WORDS = Words(
    action="update",
    waiting="magnacoda will be updated as soon as it has stopped.",
    go="Press Enter to update now (or close this window to cancel)",
    again="magnacoda was started again, so nothing was changed. Quit it and run update again.",
    starting=(
        "The update is starting. Please wait: it can take a minute or two, and nothing more",
        "appears here until it has finished.",
    ),
    done="Done. Start magnacoda again to use the new version.",
    failed="The update did not finish. The last lines of its log:",
    fix="If magnacoda no longer starts, repair it with:",
)


def windows_script(
    commands: list[list[str]],
    install_folder: str,
    repair: str,
    log: str | None = None,
    program: str = "magnacod",
    words: Words = UPDATE_WORDS,
) -> str:
    """PowerShell script: wait for every magnacoda process to exit, confirm, run the commands into
    `log`, show the tail only on failure, then delete itself. Tests pass their own `program` prefix so
    a real magnacoda on the machine doesn't block them.
    """
    lines = [
        f"$Host.UI.RawUI.WindowTitle = 'magnacoda {words.action}'",
        # Windows freezes a console window while text is selected in it ("Quick Edit": a click inside
        # starts a selection), which looks like the update hanging. Switch that off for this window.
        "try {",
        "    Add-Type -Namespace MagnacodaUpdate -Name Console -MemberDefinition @'",
        '[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int handle);',
        '[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr handle, out uint mode);',
        '[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr handle, uint mode);',
        "'@",
        "    $in = [MagnacodaUpdate.Console]::GetStdHandle(-10)",
        "    $mode = [uint32]0",
        "    if ([MagnacodaUpdate.Console]::GetConsoleMode($in, [ref]$mode)) {",
        "        # 0x40: Quick Edit (cleared); 0x80: extended flags (needed for the change to apply)",
        "        $mode = [uint32](($mode -band 0xFFBF) -bor 0x80)",
        "        [void][MagnacodaUpdate.Console]::SetConsoleMode($in, $mode)",
        "    }",
        "} catch { }",
        "function Ask($question) {",
        "    # Throw away keys pressed earlier, so only a fresh Enter answers (an early press must not",
        "    # start the update, or close the window before the result has been read).",
        "    try { $Host.UI.RawUI.FlushInputBuffer() } catch { }",
        "    try { while ([Console]::KeyAvailable) { [void][Console]::ReadKey($true) } } catch { }",
        "    Read-Host $question | Out-Null",
        "}",
        f"$folder = {_ps(_with_separator(install_folder))}",
        "function Running {",
        "    $ErrorActionPreference = 'SilentlyContinue'  # some system processes won't show their path",
        "    @(Get-Process | Where-Object {",
        f"        $_.Id -ne $PID -and ($_.ProcessName -like {_ps(program + '*')} -or",
        "        ($_.Path -and $_.Path.StartsWith($folder, [StringComparison]::OrdinalIgnoreCase)))",
        "    })",
        "}",
        f"Write-Host {_ps(words.waiting)}",
        "Write-Host 'Nothing has been changed yet: to cancel, just close this window.'",
        "$told = $false",
        "while ((Running).Count -gt 0) {",
        "    if (-not $told) {",
        "        Write-Host ''",
        "        Write-Host 'magnacoda is still running, perhaps in another window or tab.'",
        "        Write-Host 'Type exit at each magnacoda prompt. You do not need to close any windows.'",
        "        Write-Host 'Waiting...'",
        "        $told = $true",
        "    }",
        "    Start-Sleep -Seconds 1",
        "}",
        "Write-Host ''",
        "Write-Host 'magnacoda has stopped.'",
        f"Ask {_ps(words.go)}",
        "if ((Running).Count -gt 0) {",  # started again while waiting for Enter: don't break it
        f"    Write-Host {_ps(words.again)}",
        "    Ask 'Press Enter to close this window'",
        "    Remove-Item -LiteralPath $PSCommandPath -ErrorAction SilentlyContinue",
        "    exit 1",
        "}",
        "Write-Host ''",
        *[f"Write-Host {_ps(line)}" for line in words.starting],
        (
            f"$log = {_ps(log)}"
            if log
            else f"$log = Join-Path ([IO.Path]::GetTempPath()) 'magnacoda-{words.action}.log'"
        ),
        "Remove-Item -LiteralPath $log -ErrorAction SilentlyContinue",
        "$ok = $true",
    ]
    for command in commands:
        call = "& " + " ".join(_ps(part) for part in command)
        # 2>&1 and "$_" turn each line into plain text: pipx writes its progress to the error channel,
        # which Windows PowerShell 5.1 would otherwise log wrapped in alarming error formatting.
        lines += [
            f'if ($ok) {{ {call} 2>&1 | ForEach-Object {{ "$_" }} | '
            "Out-File -FilePath $log -Append -Encoding utf8",
            "    if ($LASTEXITCODE -ne 0) { $ok = $false } }",
        ]
    lines += [
        "Write-Host ''",
        "if ($ok) {",
        f"    Write-Host {_ps(words.done)}",
        "} else {",
        f"    Write-Host {_ps(words.failed)}",
        f"    Get-Content -LiteralPath $log -Tail {TAIL_LINES} -ErrorAction SilentlyContinue |",
        '        ForEach-Object { Write-Host "  $_" }',
        '    Write-Host "The whole log is in $log"',
        "    Write-Host ''",
        f"    Write-Host {_ps(words.fix)}",
        *[f"    Write-Host {_ps('  ' + line)}" for line in repair.splitlines()],
        "}",
        "Ask 'Press Enter to close this window'",
        "Remove-Item -LiteralPath $PSCommandPath -ErrorAction SilentlyContinue",
    ]
    return "\r\n".join(lines) + "\r\n"


def count_others(processes: dict[int, tuple[int, str]], me: int) -> int:
    """Other running magnacoda processes, from {pid: (ppid, name)}.

    This process's ancestors don't count: on Windows the launcher is a grandparent (launcher -> python.exe
    stub -> python).
    """
    mine: set[int] = set()
    pid = me
    while pid in processes and pid not in mine and len(mine) < 64:  # 64: never loop on a reused pid
        mine.add(pid)
        pid = processes[pid][0]
    return sum(
        1 for pid, (_, name) in processes.items() if name.lower().startswith("magnacod") and pid not in mine
    )


def _windows_processes() -> dict[int, tuple[int, str]]:  # pragma: no cover - Windows only
    """{pid: (ppid, name)} via CreateToolhelp32Snapshot; empty if it fails."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return {}
    processes: dict[int, tuple[int, str]] = {}
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            processes[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return processes


def others_running() -> int:  # pragma: no cover - Windows only
    """Other running copies of magnacoda; 0 if unknown."""
    try:
        return count_others(_windows_processes(), os.getpid())
    except (OSError, AttributeError, ValueError):
        return 0


def start_in_new_window(
    commands: list[list[str]], repair: str, words: Words = UPDATE_WORDS
) -> bool:  # pragma: no cover - Windows only
    """Write the script and open it in a new PowerShell window. False if that couldn't be started."""
    try:
        handle, path = tempfile.mkstemp(prefix=f"magnacoda-{words.action}-", suffix=".ps1")
        # utf-8-sig: Windows PowerShell 5.1 reads a script as UTF-8 only with the byte-order mark.
        with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as file:
            file.write(windows_script(commands, sys.prefix, repair, words=words))
        new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
            creationflags=new_console,
            close_fds=True,
        )
    except OSError:
        return False
    return True
