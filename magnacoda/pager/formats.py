"""The kinds of document the pager lays out. A program says which one it's showing; the pager does
the rest.

- MARKDOWN: Markdown, one page per `##` section (markdown.py).
- REFERENCE: a command reference laid out like a man page (reference.py).
- TEXT: plain text, word-wrapped.
"""

from __future__ import annotations

from dataclasses import dataclass

from magnacoda.pager import markdown, reference
from magnacoda.pager.screen import Wrapper, default_wrap


@dataclass(frozen=True)
class Format:
    name: str
    render: Wrapper  # one section's text as screen lines of a given width
    emphasis: bool = False  # the pager styles *italic* and **bold** itself (Markdown does its own)
    code: bool = False  # `code` and code blocks get a background of their own (tint.py)


MARKDOWN = Format("markdown", markdown.render, code=True)
REFERENCE = Format("reference", reference.render, emphasis=True, code=True)
TEXT = Format("text", default_wrap)
