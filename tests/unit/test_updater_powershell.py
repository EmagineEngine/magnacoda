"""The Windows update script, actually run by PowerShell (pwsh) where it is installed; skipped
elsewhere. A process that gives itself the name of magnacoda stands in for a running magnacoda.
Windows itself (file locking, Windows PowerShell 5.1, the new window) still needs a check by hand on
Windows."""

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from magnacoda import updater

PWSH = shutil.which("pwsh")
# The stand-in for a running magnacoda: its own name, so a real magnacoda open on this machine doesn't
# make the tests wait for it, and one per test process, so tests run in parallel don't wait for each
# other's. Linux keeps 15 characters of a process name.
FAKE = f"fakemc{os.getpid()}"
# The stand-in is Python, renaming itself with prctl(PR_SET_NAME), so it doesn't depend on a program
# such as `sleep`, which on Ubuntu 26.04 is one multi-call program that fails when copied under a new name.
_STAND_IN = (
    "import ctypes, sys, time; "
    "ctypes.CDLL(None).prctl(15, sys.argv[1].encode()); "
    "time.sleep(float(sys.argv[2]))"
)
pytestmark = pytest.mark.skipif(
    PWSH is None or not sys.platform.startswith("linux"), reason="needs PowerShell (pwsh) on Linux"
)


def _script(tmp_path: Path, exit_code: int = 0) -> Path:
    install = tmp_path / "install"
    install.mkdir()
    stand_in = [
        PWSH,
        "-NoProfile",
        "-Command",
        f"Write-Host 'STAND-IN RAN'; [Console]::Error.WriteLine('PROGRESS ON STDERR'); exit {exit_code}",
    ]
    script = tmp_path / "update.ps1"
    log = str(tmp_path / "update.log")
    script.write_text(
        updater.windows_script([stand_in], str(install), "pipx reinstall magnacoda", log=log, program=FAKE),
        encoding="utf-8-sig",
    )
    return script


def _start(seconds: int) -> subprocess.Popen[bytes]:
    """Start the fake magnacoda, and collect it the moment it ends: on Linux a finished child that
    hasn't been collected still shows in the process list (Windows has no such leftovers), and the
    script would rightly keep waiting for it."""
    process = subprocess.Popen([sys.executable, "-c", _STAND_IN, FAKE, str(seconds)])
    threading.Thread(target=process.wait, daemon=True).start()
    return process


