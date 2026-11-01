from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from magnacoda import plugins
from magnacoda.browser.redirects import from_elsewhere
from magnacoda.findings.checklist import load_guidance
from magnacoda.findings.merge import tested_text, where_text
from magnacoda.findings.models import (
    CriterionEntry,
    FeatureExample,
    Finding,
    OptionGroup,
    PageImage,
    ScanReport,
)
from magnacoda.report.css_lines import where_set


def _link(entry: CriterionEntry) -> str:
    return f"**[{entry.num} {entry.title}]({entry.url})** ({entry.level})"


_SEVERITY_ORDER = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}
_IMAGE_CHECKS = {
    "1.1.1": "does its text alternative say what it shows? Where it has none, or is marked decorative, "
    "answer the question with the image.",
    "1.4.5": "if it shows text, could that be real text instead? (Text in a logo is fine.)",
}


_HIDDEN_REACHABLE = (
    "it can't be seen, yet Tab moves focus to it and screen readers read it out, so keyboard users lose "
    "track of where they are and screen reader users meet something nobody else sees (a hidden "
    "honeypot field against spam, or an off-screen menu, often does this). If it's not meant to be used, "
    "hide it from both: `display: none` (or `visibility: hidden` to keep its space in the layout), or "
    '`tabindex="-1"` on it and `aria-hidden="true"` on its container. If it is meant to be used, make '
    "it visible, at least while it has focus."
)


_BOX = re.compile(r"^- \[[ xX]\] ")
_CRITERION_ITEM = re.compile(r"^- \[[ xX]\] \*\*\[(\d+(?:\.\d+)+) ")
ID_MARK = re.compile(r"<!-- id:([A-Za-z0-9._-]+) -->")


def item_id(selector: str, kind: str, key: str) -> str:
    """Stable ID for one tickable item: hashed selector, item kind and rule/criterion."""
    digest = hashlib.sha1(selector.encode("utf-8")).hexdigest()[:10]
    return f"e-{digest}-{kind}-" + re.sub(r"[^A-Za-z0-9._-]", "_", key or "x")


def _with_id(text: str, identifier: str) -> str:
    """Append the ID as an HTML comment: invisible in editors, and how ticks.py finds the line."""
    first, newline, rest = text.partition("\n")
    return f"{first} <!-- id:{identifier} -->{newline}{rest}"


def _add_criterion_ids(lines: list[str]) -> list[str]:
    """IDs for criterion items (c-<number>) and page-level failures (u-<n>)."""
    out, unplaced = [], 0
    for line in lines:
        if _BOX.match(line) and not ID_MARK.search(line.split("\n")[0]):
            criterion = _CRITERION_ITEM.match(line)
            if criterion:
                line = _with_id(line, f"c-{criterion.group(1)}")
            else:
                unplaced += 1
                line = _with_id(line, f"u-{unplaced}")
        out.append(line)
    return out


@dataclass
class _Item:
    """One problem or check on an element. Elements with equal `shared` are grouped; `before`/`after`
    are per-element lines."""

    kind: str  # fix, review, hidden or check
    key: tuple[str, str]
    shared: list[str]  # the item's line, then its own sub-lines ("why it matters", "fix")
    before: list[str] = field(default_factory=list)
    after: list[str] = field(default_factory=list)
    finding: Finding | None = None  # for a Fix: the failure it is about (recheck.py tests it again)


_KIND_ORDER = {"fix": 0, "review": 1, "hidden": 2, "check": 3}


@dataclass
class _Element:
    """One element with its picture or options and its items, each once."""

    selector: str
    hint: str = ""
    image: PageImage | None = None
    items: list[_Item] = field(default_factory=list)
    keys: set[tuple[str, str]] = field(default_factory=set)
    options: list[str] = field(default_factory=list)  # a radio or checkbox group's options
    rank: int = 9  # 0-3 the worst failure's severity, 4 something axe-core couldn't decide,
    # 5 hidden but reachable, 9 checks only
    seen: int = 0

    def add(self, item: _Item) -> None:
        if item.key not in self.keys:
            self.keys.add(item.key)
            self.items.append(item)

    def ordered_items(self) -> list[_Item]:
        return sorted(self.items, key=lambda item: (_KIND_ORDER[item.kind], item.key))

    def signature(self) -> tuple[tuple[tuple[str, str], tuple[str, ...]], ...]:
        """What it has in common with an element that would be listed with it: the same items."""
        return tuple((item.key, tuple(item.shared)) for item in self.ordered_items())

    def done_id(self) -> str | None:
        """ID of the Checked box; hashes its checks so a tick doesn't carry over to different checks."""
        checks = sorted(f"{a}:{b}" for a, b in (item.key for item in self.items) if a != "fix")
        if not checks:
            return None
        digest = hashlib.sha1("|".join(checks).encode("utf-8")).hexdigest()[:6]
        return item_id(self.selector, "done", digest)


