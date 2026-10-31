"""Format Finding.css as (css, where) pairs; each report styles the CSS as code its own way.

set by `.entry a { text-decoration: none; color: #2a5a9a }` in /css/site.css, line 1
    (from /src/_links.scss, line 5)
"""

from __future__ import annotations

from magnacoda.findings.models import CssSource


def where_set(sources: list[CssSource]) -> list[tuple[str, str]]:
    """(the CSS, where it is) for each rule, declarations of the same rule together, in order."""
    groups: dict[tuple, list[CssSource]] = {}
    for source in sources:
        if source.kind == "not-set":
            continue
        key = (source.kind, source.selector, source.file, source.state, source.inherited)
        groups.setdefault(key, []).append(source)
    lines = []
    for group in groups.values():
        first = group[0]
        declarations = "; ".join(dict.fromkeys(s.declaration for s in group if s.declaration))
        if first.kind == "style-attribute":
            code = f'style="{declarations}"'
            where = "in the element's own style attribute" + (
                " (inherited from an ancestor's)" if first.inherited else ""
            )
        elif first.kind == "browser-default":
            code = declarations
            where = "(the browser's default: the site doesn't set it)"
        else:
            code = f"{first.selector} {{ {declarations} }}"
            where = _place(first, group)
        if first.state:
            where += ", with the keyboard focus on it"
        if first.inherited and first.kind != "style-attribute":
            where += " (inherited from an ancestor)"
        if first.utility_class:
            where += (
                "; it's a class on the element itself: if it's a utility class (as in Tailwind), change "
                "the element's classes in its HTML instead"
            )
        lines.append((code, where))
    return lines


def _place(source: CssSource, group: list[CssSource]) -> str:
    if source.kind == "script":
        return "added by a script (no file to point to)"
    numbers = sorted({s.line for s in group if s.line})
    line = (
        f", line {numbers[0]}"
        if len(numbers) == 1
        else f", lines {', '.join(map(str, numbers[:-1]))} and {numbers[-1]}"
        if numbers
        else ""
    )
    originals = sorted({s.original_line for s in group if s.original_line})
    if source.kind == "style-element":
        place = f"in a style element of the page ({source.file}{line} of its HTML)"
    else:
        place = f"in {source.file}{line}"
    if source.original_file:
        original_line = (
            f", line {originals[0]}"
            if len(originals) == 1
            else f", lines {', '.join(map(str, originals[:-1]))} and {originals[-1]}"
            if originals
            else ""
        )
        place += f" (from {source.original_file}{original_line}, by its source map)"
    return place
