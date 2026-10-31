"""What's new, update notices and the news feed, for the banner and the `news` command.

- What's new comes from data/whats-new.md (no network).
- Updates: a daily PyPI check for magnacoda and published add-ons. Private packages are never looked up,
  and a PyPI project must link to the same URL as the installed package, so look-alikes are ignored.
- News: a daily Markdown feed from NEWS_URL, stripped of control characters before display.

Requests send only the version (user_agent). Checks run in the background, fail silently, and are off
with MAGNACODA_NEWS=off, `check = off` in preferences.ini, in CI, or outside a terminal.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from importlib import metadata, resources
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from magnacoda import __version__, plugins, preferences
from magnacoda.userdir import config_dir, write_private

NEWS_URL = "https://news.magnacoda.dev/v1/news.md"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
ENV_OFF_SWITCH = "MAGNACODA_NEWS"
OFF_VALUES = {"off", "0", "false", "no"}
CHECK_INTERVAL = timedelta(hours=24)
TIMEOUT = 3.0  # seconds, per request
MAX_FEED_BYTES = 64 * 1024
MAX_PYPI_BYTES = 4 * 1024 * 1024
MAX_FEED_ITEMS = 20
SHOWN_DAYS = 3  # the banner mentions each update or news item on the first shell of a day, this many days
PRIVATE_CLASSIFIER = "Private :: Do Not Upload"

# fetch(url, max_bytes) -> body; raises on any failure. Tests pass their own.
Fetch = Callable[[str, int], bytes]

_lock = threading.Lock()


# --------------------------------------------------------------------------- when checks may run


def allowed(env: dict[str, str] | None = None) -> bool:
    """The user's switches: MAGNACODA_NEWS=off, `check = off` in preferences.ini, or a CI run."""
    env = dict(os.environ) if env is None else env
    if env.get(ENV_OFF_SWITCH, "").strip().lower() in OFF_VALUES or env.get("CI", "").strip():
        return False
    return preferences.load().news_check