class _Elements:
    def __init__(self, groups: list[OptionGroup] | None = None) -> None:
        self.by_selector: dict[str, _Element] = {}
        # An option of a radio or checkbox group is listed as part of its group (one question).
        self.group_of: dict[str, OptionGroup] = {
            option.selector: group for group in groups or [] for option in group.options
        }

    def get(self, selector: str, hint: str = "") -> _Element:
        group = self.group_of.get(selector)
        if group is not None:
            selector, hint = group.element.selector, group.element.hint
        element = self.by_selector.get(selector)
        if element is None:
            element = self.by_selector[selector] = _Element(selector, hint, seen=len(self.by_selector))
            if group is not None:
                element.options = [option.hint or option.selector for option in group.options]
        elif hint and not element.hint:
            element.hint = hint
        return element

    def ordered(self) -> list[_Element]:
        return sorted(self.by_selector.values(), key=lambda e: (e.rank, e.seen))


def _criteria(nums: list[str], by_num: dict[str, CriterionEntry]) -> str:
    return (
        ", ".join(_link(by_num[num]) if num in by_num else f"**{num}**" for num in nums)
        or "**best practice**"
    )


def _fix_key(finding: Finding) -> tuple[str, str] | None:
    """Findings sharing a fix: by text for templates, by fix_group for AI fixes."""
    if finding.fix is None:
        return None
    if finding.fix.generated_by == "template":
        return (finding.rule_id, finding.fix.summary)
    group = finding.explanation.fix_group if finding.explanation else None
    return (finding.rule_id, f"group:{group}") if group else None


def _fix_item(
    finding: Finding, by_num: dict[str, CriterionEntry], shared: int = 1, variants: list[str] | None = None
) -> _Item:
    """A failed check: what's wrong (including "only on mobile" and the like) and the fix."""
    where = where_text(finding.seen_in, variants or [])
    lines = [
        f"**Fix** {_criteria(finding.wcag_criteria, by_num)} - {_plain(finding.description)} "
        f"*({finding.severity}; rule {finding.rule_id}{'; ' + where if where else ''})*"
    ]
    if finding.explanation:
        lines.append(f"  - why it matters: {_plain(finding.explanation.why_it_matters)}")
        lines.append(f"  - how to fix: {_with_code(finding.explanation.how_to_fix)}")
    after = []
    if finding.fix:
        label = "fix" if finding.fix.generated_by == "template" else "AI-suggested fix"
        same = f" *(the same fix applies to {shared} elements)*" if shared > 1 else ""
        lines.append(f"  - {label}: {_with_code(finding.fix.summary)}{same}")
        snippet = finding.fix.corrected_snippet
        if snippet and snippet != finding.html_snippet:
            after.append(f"e.g. {_code(_one_line(snippet))}")
    before = [f"now: {_code(_one_line(finding.html_snippet)[:200])}"] if finding.html_snippet else []
    before += [
        f"set by {_code(_one_line(code)[:300])} {_plain(where)}" for code, where in where_set(finding.css)
    ]
    return _Item("fix", ("fix", finding.rule_id), lines, before, after)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _image_lines(number: int, image: PageImage, variants: list[str] | None = None) -> list[str]:
    """What an image looks like and how it's described to someone who can't see it (no checkboxes)."""
    lines = []
    where = where_text(image.seen_in, variants or [])
    if image.file:
        target = f"<{image.file}>" if " " in image.file else image.file
        size = f" ({image.width}×{image.height})" if image.width and image.height else ""
        lines.append(f"- ![Screenshot of image {number}]({target}){size}")
    else:
        lines.append("- (no screenshot: the image couldn't be photographed)")
    if where:
        lines.append(f"- shown {where}")
    uses_alt = image.kind in ("img", "input-image")  # svg, canvas and role="img" are named other ways
    # Where it has no text alternative, ask whether it's decorative, and give the change for each answer.
    # Hidden from screen readers, any alt or label it has goes unread, so that comes first.
    if image.hidden and image.hidden.endswith("around it"):
        alt = (
            'hidden from screen readers by `aria-hidden="true"` on an element around it. Is it purely '
            "decorative? **No:** take `aria-hidden` off that element, so the image can be named."
        )
    elif image.hidden:
        name_it = "describe it in `alt`" if uses_alt else 'add `role="img"` and `aria-label="..."`'
        alt = (
            f"marked decorative (`{image.hidden}`). Is it purely decorative? "
            f"**No:** remove `{image.hidden}`, then {name_it}."
        )
    elif image.alt is None and not image.label:
        alt = (
            '**none**. Is it purely decorative? **Yes:** add `alt=""`. **No:** add `alt="..."` saying what '
            "it shows (or, in a link or button, where it goes or what it does)."
            if uses_alt
            else '**none**. Is it purely decorative? **Yes:** add `aria-hidden="true"`. **No:** add '
            '`role="img"` and `aria-label="..."` saying what it shows.'
        )
    elif image.alt == "" and not image.label:
        alt = 'marked decorative (`alt=""`). Is it purely decorative? **No:** describe it in `alt`.'
    elif image.alt:
        alt = f'"{_plain(image.alt)}"'
    else:
        alt = "none (named another way, below)" if uses_alt else "see below"
    lines.append(f"- {'alt text' if uses_alt else 'text alternative'}: {alt}")
    if image.label:
        lines.append(f'- named by aria-label or title: "{_plain(image.label)}"')
    if image.src:
        if image.src.startswith("data:"):
            lines.append("- source: embedded in the page (a data: address)")
        else:
            lines.append(f"- source: {_code(image.src[:150])}")
    return lines