def _run(script: Path, keys: str = "\n\n", timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PWSH, "-NoProfile", "-File", str(script)],
        input=keys,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_the_script_parses():
    script = updater.windows_script(
        [["pipx", "upgrade", "magnacoda"]], r"C:\Users\Zoë O'Brien\venv", "pipx reinstall magnacoda"
    )
    check = (
        "$e = $null; [void][System.Management.Automation.Language.Parser]::ParseInput("
        "[Console]::In.ReadToEnd(), [ref]$null, [ref]$e); if ($e) { $e | ForEach-Object Message; exit 1 }"
    )
    result = subprocess.run(
        [PWSH, "-NoProfile", "-Command", check], input=script, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_it_waits_while_magnacoda_runs_then_asks_then_updates(tmp_path):
    script = _script(tmp_path)
    # The fake runs until the script says it's waiting, then stops: PowerShell can take many seconds
    # to start on a busy machine, so a fake that ends on its own may be gone before the script looks.
    running = _start(120)
    process = subprocess.Popen(
        [PWSH, "-NoProfile", "-File", str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    lines = []
    try:
        process.stdin.write("\n\n")
        process.stdin.close()
        for line in process.stdout:
            lines.append(line)
            if "Waiting..." in line:
                running.terminate()
        process.wait(timeout=60)
    finally:
        running.kill()
        process.kill()
    out = "".join(lines)
    assert out.index("Waiting...") < out.index("magnacoda has stopped.") < out.index("The update is starting")
    assert "Done. Start magnacoda again" in out
    assert "STAND-IN RAN" not in out  # its output went to the log
    raw = (tmp_path / "update.log").read_bytes()  # PowerShell 7 writes UTF-8; Windows PowerShell 5.1, UTF-16
    logged = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")
    assert "STAND-IN RAN" in logged and "PROGRESS ON STDERR" in logged
    assert "NativeCommandError" not in logged and "CategoryInfo" not in logged  # plain lines only
    assert not script.exists()  # it deletes itself


def test_a_failed_update_shows_the_repair(tmp_path):
    script = _script(tmp_path, exit_code=3)
    out = _run(script).stdout
    assert "The last lines of its log:" in out and "  STAND-IN RAN" in out and "The whole log is in" in out
    assert "If magnacoda no longer starts, repair it with:" in out
    assert "  pipx reinstall magnacoda" in out and "Done." not in out


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX pseudo-terminal")
def test_magnacoda_started_again_before_enter_means_no_update(tmp_path):
    script = _script(tmp_path)
    terminal, running = _Terminal(script), None
    try:
        assert _until(terminal, "Press Enter to update now")  # it saw no magnacoda and asks
        running = _start(120)  # magnacoda is started again before Enter
        terminal.wait(0.5)
        terminal.press_enter()
        assert _until(terminal, "magnacoda was started again, so nothing was changed.")
        assert "STAND-IN RAN" not in terminal.text() and "The update is starting" not in terminal.text()
    finally:
        if running is not None:
            running.kill()
        terminal.close()


class _Terminal:
    """PowerShell on a pseudo-terminal, so it reads keys as from a real keyboard. It answers
    PowerShell's cursor-position queries (ESC [6n) as a real terminal would."""

    def __init__(self, script: Path):
        self.fd, child = os.openpty()
        self.process = subprocess.Popen(
            [PWSH, "-NoProfile", "-File", str(script)],
            stdin=child,
            stdout=child,
            stderr=child,
            start_new_session=True,
        )
        os.close(child)
        self.output = b""

    def wait(self, seconds: float) -> None:
        import select

        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ready, _, _ = select.select([self.fd], [], [], 0.05)
            if ready:
                try:
                    chunk = os.read(self.fd, 4096)
                except OSError:
                    return
                self.output += chunk
                for _ in range(chunk.count(b"\x1b[6n")):
                    os.write(self.fd, b"\x1b[1;1R")

    def press_enter(self, then_wait: float = 0.3) -> None:
        os.write(self.fd, b"\r")
        self.wait(then_wait)

    def text(self) -> str:
        return self.output.decode(errors="replace")

    def running(self) -> bool:
        return self.process.poll() is None

    def close(self) -> None:
        if self.running():
            self.process.kill()
        self.process.wait()
        os.close(self.fd)


def _until(terminal: _Terminal, words: str, seconds: float = 60) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end and words not in terminal.text():
        terminal.wait(0.2)
    return words in terminal.text()


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX pseudo-terminal")
def test_enter_pressed_early_or_during_the_update_is_thrown_away(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    stand_in = [PWSH, "-NoProfile", "-Command", "Start-Sleep 2; exit 0"]
    script = tmp_path / "update.ps1"
    script.write_text(
        updater.windows_script([stand_in], str(install), "r", log=str(tmp_path / "u.log"), program=FAKE),
        encoding="utf-8-sig",
    )
    running = _start(120)  # stopped below, once the script has seen it
    terminal = _Terminal(script)
    try:
        assert _until(terminal, "Waiting...")
        for _ in range(3):
            terminal.press_enter()  # impatient presses while magnacoda still runs
    finally:
        running.terminate()
    assert _until(terminal, "Press Enter to update now")
    terminal.wait(1)
    assert "The update is starting" not in terminal.text()  # the early presses didn't start it
    terminal.press_enter()
    assert _until(terminal, "The update is starting. Please wait")
    for _ in range(3):
        terminal.press_enter(0.1)  # impatient presses while it updates
    assert _until(terminal, "Press Enter to close this window")
    terminal.wait(1)
    assert terminal.running()  # the result stays on screen
    terminal.press_enter()
    end = time.monotonic() + 15
    while terminal.running() and time.monotonic() < end:
        terminal.wait(0.2)
    running = terminal.running()
    terminal.close()
    assert not running  # a fresh press closes it
