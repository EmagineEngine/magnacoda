"""Reading a file to show: control codes stripped, huge or binary files refused, Markdown recognized."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from magnacoda.pager.markdown import looks_like_markdown

MAX_BYTES = 2 * 1024 * 1024
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkd"}
# Files that may be Markdown without saying so (LICENSE, NOTICE, notes.txt): looks_like_markdown decides.
MAYBE_MARKDOWN_SUFFIXES = {"", ".txt"}
# Control characters and text-direction overrides; newlines and tabs stay.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‎‏‪-‮⁦-⁩]")


class CannotView(Exception):
    """Why a file can't be shown, in words for the user."""


@dataclass(frozen=True)
class TextFile:
    path: Path
    text: str
    markdown: bool


def clean(text: str) -> str:
    """Strip control characters and direction overrides (newlines and tabs stay)."""
    return _CONTROL.sub("", text.replace("\r\n", "\n"))


def read(typed: str, max_bytes: int | None = None) -> TextFile:
    """The file `typed` names, relative to the current folder (`~` works); MAX_BYTES at most unless
    `max_bytes` says otherwise. Raises CannotView."""
    max_bytes = MAX_BYTES if max_bytes is None else max_bytes
    path = Path(typed).expanduser()
    try:
        if path.is_dir():
            raise CannotView(f"{typed} is a folder, not a file.")
        size = path.stat().st_size
    except FileNotFoundError:
        raise CannotView(f"There is no file {typed} (looked in {Path.cwd()}).") from None
    except OSError as exc:
        raise CannotView(f"Could not read {typed}: {exc.strerror or exc}.") from None
    if size > max_bytes:
        limit = max_bytes / 1024 / 1024
        raise CannotView(
            f"{typed} is too large to view ({size / 1024 / 1024:.1f} MB; the limit is {limit:g} MB)."
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CannotView(f"Could not read {typed}: {exc.strerror or exc}.") from None
    if b"\0" in data[:8192]:
        raise CannotView(f"{typed} doesn't look like a text file, so it can't be shown here.")
    text = clean(data.decode("utf-8", "replace"))
    if not text.strip():
        raise CannotView(f"{typed} is empty.")
    suffix = path.suffix.lower()
    markdown = suffix in MARKDOWN_SUFFIXES or (
        suffix in MAYBE_MARKDOWN_SUFFIXES and looks_like_markdown(text)
    )
    return TextFile(path=path, text=text, markdown=markdown)