def _check(entry: CriterionEntry, question: str, note: str = "") -> _Item:
    """A check a person makes on an element; a note from magnacoda's own tests is the element's own."""
    return _Item(
        "check",
        ("check", entry.num),
        [f"**Check** {_link(entry)} - {question}"],
        [note.strip()] if note else [],
    )


def _page_elements(report: ScanReport, by_num: dict[str, CriterionEntry]) -> tuple[list[_Element], list[str]]:
    """(each element with its items, in order; failures that belong to no particular element)."""
    elements = _Elements(report.option_groups)
    unplaced: list[str] = []

    def named(selector: str) -> tuple[str, str]:
        name = report.element_names.get(selector)
        return (name.selector, name.hint) if name else (selector, "")

    shared: dict[tuple[str, str], int] = {}
    first: dict[tuple[str, str], Finding] = {}  # an AI fix group's wording: its first member's, for all
    for finding in report.findings:
        key = _fix_key(finding)
        if key:
            shared[key] = shared.get(key, 0) + 1
            first.setdefault(key, finding)
    for finding in report.findings:
        key = _fix_key(finding)
        worded = finding
        if key and finding.fix and finding.fix.generated_by != "template":
            lead = first[key]
            worded = finding.model_copy(
                update={
                    "explanation": lead.explanation,
                    "fix": finding.fix.model_copy(update={"summary": lead.fix.summary if lead.fix else ""}),
                }
            )
        item = _fix_item(worded, by_num, shared.get(key, 1) if key else 1, report.meta.variants)
        item.finding = finding
        if not finding.selector:
            lines = _item_lines(item, None, own=True)
            unplaced.append("\n".join(["- [ ] " + lines[0][2:], *lines[1:]]))  # its u- ID comes later
            continue
        element = elements.get(*named(finding.selector))
        element.rank = min(element.rank, _SEVERITY_ORDER.get(finding.severity, 3))
        element.add(item)
        element.keys.update(("covered", num) for num in finding.wcag_criteria)
    for rule in report.needs_review:
        for detail in rule.details:
            selector, _, reason = detail.partition(" - ")
            element = elements.get(*named(selector))
            element.rank = min(element.rank, 4)
            line = (
                f"**Review** {_criteria(rule.wcag_criteria, by_num)} - {_plain(rule.description)} "
                f"*(axe-core couldn't decide; rule {rule.rule_id})*"
            )
            element.add(_Item("review", ("review", rule.rule_id), [line], [f"here: {_plain(reason)}"]))
    # Before the relevant checks: being invisible yet reachable is the likeliest real problem.
    hidden = report.page_features.examples.get("hidden_reachable", []) if report.page_features else []
    for example in hidden:
        element = elements.get(example.selector, example.hint)
        element.rank = min(element.rank, 5)
        line = f"**Check** {_criteria(['2.4.7', '2.4.3'], by_num)} - {_HIDDEN_REACHABLE}"
        element.add(_Item("hidden", ("hidden", ""), [line]))
    evidence = _evidence(report)
    for entry in (e for e in report.checklist if e.tier == "relevant"):
        for example in entry.examples:
            element = elements.get(example.selector, example.hint)
            if ("covered", entry.num) not in element.keys:
                _hint, note = evidence.pop((example.selector, entry.num), ("", ""))
                element.add(_check(entry, entry.how_to_check or "", note))
    # What sending the forms empty showed, for fields and forms not listed by a relevant check above.
    for (selector, num), (hint, note) in evidence.items():
        if num not in by_num:
            continue
        element = elements.get(selector, hint)
        if ("covered", num) not in element.keys:
            element.add(_check(by_num[num], by_num[num].how_to_check or "", note))
    for number, image in enumerate(report.images, start=1):
        element = elements.get(image.selector, image.alt or image.label or "")
        element.image = image
        element.keys.add(("image", str(number)))
        for num, question in _IMAGE_CHECKS.items():
            if num in by_num and ("covered", num) not in element.keys:
                element.add(_check(by_num[num], question))
    return elements.ordered(), unplaced


