from __future__ import annotations

import configparser
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from magnacoda.userdir import config_dir, write_private

DEFAULT_HISTORY_MAX = 100
DEFAULT_RECHECK_LIMIT = 3
_LIMITS = {"history": (0, 1000), "recheck": (0, 100)}

TEMPLATE = f"""# magnacoda preferences.
# Edit freely. A missing or invalid value falls back to the default. Add-ons may add sections.

[history]
# How many scans to remember in history.md (0 turns history off; at most 1000).
max = {DEFAULT_HISTORY_MAX}

[news]
# Once a day, ask pypi.org whether a newer magnacoda is available and fetch the news from
# news.magnacoda.dev (on or off). Nothing about you or your scans is sent.
check = on

[display]
# Type short text out in quick chunks in the interactive shell, like a terminal printer (on or off).
# Turn it off if you use a screen reader, which announces text as it arrives.
typing = on
# Show a spinner and what the scan is doing while it runs (on or off). Turn it off if you use a screen
# reader, which may announce every change; you then get one plain line per scan instead.
spinner = on
# Show a short tip under the list of commands that menu shows (on or off).
tips = on

[scan]
# Quick scans (on or off): leave out the slowest tests that use the page, which watch it for moving
# content and hover, click and press single keys, saving about 10 seconds a scan. The checklist then
# leaves those checks to you. A scan's --quick or --thorough overrides it.
quick = off
# Before the wizard runs a scan, check the page and say about how long the scan will take, offering
# settings that make it faster (on or off). The check loads the page once, in a few seconds.
estimate = on
# When you type scan with only an address, say what the default settings are and ask before
# scanning (on or off). Never asked with options, with -y, or when no person is there (CI, scripts).
confirm = on
# Where scans are saved, and where review and recheck look. Blank: magnacoda-scans in your Documents
# folder. A scan's --scans-dir saves one scan somewhere else.
folder =

[pager]
# How help, the README, news and view show text, one screen at a time.
# Page one screen at a time (on or off). Off prints everything at once, as MAGNACODA_PAGER=off does.
paging = on
# Show a link to another section as "text (section N)", N as in the g list, so you can type N to go
# there (on or off).
number_links = on
# Leave out a document's own table of contents, since the g list does its job (on or off).
hide_contents = on
# Colors for the pager; default is your terminal's own. Press c in the pager to try the others.
# Add your own in pager-colors.ini, in this folder (see the README).
colors = default
# Web addresses as links that open with Ctrl+click (on or off).
hyperlinks = on
# Fade between dark and light colors instead of switching at once (on or off).
fade = on
# When you resized the window while reading, start a fresh page when you leave (on or off). Off leaves
# the screen as the resize left it, which may look jumbled; your terminal's scrollback keeps it all.
refresh_after_resize = off

[ai]
# Which account the AI tiers (--ai explain/semantic) use: claude-plan (your Claude subscription,
# through Claude Code), api-key (an Anthropic API key, billed per use), or ask (decide the first
# time it matters; `setup` asks too). A scan's --ai-engine overrides it.
engine = ask

[review]
# How `review` opens a saved scan in your browser: tab (the browser decides; usually a new tab) or
# new (a new browser window, for Firefox, Chrome, Brave, Edge and Vivaldi).
window = tab

[recheck]
# How many times an AI agent or a script may recheck one saved scan, with no person at the keyboard,
# before recheck stops and asks for a person (0: no limit). Your own rechecks don't count. A new scan
# starts again from 0.
limit = {DEFAULT_RECHECK_LIMIT}
"""

AIChoice = Literal["ask", "api", "claude-code"]
# What people may write, and what it means. The flag's own names (api, claude-code) work here too.
_AI_CHOICES: dict[str, AIChoice] = {
    "ask": "ask",
    "auto": "ask",
    "claude-plan": "claude-code",
    "claude-code": "claude-code",
    "api-key": "api",
    "api": "api",
}
# How a choice is written back into the file: the clearer names, as in the comment above.
_AI_WRITTEN = {"ask": "ask", "claude-code": "claude-plan", "api": "api-key"}


