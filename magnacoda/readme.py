"""The README and the manual that came with this version, for the `readme` and `docs` commands (shown
with pager.markdown)."""

from __future__ import annotations

import posixpath
import re

from magnacoda import documents

REPOSITORY = "https://github.com/emagineengine/magnacoda"
# A link to another file in the repository, such as (SECURITY.md) or (docs/manual.md#scan-options):
# not a web address, an #anchor or a picture.
_RELATIVE_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\((?!https?://|#|mailto:)([^)\s]+)\)")


def _with_full_links(text: str, source: str) -> str:
    """Relative links made full, since the viewer opens only web addresses."""
    folder = posixpath.dirname(source)

    def full(match: re.Match[str]) -> str:
        path = posixpath.normpath(posixpath.join(folder, match.group(2)))
        return f"[{match.group(1)}]({REPOSITORY}/blob/main/{path})"

    return _RELATIVE_LINK.sub(full, text)


def _document(packaged: str) -> str | None:
    """data/`packaged` when installed, its source in the repository from a checkout, else None."""
    path = documents.locate(packaged)
    if path is None:
        return None
    return _with_full_links(path.read_text(encoding="utf-8"), documents.SOURCES[packaged])


def readme_text() -> str | None:
    return _document("README.md")


def manual_text() -> str | None:
    return _document("manual.md")