def _quoted(texts: list[str]) -> str:
    return "; ".join(f'"{_plain(text)}"' for text in texts)


def _empty_submit_evidence(report: ScanReport) -> dict[tuple[str, str], tuple[str, str]]:
    """Empty-submit notes for Check items: {(selector, criterion): (hint, note)}."""
    notes: dict[tuple[str, str], tuple[str, str]] = {}
    for form in report.empty_submit.forms if report.empty_submit else []:
        where = (form.form.selector, form.form.hint)
        for field_ in form.fields:
            if field_.message and (field_.invalid or form.outcome == "browser"):
                how = (
                    "the browser's own check stopped it and named this field"
                    if form.outcome == "browser"
                    else "it was marked invalid, with its message tied to it"
                )
                notes[(field_.element.selector, "3.3.1")] = (
                    field_.element.hint,
                    f" *Sent empty, {how}*, so an empty field is handled; try a wrong value too "
                    "(such as a badly formed one).",
                )
            if field_.message:
                said = "the browser said" if form.outcome == "browser" else "it said"
                notes[(field_.element.selector, "3.3.3")] = (
                    field_.element.hint,
                    f" *Sent empty, {said}:* {_quoted([field_.message])}",
                )
        if form.messages:
            notes[(where[0], "3.3.3")] = (
                where[1],
                f" *Sent empty, the form showed:* {_quoted(form.messages)}. Do they say which field "
                "is wrong and how to fix it?",
            )
            if not any(f.invalid or f.message for f in form.fields):
                notes[(where[0], "3.3.1")] = (
                    where[1],
                    " *Sent empty, the form showed error text, but no field was marked invalid or tied to "
                    "it:* make sure each message says which field it's about.",
                )
        if form.outcome == "page" and form.announced:
            notes[(where[0], "4.1.3")] = (
                where[1],
                " *Sent empty, its error messages reached screen readers*; check its other messages too "
                '(such as "Sent" or a number of results).',
            )
        if form.outcome == "sent" and form.required:
            fields = "field is" if form.required == 1 else "fields are"
            notes[(where[0], "3.3.1")] = (
                where[1],
                f" *Sent empty, the form went out with no message, although {form.required} {fields} "
                "marked required* (magnacoda stopped it, so nothing arrived). If the site checks it on "
                "its server, look at the page that comes back.",
            )
    return notes


_KEYBOARD_NUMS = ("2.4.7", "2.4.11", "2.1.2", "3.2.1")