def checks_enabled(stdin: Any = None, stdout: Any = None, env: dict[str, str] | None = None) -> bool:
    """allowed(), and running in a real terminal (so never in scripts or piped output)."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    try:
        if not (stdin.isatty() and stdout.isatty()):
            return False
    except (AttributeError, ValueError):
        return False
    return allowed(env)


# --------------------------------------------------------------------------- the saved state


@dataclass
class FeedItem:
    id: str  # the heading, "2026-11-02 Title"
    date: str
    title: str
    body: str


@dataclass
class State:
    checked: str = ""  # ISO time of the last check, successful or not
    latest: dict[str, str] = field(default_factory=dict)  # package -> latest version on PyPI
    feed: list[FeedItem] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)  # feed item ids opened in `news`
    notes_seen: str | None = None  # the version whose notes were last announced or read
    shown: dict[str, list[str]] = field(default_factory=dict)  # banner item -> local dates it was shown


def state_path() -> Path:
    return config_dir() / "news-state.json"


def load_state() -> State:
    try:
        raw = json.loads(state_path().read_text(encoding="utf-8"))
        return State(
            checked=str(raw.get("checked", "")),
            latest={str(k): str(v) for k, v in dict(raw.get("latest", {})).items()},
            feed=[
                FeedItem(**{k: str(item[k]) for k in ("id", "date", "title", "body")})
                for item in raw.get("feed", [])
            ],
            seen=[str(x) for x in raw.get("seen", [])],
            notes_seen=None if raw.get("notes_seen") is None else str(raw["notes_seen"]),
            shown={str(k): [str(d) for d in v] for k, v in dict(raw.get("shown", {})).items()},
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return State()


def save_state(state: State) -> None:
    data = {
        "checked": state.checked,
        "latest": state.latest,
        "feed": [item.__dict__ for item in state.feed],
        "seen": state.seen[-200:],
        "notes_seen": state.notes_seen,
        "shown": state.shown,
    }
    try:
        write_private(state_path(), json.dumps(data, indent=1) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- text from outside

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‎‏‪-‮⁦-⁩]")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def clean(text: str) -> str:
    """Strip control characters and direction overrides (newlines and tabs stay)."""
    return _CONTROL.sub("", text.replace("\r\n", "\n"))


_FEED_HEADING = re.compile(r"^##[ \t]+(\d{4}-\d{2}-\d{2})[ \t]+(.+?)[ \t]*$")


def parse_feed(text: str) -> list[FeedItem]:
    """Feed items, newest first, from `## YYYY-MM-DD Title` headings."""
    items: list[FeedItem] = []
    current: list[str] | None = None
    for line in _COMMENT.sub("", clean(text)).splitlines():
        heading = _FEED_HEADING.match(line)
        if heading:
            date, title = heading.group(1), heading.group(2)
            current = []
            items.append(FeedItem(f"{date} {title}", date, title, ""))
        elif line.startswith("## "):
            current = None  # a heading without a date: not an item
        elif current is not None:
            current.append(line.rstrip())
            items[-1].body = "\n".join(current).strip("\n")[:4000]
    items.sort(key=lambda item: item.date, reverse=True)
    return items[:MAX_FEED_ITEMS]


_NOTES_HEADING = re.compile(r"^##[ \t]+v?(\d+(?:\.\d+)*)\b.*$")


def release_notes() -> dict[str, str]:
    """{version: notes} from the packaged whats-new.md (one `## X.Y.Z` section per release)."""
    try:
        text = (resources.files("magnacoda") / "data" / "whats-new.md").read_text(encoding="utf-8")
    except OSError:
        return {}
    notes: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in _COMMENT.sub("", text).splitlines():
        heading = _NOTES_HEADING.match(line)
        if heading:
            current = notes.setdefault(heading.group(1), [])
        elif line.startswith("## "):
            current = None
        elif current is not None:
            current.append(line.rstrip())
    return {version: "\n".join(lines).strip("\n") for version, lines in notes.items() if any(lines)}


def notes_for(version: str) -> str:
    """This release's notes (0.4.0 also matches 0.4, 0.4.0.post1 and dev builds), or ""."""
    wanted = release_numbers(version)
    for noted, text in release_notes().items():
        if wanted is not None and release_numbers(noted) == wanted:
            return text
    return ""


# --------------------------------------------------------------------------- versions
# `packaging` handles pre/post/dev releases, epochs and local labels the way pip does.


def parse_version(text: str) -> Version | None:
    try:
        return Version(text.strip())
    except InvalidVersion:
        return None


def release_numbers(version: str) -> tuple[int, ...] | None:
    """The release numbers, without trailing zeros (0.4.0 and 0.4 -> (0, 4)), or None if unreadable."""
    parsed = parse_version(version)
    if parsed is None:
        return None
    numbers = list(parsed.release)
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return tuple(numbers)


def is_offered(version: str) -> bool:
    """A final release (no alpha, beta, rc or dev)."""
    parsed = parse_version(version)
    return parsed is not None and not parsed.is_prerelease


def is_newer(latest: str, installed: str) -> bool:
    """`latest` is a newer final release. Never for dev or local installs."""
    new, old = parse_version(latest), parse_version(installed)
    if new is None or old is None or new.is_prerelease or old.is_devrelease or old.local:
        return False
    return new > old


# --------------------------------------------------------------------------- what is installed


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    urls: frozenset[str]  # its declared web addresses, normalized


def _normalized(url: str) -> str:
    url = url.strip().lower()
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.rstrip("/").removesuffix(".git")


def _package(name: str) -> Package | None:
    """An installed distribution worth asking PyPI about, or None (missing, or marked private)."""
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    md = dist.metadata
    if PRIVATE_CLASSIFIER in (md.get_all("Classifier") or []):
        return None
    urls = [value.split(",", 1)[-1] for value in md.get_all("Project-URL") or []]
    urls += md.get_all("Home-page") or []
    return Package(md["Name"] or name, dist.version, frozenset(_normalized(u) for u in urls if u.strip()))