@dataclass(frozen=True)
class Preferences:
    history_max: int = DEFAULT_HISTORY_MAX
    news_check: bool = True
    typing: bool = True
    spinner: bool = True
    tips: bool = True
    paging: bool = True
    ai_engine: AIChoice = "ask"
    review_window: Literal["tab", "new"] = "tab"
    quick: bool = False
    estimate: bool = True
    confirm: bool = True
    scans_folder: str = ""
    recheck_limit: int = DEFAULT_RECHECK_LIMIT


def preferences_path() -> Path:
    return config_dir() / "preferences.ini"


def ensure_file() -> None:
    """Create the preferences file with its defaults and comments if it does not exist. Never raises."""
    path = preferences_path()
    try:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(TEMPLATE, encoding="utf-8")
    except OSError:
        pass


def _number(parser: configparser.ConfigParser, section: str, key: str, default: int) -> int:
    low, high = _LIMITS[section]
    try:
        value = parser.getint(section, key, fallback=default)
    except ValueError:
        return default
    return min(max(value, low), high)


def load() -> Preferences:
    """The preferences, creating the file first if needed. Bad or missing values give the defaults."""
    ensure_file()
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    try:
        parser.read(preferences_path(), encoding="utf-8")
    except (configparser.Error, OSError, UnicodeError):
        return Preferences()
    try:
        news_check = parser.getboolean("news", "check", fallback=True)  # on/off, yes/no, true/false
    except ValueError:
        news_check = True
    try:
        typing = parser.getboolean("display", "typing", fallback=True)
    except ValueError:
        typing = True
    try:
        tips = parser.getboolean("display", "tips", fallback=True)
    except ValueError:
        tips = True
    try:
        spinner = parser.getboolean("display", "spinner", fallback=True)
    except ValueError:
        spinner = True
    try:
        quick = parser.getboolean("scan", "quick", fallback=False)
    except ValueError:
        quick = False
    try:
        estimate = parser.getboolean("scan", "estimate", fallback=True)
    except ValueError:
        estimate = True
    try:
        confirm = parser.getboolean("scan", "confirm", fallback=True)
    except ValueError:
        confirm = True
    try:
        paging = parser.getboolean("pager", "paging", fallback=True)
    except ValueError:
        paging = True
    ai_engine = _AI_CHOICES.get(parser.get("ai", "engine", fallback="ask").strip().lower(), "ask")
    window = parser.get("review", "window", fallback="tab").strip().lower()
    return Preferences(
        history_max=_number(parser, "history", "max", DEFAULT_HISTORY_MAX),
        news_check=news_check,
        typing=typing,
        tips=tips,
        spinner=spinner,
        paging=paging,
        ai_engine=ai_engine,
        review_window="new" if window in ("new", "window") else "tab",
        quick=quick,
        estimate=estimate,
        confirm=confirm,
        scans_folder=parser.get("scan", "folder", fallback="").strip(),
        recheck_limit=_number(parser, "recheck", "limit", DEFAULT_RECHECK_LIMIT),
    )


def set_ai_engine(choice: AIChoice) -> None:
    """Set [ai] engine in preferences.ini (see set_value)."""
    set_value("ai", "engine", _AI_WRITTEN[choice])