def _criterion_notes(report: ScanReport) -> dict[str, str]:
    """Keyboard notes for criterion lines a person still decides."""
    notes: dict[str, str] = {}
    for note in report.interaction.notes if report.interaction else []:
        if not note.element.selector:
            notes[note.num] = notes.get(note.num, "") + note.note
    keyboard = report.keyboard
    if keyboard is None or not keyboard.stops:
        return notes
    went = f"Tab went through {'all' if keyboard.complete else 'the first'} {keyboard.stops} elements"
    if keyboard.jumps:
        jumps = "; ".join(f"{_example(a)} to {_example(b)}" for a, b in keyboard.jumps)
        notes["2.4.3"] = (
            f" *{went}; the focus jumped back up the page from* {jumps}. Does that order make sense?"
        )
    else:
        notes["2.4.3"] = f" *{went}, always moving on down the page*; check that the order also makes sense."
    if keyboard.skip_link == "works":
        notes["2.4.1"] = " *The skip link at the start works.*"
    if not keyboard.complete:
        for num in _KEYBOARD_NUMS:  # (a criterion with a problem found is listed as failed instead)
            notes[num] = f" *{went} without this problem, then had to stop*; check the rest by hand."
    return notes


def _fields_evidence(report: ScanReport) -> dict[tuple[str, str], tuple[str, str]]:
    """What looking at the fields showed, as notes for their 1.3.5 and 3.3.8 Check items."""
    fields = report.fields
    if fields is None:
        return {}
    notes: dict[tuple[str, str], tuple[str, str]] = {}
    for purpose in fields.purposes:
        where = (purpose.element.selector, "1.3.5")
        if purpose.autocomplete and purpose.autocomplete == purpose.guess:
            note = f' *It has autocomplete="{_plain(purpose.autocomplete)}", as its label suggests.*'
        elif purpose.autocomplete:
            note = (
                f' *It has autocomplete="{_plain(purpose.autocomplete)}"*: check that this is what it '
                "asks for."
            )
        elif not purpose.guess:
            note = (
                " *Its label doesn't look like the visitor's own details*; if it does ask for them, add the "
                "matching autocomplete value."
            )
        else:
            continue  # listed to fix
        notes[where] = (purpose.element.hint, note)
    flagged = {p.element.selector for p in fields.problems if p.kind != "missing-autocomplete"}
    for purpose in fields.purposes:
        if purpose.guess in ("current-password", "new-password") and purpose.element.selector not in flagged:
            notes[(purpose.element.selector, "3.3.8")] = (
                purpose.element.hint,
                " *Pasting into it works, and password managers aren't turned away*; check for puzzles, or "
                "anything to remember or copy by hand.",
            )
    return notes


def _evidence(report: ScanReport) -> dict[tuple[str, str], tuple[str, str]]:
    """Everything magnacoda's own tests noted for Check items, by (selector, criterion)."""
    notes = _empty_submit_evidence(report)
    more = _fields_evidence(report)
    for seen in report.interaction.notes if report.interaction else []:
        if seen.element.selector:
            key = (seen.element.selector, seen.num)
            more[key] = (seen.element.hint, more[key][1] + seen.note if key in more else seen.note)
    for key, (hint, text) in more.items():
        notes[key] = (hint, notes[key][1] + text) if key in notes else (hint, text)
    return notes


def _own_lines(
    element: _Element, images: list[PageImage], in_group: bool, variants: list[str] | None = None
) -> list[str]:
    """The element's own lines: picture, options, and per-item details when grouped."""
    lines: list[str] = []
    if element.image is not None:
        lines += _image_lines(images.index(element.image) + 1, element.image, variants)
    if element.options:
        lines.append("- options: " + ", ".join(f'"{_plain(option)}"' for option in element.options))
    if in_group:
        seen: set[str] = set()
        for item in element.ordered_items():
            label = "" if item.kind == "fix" else f"{item.key[1] or 'check'}: "
            for line in item.before + item.after:
                if line not in seen:
                    seen.add(line)
                    lines.append(f"- {label}{line}")
    return lines


def _item_lines(item: _Item, box_id: str | None, own: bool) -> list[str]:
    """Fix items get a box; others are plain lines."""
    first = f"- [ ] {item.shared[0]} <!-- id:{box_id} -->" if box_id else f"- {item.shared[0]}"
    before = [f"  - {line}" for line in item.before] if own else []
    after = [f"  - {line}" for line in item.after] if own else []
    return [first, *before, *item.shared[1:], *after]


_DONE_LINE = "**Checked:** tick when you've looked at everything below that needs a person"