def installed_packages() -> list[Package]:
    """magnacoda, then each add-on package once (a collection of add-ons is one package)."""
    names = ["magnacoda"]
    for addon in plugins.loaded():
        if addon.package not in names:
            names.append(addon.package)
    return [package for package in (_package(name) for name in names) if package is not None]


# --------------------------------------------------------------------------- checking


def user_agent() -> str:
    """User-Agent: the version only ("magnacoda/1.2.0"), without a dev build's "+..." part."""
    return f"magnacoda/{__version__.split('+')[0]}"


def _fetch(url: str, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent()})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - fixed https URLs
        body: bytes = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"{url} sent more than {max_bytes} bytes")
    return body


def latest_on_pypi(package: Package, fetch: Fetch | None = None) -> str | None:
    """Latest PyPI release if that project links back to ours, else None."""
    if not package.urls:
        return None  # nothing to recognize it by
    try:
        info = json.loads((fetch or _fetch)(PYPI_URL.format(name=package.name), MAX_PYPI_BYTES))["info"]
        theirs = {_normalized(str(u)) for u in (info.get("project_urls") or {}).values()}
        if info.get("home_page"):
            theirs.add(_normalized(str(info["home_page"])))
        if not theirs & package.urls:
            return None
        version = str(info["version"])
    except Exception:  # noqa: BLE001 - any failure is silent
        return None
    return version if is_offered(version) else None


def _now() -> datetime:
    return datetime.now(UTC)


def _local_date() -> str:
    """Today in the person's own time zone: a day of the banner starts at their midnight."""
    return datetime.now().date().isoformat()


def due(state: State, now: datetime | None = None) -> bool:
    try:
        last = datetime.fromisoformat(state.checked)
    except ValueError:
        return True
    return (now or _now()) - last >= CHECK_INTERVAL


def refresh(fetch: Fetch | None = None, force: bool = False, now: datetime | None = None) -> None:
    """Check for updates and fetch the news, if a day has passed (or `force`). Never raises."""
    fetch = fetch or _fetch
    try:
        state = load_state()
        if not force and not due(state, now):
            return
        latest: dict[str, str] = {}
        for package in installed_packages():
            version = latest_on_pypi(package, fetch)
            if version:
                latest[package.name] = version
        try:
            feed: list[FeedItem] | None = parse_feed(
                fetch(NEWS_URL, MAX_FEED_BYTES).decode("utf-8", "replace")
            )
        except Exception:  # noqa: BLE001
            feed = None
        with _lock:
            state = load_state()  # re-read: `news` may have marked items seen meanwhile
            state.checked = (now or _now()).isoformat()
            state.latest = latest
            if feed is not None:
                state.feed = feed
            save_state(state)
    except Exception:  # noqa: BLE001 - checking must never break anything
        pass


def refresh_in_background() -> None:
    """Start a daily check without waiting for it (the banner shows what the previous one found)."""
    if checks_enabled() and due(load_state()):
        threading.Thread(target=refresh, name="magnacoda-news", daemon=True).start()


def note_first_run() -> None:
    """First run: mark this version's notes as seen; there's nothing new to a new user."""
    with _lock:
        state = load_state()
        if state.notes_seen is None:
            state.notes_seen = __version__
            save_state(state)


# --------------------------------------------------------------------------- what to show


@dataclass(frozen=True)
class Update:
    name: str
    installed: str
    latest: str


def updates(state: State | None = None) -> list[Update]:
    """Installed packages with a newer release on PyPI, from the last check."""
    state = load_state() if state is None else state
    found = []
    for package in installed_packages():
        latest = state.latest.get(package.name)
        if latest and is_newer(latest, package.version):
            found.append(Update(package.name, package.version, latest))
    return found


def unseen_items(state: State) -> list[FeedItem]:
    return [item for item in state.feed if item.id not in state.seen]


def notes_unseen(state: State) -> bool:
    return state.notes_seen is not None and state.notes_seen != __version__ and bool(notes_for(__version__))