def set_value(section_name: str, key: str, written: str) -> None:
    """Set one of magnacoda's own settings in preferences.ini, adding its section or line if missing.
    Raises OSError, also when the file can't be read cleanly or the change would touch anything else;
    the file is then kept."""
    ensure_file()
    path = preferences_path()
    text = path.read_text(encoding="utf-8")
    line = re.compile(rf"^({re.escape(key)}\s*=).*$", re.MULTILINE)
    section = re.search(rf"^\[{re.escape(section_name)}\]\s*$", text, re.MULTILINE)
    if section is None:
        start = TEMPLATE.index(f"[{section_name}]")
        end = TEMPLATE.find("\n[", start)
        block = TEMPLATE[start : end + 1 if end != -1 else None]  # only this section; others may be there
        block = line.sub(lambda m: f"{m.group(1)} {written}", block, count=1)
        new_text = text.rstrip("\n") + "\n\n" + block
    else:
        rest = text[section.end() :]
        next_section = re.search(r"^\[", rest, re.MULTILINE)
        body = rest[: next_section.start()] if next_section else rest
        if line.search(body):
            body = line.sub(lambda m: f"{m.group(1)} {written}", body, count=1)
        else:
            body = f"\n{key} = {written}" + body
        new_text = text[: section.end()] + body + (rest[next_section.start() :] if next_section else "")
    try:
        before, after = _parse(text), _parse(new_text)
    except configparser.Error:
        raise OSError("preferences.ini has a line magnacoda can't read, so it was left as it is") from None
    expected = {name: dict(before.items(name)) for name in before.sections()}
    if section is None:  # the template's defaults come with the section
        expected[section_name] = dict(_parse(block).items(section_name))
    expected[section_name][key] = written
    if _contents(after) != expected:
        raise OSError("the change would have touched other settings, so preferences.ini was left as it is")
    write_private(path, new_text)


# Add-on settings. An add-on declares its section with AddonSection; magnacoda writes the section into
# preferences.ini and reads the values back, so an add-on never edits the file itself. Everything an
# add-on declares is checked first, and a change is written only when reading the new file back shows
# that nothing else changed, so a faulty add-on can't damage the file.

_CORE_SECTIONS = frozenset(re.findall(r"^\[(\w+)\]", TEMPLATE, re.MULTILINE))
_NAME = re.compile(r"[a-z][a-z0-9_]{1,29}")  # section and setting names
_WORD = re.compile(r"[a-z0-9][a-z0-9_-]{0,29}")  # the words a choice may be
_MAX_SETTINGS = 20
_MAX_COMMENT = 400
_COMMENT_WIDTH = 100


@dataclass(frozen=True)
class Setting:
    """One add-on setting: a whole number (give low and high), on or off (a bool default), or one word
    from `choices`. The comment says what it does, in one paragraph; magnacoda wraps it."""

    key: str
    default: int | bool | str
    comment: str
    low: int | None = None
    high: int | None = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class AddonSection:
    """An add-on's own section of preferences.ini. Raises ValueError if anything in it is not allowed."""

    name: str
    settings: tuple[Setting, ...]

    def __post_init__(self) -> None:
        _check_section(self)

    def setting(self, key: str) -> Setting:
        for setting in self.settings:
            if setting.key == key:
                return setting
        raise KeyError(f"[{self.name}] declares no setting named {key!r}")


def _check_section(section: AddonSection) -> None:
    if not isinstance(section.name, str) or not _NAME.fullmatch(section.name):
        raise ValueError(
            f"{section.name!r} can't name a section: use 2 to 30 of a-z, 0-9 and _, from a letter"
        )
    if section.name in _CORE_SECTIONS:
        raise ValueError(f"[{section.name}] is one of magnacoda's own sections")
    settings = section.settings
    if not isinstance(settings, tuple) or not 1 <= len(settings) <= _MAX_SETTINGS:
        raise ValueError(f"[{section.name}] needs a tuple of 1 to {_MAX_SETTINGS} settings")
    keys = [getattr(setting, "key", None) for setting in settings]
    if len(set(keys)) != len(keys):
        raise ValueError(f"[{section.name}] names a setting twice")
    for setting in settings:
        _check_setting(section.name, setting)