def _block(
    number: int, group: list[_Element], images: list[PageImage], variants: list[str] | None = None
) -> list[str]:
    """One element, or a stack of identical ones: each with its box, then the shared items once."""
    first = group[0]
    items = first.ordered_items()
    fixes = [item for item in items if item.kind == "fix"]
    checks = [item for item in items if item.kind != "fix"]
    if len(group) == 1:
        heading = f"### {number}. {_example(FeatureExample(selector=first.selector, hint=first.hint))}"
        body = _own_lines(first, images, in_group=False, variants=variants)
        for item in fixes:
            body += _item_lines(item, item_id(first.selector, *item.key), own=True)
        done = first.done_id()
        if done:
            body.append(f"- [ ] {_DONE_LINE} <!-- id:{done} -->")
        for item in checks:
            body += _item_lines(item, None, own=True)
        return [heading, "", *body, ""]
    # A verb first, so the number doesn't run into the count ("8. 4 elements" reads as 8.4).
    verb = "Fix and check" if fixes and checks else "Fix" if fixes else "Check"
    each = "both" if len(group) == 2 else "all"
    heading = f"### {number}. {verb} these {len(group)} elements, {each} in the same way"
    body = []
    for element in group:
        name = _example(FeatureExample(selector=element.selector, hint=element.hint))
        done = element.done_id()
        body.append(f"- [ ] {name} <!-- id:{done} -->" if done else f"- {name}")
        body += [f"  {line}" for line in _own_lines(element, images, in_group=True, variants=variants)]
    together = "\n".join(sorted(element.selector for element in group))
    shared = []
    for item in fixes:
        shared += _item_lines(item, item_id(together, *item.key), own=False)
    for item in checks:
        shared += _item_lines(item, None, own=False)
    tick = " (tick each one above when you've checked it)" if checks else ""
    return [heading, "", *body, "", f"For each of them{tick}:", "", *shared, ""]


def fix_targets(report: ScanReport) -> dict[str, list[Finding]]:
    """Fix box ID -> the failures behind it, as to_markdown would write them. Page-level failures have
    no stable ID and are skipped."""
    by_num = {e.num: e for e in report.checklist}
    elements, _unplaced = _page_elements(report, by_num)
    targets: dict[str, list[Finding]] = {}
    for group in _grouped(elements):
        together = group[0].selector if len(group) == 1 else "\n".join(sorted(e.selector for e in group))
        for item in group[0].ordered_items():
            if item.kind != "fix":
                continue
            members = [next(i for i in element.items if i.key == item.key) for element in group]
            targets[item_id(together, *item.key)] = [m.finding for m in members if m.finding is not None]
    return targets


def _grouped(elements: list[_Element]) -> list[list[_Element]]:
    """Elements with exactly the same items, together, in the order of the first of each."""
    groups: dict[tuple[object, ...], list[_Element]] = {}
    for element in elements:
        groups.setdefault(element.signature(), []).append(element)
    return list(groups.values())


def anchor(title: str) -> str:
    """Heading anchor as generated by GitHub, GitLab and most other renderers."""
    return re.sub(r"[^a-z0-9 -]", "", title.lower()).replace(" ", "-")


def _section(title: str, intro: str | None, lines: list[str]) -> tuple[str, list[str]] | None:
    if not lines:
        return None
    heading = f"{title} ({len(lines)})"
    block = [f"## {heading}", ""]
    if intro:
        block += [intro, ""]
    return heading, block + lines + [""]


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>])")  # (# and | matter only at a line's start or in tables)


def _code(text: str) -> str:
    """Text as inline code (a selector), never breaking out of its backticks."""
    return "`" + text.replace("`", "'") + "`"


def _plain(text: str) -> str:
    """Page text shown as-is: Markdown characters in it are escaped, so it can't format the checklist."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text)


_CODE_SPAN = re.compile(r"`([^`\n]+)`")


def _with_code(text: str) -> str:
    """Escape fix text except `code` spans, so AI or axe text can't add other formatting."""
    parts = _CODE_SPAN.split(text)  # plain text, code, plain text, ...
    return "".join(_code(part) if i % 2 else _plain(part) for i, part in enumerate(parts))


def _example(example: FeatureExample) -> str:
    """One element behind a manual check: its selector, and what it says or is labelled."""
    return _code(example.selector) + (f' ("{_plain(example.hint)}")' if example.hint else "")