def _notice_parts(state: State, env: dict[str, str] | None) -> list[tuple[str, set[str]]]:
    """The banner line's parts, each with the items it mentions ("update:name:version", "notes:version",
    "news:id")."""
    parts: list[tuple[str, set[str]]] = []
    checks = allowed(env)
    available = updates(state) if checks else []
    for update in available:
        if update.name == "magnacoda":
            parts.append(
                (
                    f"magnacoda {update.latest} is available (you have {update.installed}; type update)",
                    {f"update:magnacoda:{update.latest}"},
                )
            )
    addon_updates = [u for u in available if u.name != "magnacoda"]
    if addon_updates:
        plural = "s" if len(addon_updates) > 1 else ""
        parts.append(
            (
                f"{len(addon_updates)} add-on update{plural} (type update)",
                {f"update:{u.name}:{u.latest}" for u in addon_updates},
            )
        )
    if notes_unseen(state):
        parts.append((f"what's new in {release_label(__version__)}", {f"notes:{__version__}"}))
    unseen = unseen_items(state) if checks else []
    if unseen:
        count = f"{len(unseen)} news item{'s' if len(unseen) > 1 else ''}"
        parts.append((count, {f"news:{item.id}" for item in unseen}))
    return parts


def notice_line(env: dict[str, str] | None = None, only: set[str] | None = None) -> str:
    """The banner's update/news line from saved state, or "". With `only`, just the parts that mention
    one of those items (what today_notice chose for this shell)."""
    try:
        parts = [text for text, items in _notice_parts(load_state(), env) if only is None or items & only]
        if not parts:
            return ""
        tail = " - type news" if any(not part.endswith("update)") for part in parts) else ""
        return "News: " + " · ".join(parts) + tail
    except Exception:  # noqa: BLE001
        return ""


def today_notice(env: dict[str, str] | None = None, today: str | None = None) -> set[str]:
    """The items the banner mentions in this shell, noted as shown today: each one only in the day's
    first shell, on up to SHOWN_DAYS days (days it was shown, so a week away still shows it). `news`
    and `update` still show everything."""
    today = today or _local_date()
    try:
        with _lock:
            state = load_state()
            items = set().union(*(items for _, items in _notice_parts(state, env)))
            chosen: set[str] = set()
            for item in items:
                days = state.shown.get(item, [])
                if today not in days and len(days) < SHOWN_DAYS:
                    chosen.add(item)
                    state.shown[item] = [*days, today]
            # Forget items no longer on offer (read, installed, or gone from the feed).
            state.shown = {item: days for item, days in state.shown.items() if item in items}
            save_state(state)
            return chosen
    except Exception:  # noqa: BLE001
        return set()


def release_label(version: str) -> str:
    """The version as people read it: "0.4.0" (also for 0.4.0.dev3 or 0.4.0+local)."""
    parsed = parse_version(version)
    return parsed.base_version if parsed else version


def mark_all_seen() -> None:
    with _lock:
        state = load_state()
        state.seen = list(dict.fromkeys([*state.seen, *(item.id for item in state.feed)]))
        state.notes_seen = __version__
        save_state(state)


def sections(env: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Pager sections for `news`: updates, release notes, news."""
    state = load_state()
    checks = allowed(env)
    found: list[tuple[str, str]] = []
    available = updates(state) if checks else []
    if available:
        lines = [f"- `{u.name} {u.installed} -> {u.latest}`" for u in available]
        found.append(
            ("updates", "Updates available\n" + "\n".join(lines) + "\n\nType `update` to install them.")
        )
    notes = notes_for(__version__)
    if notes:
        found.append(("whats-new", f"What's new in {release_label(__version__)}\n\n" + notes))
    if checks and state.feed:
        items = []
        for item in state.feed:
            new = "" if item.id in state.seen else " (new)"
            items.append(f"{item.date}  {item.title}{new}\n\n{item.body}".rstrip())
        found.append(("news", "News\n\n" + "\n\n".join(items)))
    return found