def _check_setting(where: str, setting: Setting) -> None:
    if not isinstance(setting, Setting):
        raise ValueError(f"[{where}] has something that is not a Setting")
    key, default = setting.key, setting.default
    if not isinstance(key, str) or not _NAME.fullmatch(key):
        raise ValueError(
            f"[{where}] {key!r} can't name a setting: use 2 to 30 of a-z, 0-9 and _, from a letter"
        )
    comment = setting.comment
    if not isinstance(comment, str) or not comment.strip() or len(comment) > _MAX_COMMENT:
        raise ValueError(f"[{where}] {key}: the comment must be 1 to {_MAX_COMMENT} characters")
    if not comment.isprintable():
        raise ValueError(f"[{where}] {key}: the comment must be one paragraph without control characters")
    if isinstance(default, bool):
        if setting.low is not None or setting.high is not None or setting.choices:
            raise ValueError(f"[{where}] {key}: an on/off setting takes no range or choices")
    elif isinstance(default, int):
        low, high = setting.low, setting.high
        if setting.choices or type(low) is not int or type(high) is not int or not low <= default <= high:
            raise ValueError(f"[{where}] {key}: a number needs whole-number low and high around its default")
    elif isinstance(default, str):
        choices = setting.choices
        if setting.low is not None or setting.high is not None or not isinstance(choices, tuple):
            raise ValueError(f"[{where}] {key}: a word setting takes a tuple of choices and no range")
        if not choices or not all(isinstance(c, str) and _WORD.fullmatch(c) for c in choices):
            raise ValueError(f"[{where}] {key}: each choice must be one word of a-z, 0-9, _ and -")
        if default not in choices:
            raise ValueError(f"[{where}] {key}: the default must be one of the choices")
    else:
        raise ValueError(f"[{where}] {key}: the default must be a whole number, True or False, or a word")


def _written(value: int | bool | str) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def _section_text(section: AddonSection) -> str:
    lines = ["", f"[{section.name}]"]
    for setting in section.settings:
        lines += textwrap.wrap(
            setting.comment, width=_COMMENT_WIDTH, initial_indent="# ", subsequent_indent="# "
        )
        lines.append(f"{setting.key} = {_written(setting.default)}")
    return "\n".join(lines) + "\n"


def _parse(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(inline_comment_prefixes=("#", ";"), interpolation=None)
    parser.read_string(text)
    return parser


def _contents(parser: configparser.ConfigParser) -> dict[str, dict[str, str]]:
    return {name: dict(parser.items(name)) for name in parser.sections()}


_declared: dict[str, AddonSection] = {}


def add_section(section: AddonSection) -> None:
    """Add the add-on's section to the end of preferences.ini if it is missing. The file is left as it
    is when it can't be read cleanly, or when the new text would change anything else. Raises
    ValueError only when another add-on already uses the section's name."""
    taken = _declared.setdefault(section.name, section)
    if taken != section:
        raise ValueError(f"another add-on already uses the preferences section [{section.name}]")
    ensure_file()
    path = preferences_path()
    try:
        text = path.read_text(encoding="utf-8")
        before = _parse(text)
        if before.has_section(section.name):
            return
        new_text = text + ("\n" if text and not text.endswith("\n") else "") + _section_text(section)
        expected = _contents(before)
        expected[section.name] = {s.key: _written(s.default) for s in section.settings}
        if _contents(_parse(new_text)) != expected:
            return
        write_private(path, new_text)
    except (configparser.Error, OSError, UnicodeError):
        pass


def addon_value(section: AddonSection, key: str) -> int | bool | str:
    """The value of one of an add-on's settings, adding its section first if missing. A missing or
    invalid value gives the default; a number out of range is brought into it."""
    setting = section.setting(key)
    add_section(section)
    try:
        raw = _parse(preferences_path().read_text(encoding="utf-8")).get(section.name, key, fallback=None)
    except (configparser.Error, OSError, UnicodeError):
        return setting.default
    if raw is None:
        return setting.default
    raw = raw.strip()
    if isinstance(setting.default, bool):
        state = configparser.ConfigParser.BOOLEAN_STATES.get(raw.lower())
        return setting.default if state is None else state
    if isinstance(setting.default, int):
        try:
            value = int(raw)
        except ValueError:
            return setting.default
        low, high = setting.low or 0, setting.high or 0  # both set: checked when declared
        return min(max(value, low), high)
    return raw.lower() if raw.lower() in setting.choices else setting.default