_QUICK = "; a quick scan (no watching for moving content, hovering, clicking or single keys)"


def to_markdown(report: ScanReport) -> str:
    meta = report.meta
    entries = report.checklist
    by_num = {e.num: e for e in entries}
    by_status = lambda status: [e for e in entries if e.tier == "automated" and e.status == status]  # noqa: E731
    by_tier = lambda tier: [e for e in entries if e.tier == tier]  # noqa: E731
    elements, unplaced = _page_elements(report, by_num)
    checked_per_element = {
        key[1] for element in elements for key in element.keys if key[0] in ("check", "covered")
    }

    header = [
        f"# Accessibility checklist: {report.url}"
        + (
            f" (reached from {elsewhere})"
            if (elsewhere := from_elsewhere(report.url, meta.requested_url))
            else ""
        ),
        "",
        f"Scanned {meta.scanned_at:%Y-%m-%d %H:%M} UTC with {plugins.edition().display_name} "
        f"{meta.tool_version} "
        f"(axe-core {meta.axe_core_version}) - WCAG {meta.wcag_version} Level {meta.wcag_level} - "
        + (
            tested_text(meta.variants, meta.device, meta.dark_theme)
            .removesuffix(".")
            .replace("Tested", "tested", 1)
            if meta.variants
            else f"{meta.color_scheme or 'default'} color scheme"
            + (f", {meta.screen} screen" if meta.screen else "")
        )
        + f"{_QUICK if meta.quick else ''}.",
        "",
        f"> Automated checks can settle only part of WCAG. All {len(entries)} criteria in scope are covered "
        "below, as checked automatically or as still needing a person, because many depend on judgment "
        "(is the alt text meaningful, does the keyboard order make sense). What concerns particular "
        "elements is listed under each element; the rest is listed by criterion. Tick items off as you "
        "verify them. Links go to the W3C's Understanding pages.",
        "",
        "> **To cover more:** "
        + (
            ""
            if meta.ai_tier == "semantic"
            else "scan again with `--ai semantic` for a second look at alt text, headings and link text; "
        )
        + "scan your other kinds of pages too; and work through the page elements and the checks below "
        "with a keyboard and a screen reader.",
        "",
    ]

    notes = _criterion_notes(report)
    relevant = []
    for e in by_tier("relevant"):
        listed = len(e.examples)
        total = _trigger_count(report, e.num)
        if listed and total <= listed:
            continue  # every element it concerns has its own item under Page elements
        more = (
            f" *{total - listed} more not listed under Page elements; check them the same way.*"
            if listed
            else ""
        )
        relevant.append(
            f"- [ ] {_link(e)} - *Why here:* {e.reason}. *How:* {e.how_to_check}{more}{notes.get(e.num, '')}"
        )
    review = [
        f"- [ ] {_link(e)} - rules: {', '.join(e.rules)}"
        for e in by_status("needs_review")
        if not any(r.details for r in report.needs_review if r.rule_id in e.rules)
    ]
    every = [f"- [ ] {_link(e)} - {e.how_to_check}{notes.get(e.num, '')}" for e in by_tier("every_page")]
    depends = [
        f"- [ ] {_link(e)} - {e.how_to_check} *({e.reason})*{notes.get(e.num, '')}"
        for e in by_tier("depends")
    ]
    elements_link = f"[Page elements](#{anchor(f'Page elements ({len(elements)})')})"
    passed = []
    for e in by_status("passed") + by_status("no_elements"):
        note = "" if e.status == "passed" else " (axe-core found nothing to check here)"
        extra = notes.get(e.num, "")
        if e.follow_up and e.num in checked_per_element:
            passed.append(
                f"- {_link(e)}{note} - passed automated checks, but a person still needs to judge each "
                f"one: see {elements_link}.{extra}"
            )
        elif e.follow_up:
            passed.append(
                f"- [ ] {_link(e)}{note} - passed automated checks. "
                f"*Still worth a look:* {e.follow_up}{extra}"
            )
        else:
            passed.append(f"- [x] {_link(e)}{note} - passed automated checks.{extra}")
    not_applicable = [
        f"- [x] {_link(e)} - untick if the page shows audio or video after you click something."
        for e in by_tier("not_applicable")
    ]
    likely_na = [
        f"- [ ] {_link(e)} - {e.reason}. *If it does apply:* {e.how_to_check}" for e in by_tier("likely_na")
    ]

    sections = [
        _elements_section(elements, report),
        _section("Fix these: not tied to one element", None, unplaced),
        _section("Needs manual review: axe-core could not decide", None, review),
        _section(
            "Check first: relevant to this page",
            "Page features detected on this page make these checks relevant.",
            relevant,
        ),
        _section("Check on every page", None, every),
        _section("Depends on your site or user flows", None, depends),
        _section(
            "Passed automated checks",
            "Ticked items need nothing more; unticked ones have a human follow-up.",
            passed,
        ),
        _section(
            "Not applicable to this page",
            "No audio, video or embedded player (iframe, object, embed) was found on this page, so these "
            "don't apply; they come ticked.",
            not_applicable,
        ),
        _section(
            "Probably not applicable", "No trigger was detected on this page - confirm quickly.", likely_na
        ),
    ]
    present = [section for section in sections if section]
    contents = ["## Contents", ""] + [f"- [{heading}](#{anchor(heading)})" for heading, _ in present] + [""]
    body = contents + [line for _, block in present for line in block]
    text = "\n".join(header + _add_criterion_ids(body)).rstrip()
    return f"{text}\n\n---\n\n{FOOTER.format(product=plugins.edition().display_name)}\n"


# The checklist's last line, under a rule; the review page leaves it out (it has its own footer).
FOOTER = "Accessibility scan by *{product}*: <https://magnacoda.dev/>"


def _elements_section(elements: list[_Element], report: ScanReport) -> tuple[str, list[str]] | None:
    if not elements:
        return None
    heading = f"Page elements ({len(elements)})"
    intro = (
        "Each element that has a problem or something to check, listed once, with everything about it "
        "underneath: **Fix** failed an automated check (tick it when you've fixed it), **Review** is "
        "something axe-core couldn't decide, **Check** needs a person; tick the element's box when you've "
        "looked at its Review and Check items. Elements with exactly the same items are listed together, "
        "each with its own box, and the items once. Elements with the most serious problems come first."
    )
    if report.images_total > len(report.images):
        intro += (
            f" Screenshots show the first {len(report.images)} of the page's {report.images_total} images."
        )
    block = [f"## {heading}", "", intro, ""]
    for number, group in enumerate(_grouped(elements), start=1):
        block += _block(number, group, report.images, report.meta.variants)
    return heading, block


def _trigger_count(report: ScanReport, num: str) -> int:
    """How many elements make a relevant check apply (the page features it is triggered by)."""
    if report.page_features is None:
        return 0
    triggers = load_guidance().get(num, {}).get("triggers", [])
    return sum(getattr(report.page_features, name, 0) for name in triggers)


def carry_ticks(text: str, carried: dict[str, str]) -> tuple[str, int]:
    """Tick items ticked in an earlier scan (`carried`: ID -> date), marked as carried over.

    Returns the text and the number newly ticked.
    """
    if not carried:
        return text, 0
    out, count = [], 0
    for line in text.split("\n"):
        match = ID_MARK.search(line)
        if match and match.group(1) in carried and line.startswith("- [ ] "):
            note = f" *(checked in the scan of {carried[match.group(1)]})*"
            line = (
                "- [x] " + line[len("- [ ] ") : match.start()].rstrip() + note + " " + line[match.start() :]
            )
            count += 1
        out.append(line)
    return "\n".join(out), count


def write_markdown(
    report: ScanReport,
    path: Path,
    images_dir: Path | None = None,
    prefix: str = "",
    carried: dict[str, str] | None = None,
) -> int:
    """Write the checklist and its screenshots, and return how many carried ticks were applied.

    `images_dir` must be inside the checklist's folder (links are relative). Sets each image's `file`.
    """
    if images_dir is not None and any(image.png for image in report.images):
        images_dir.mkdir(parents=True, exist_ok=True)
        for number, image in enumerate(report.images, start=1):
            if image.png:
                target = images_dir / f"{prefix}{number}.png"
                target.write_bytes(image.png)
                image.file = target.relative_to(path.parent).as_posix()
    text, count = carry_ticks(to_markdown(report), carried or {})
    path.write_text(text, encoding="utf-8")
    return count
