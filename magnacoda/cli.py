from __future__ import annotations

import dataclasses
import difflib
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable, Collection, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import IO, Any, NoReturn, TypeVar

import click
from click.core import ParameterSource
from rich.console import Console
from rich.markup import escape
from rich.text import Text

from magnacoda import (
    __version__,
    addresses,
    checklist,
    documents,
    estimate,
    farewell,
    history,
    name_color,
    news,
    plugins,
    preferences,
    progress,
    questions,
    readme,
    recheck,
    review_page,
    review_server,
    saved_reports,
    savedcommand,
    screenreader,
    sections,
    shortcuts,
    teletype,
    ticks,
    tips,
    updater,
    viewer,
    winconsole,
    window,
)
from magnacoda.about import about_text
from magnacoda.browser import redirects, theme
from magnacoda.browser.launcher import DEFAULT_MOBILE_DEVICE
from magnacoda.config import (
    AIConfig,
    AIEngine,
    AITier,
    BrowserName,
    FailOn,
    ScanConfig,
    StabilityConfig,
    WcagVersion,
)
from magnacoda.consent import confirm_ai_usage
from magnacoda.credentials import clear_key, save_key
from magnacoda.exceptions import AIAuthenticationError, MagnacodaError, NavigationError
from magnacoda.findings import merge
from magnacoda.findings.models import SEVERITY_RANK, ScanReport, WcagLevel
from magnacoda.help_sections import pager_options, show_file, show_help, show_pages
from magnacoda.orchestrator import run_dark_pass, run_scan
from magnacoda.pager import browser as user_browser  # the person's own browser, not the scanning one
from magnacoda.pager import formats, markdown
from magnacoda.report.json_export import to_json, write_json
from magnacoda.report.markdown_export import write_markdown
from magnacoda.report.paths import default_report_stem, make_self_ignoring, scans_folder, short
from magnacoda.report.terminal import render_report
from magnacoda.wrapping import wrap_for_stream

T = TypeVar("T")


def _parse_viewport(ctx: click.Context, param: click.Parameter, value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None  # not given: the launcher picks the size (see --screen)
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except ValueError as exc:
        raise click.BadParameter("expected WIDTHxHEIGHT, e.g. 1280x720") from exc


def _parse_kv_pairs(ctx: click.Context, param: click.Parameter, values: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            raise click.BadParameter(f"expected KEY=VALUE, got {item!r}")
        key, val = item.split("=", 1)
        result[key] = val
    return result


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _in_shell(ctx: click.Context | None = None) -> bool:
    """Whether this runs inside the shell (from the current command's context, unless one is given)."""
    ctx = ctx or click.get_current_context(silent=True)
    return ctx is not None and isinstance(ctx.obj, dict) and bool(ctx.obj.get("in_shell"))


def _program(ctx: click.Context | None = None) -> str:
    """What goes before a command in a message: nothing in the shell, "magnacoda " outside it."""
    return "" if _in_shell(ctx) else "magnacoda "


def _address_alone() -> bool:
    """The command was scan and an address, with no options (the wizard and favorites always add some)."""
    ctx = click.get_current_context()
    given = (ctx.get_parameter_source(param.name) for param in ctx.command.params if param.name != "url")
    return all(source in (ParameterSource.DEFAULT, ParameterSource.DEFAULT_MAP, None) for source in given)


winconsole.enable_virtual_terminal()  # before any Rich console is created, so Rich sees the new mode


def _echo(message: str = "", *, err: bool = False) -> None:
    """click.echo, word-wrapped to the terminal."""
    stream = sys.stderr if err else sys.stdout
    text = wrap_for_stream(message, stream)
    if err:
        click.echo(text, err=True)
    else:
        teletype.write(stream, text + "\n")  # typed out in the shell's terminal; at once elsewhere
    questions.printed(message)


_ask = questions.ask
_ask_yes_no = questions.ask_yes_no


def _require_nonempty(value: str) -> str:
    value = value.strip()
    if not value:
        raise click.UsageError("A value is required.")
    return value


def _prompt_nonempty(text: str, default: str | None = None) -> str:
    # click.prompt() re-asks on a bare Enter by itself; this catches whitespace-only input.
    return _ask(text, default=default, value_proc=_require_nonempty)  # type: ignore[no-any-return]


def _help_callback(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    show_help(ctx)
    ctx.exit()


_ARGS_KEY = "magnacoda.scan_args"
_ESTIMATED = "magnacoda.estimated"  # the scan's estimate step ran (a scan started again skips it)
_PICKER_RECENT = 10  # how many recent scans the wizard's start-up picker offers


def _record_history(typed_url: str | None = None, url: str | None = None) -> None:
    """Add the scan to history.md (redacted), with the full URL instead of what was typed."""
    args = click.get_current_context().meta.get(_ARGS_KEY)
    if args:
        args = list(args)
        if typed_url and url and typed_url in args:
            args[args.index(typed_url)] = url
        history.record(shlex.join(savedcommand.redact(args)))


def _new_scan_page() -> None:
    """A fresh page for `scan` typed at the shell's prompt, once; not when the wizard or a favorite
    runs one, which would push what was just confirmed out of view."""
    ctx = click.get_current_context()
    line = ctx.obj.get("line", "") if isinstance(ctx.obj, dict) else ""
    if line.lower().split()[:1] == ["scan"] and not ctx.meta.get("magnacoda.scan_page"):
        ctx.meta["magnacoda.scan_page"] = True
        sections.new_page(ctx, "scan")


def _ask_address() -> str:
    """`scan` without an address: ask for one (help shows the scan section), or the usual error
    without a person there."""
    if not _is_interactive():
        raise click.UsageError("Missing argument 'URL'.")
    ctx = click.get_current_context()

    def check(value: str) -> str:
        if not value.strip():
            raise click.Abort  # q cancels too, as at any question
        return value.strip()

    while True:
        typed = _ask(
            "Page to scan (such as example.com), help for more, or press Enter to cancel",
            default="",
            show_default=False,
            value_proc=check,
        )
        if typed.lower() != "help":
            break
        ctx.invoke(help_cmd, words=("scan",))
    args = ctx.meta.get(_ARGS_KEY)
    if args is not None:
        ctx.meta[_ARGS_KEY] = [*args, typed]  # for history.md
    return typed


def _address_for(typed: str) -> addresses.Address:
    """Full URL for what was typed, mentioning any scheme that was added. Unknown words are usage errors."""
    file = Path(typed).expanduser()
    if "://" not in typed and file.is_file():
        # README.md or notes.txt would otherwise be scanned as a website (.md is Moldova's domain).
        program = _program()
        raise click.UsageError(
            f"{typed} is a file on this computer. To read it, type {program}view {typed}. To scan it as a "
            f"web page, type {program}scan {file.resolve().as_uri()}, or to scan a website by that name, "
            f"type {program}scan https://{typed}."
        )
    try:
        address = addresses.interpret(typed)
    except addresses.NotAnAddress:
        if not typed.strip():
            raise click.UsageError("Give the address of the page to scan, such as example.com.") from None
        if typed.strip().replace(".", "").isdigit():
            raise click.UsageError(
                f"'{typed}' isn't a web address. To run a favorite, pick it at the start of the wizard, or "
                "type its command (fav lists them)."
            ) from None
        raise click.UsageError(
            f"No website or computer named '{typed}' was found. To scan a site by that name anyway, type "
            f"its full address, such as http://{typed}."
        ) from None
    if address.added:
        _echo(f"Scanning {address.url}", err=True)  # stderr: never mixed into JSON on stdout
    return address


_NO_ADDONS_FLAG = "--no-addons"


def _take_no_addons_flag(ctx: click.Context, args: list[str]) -> list[str]:
    """--no-addons, before the command and only at startup. Not a Click option, so it stays out of
    help and history."""
    leading = 0
    while leading < len(args) and args[leading].startswith("-"):
        leading += 1
    if _NO_ADDONS_FLAG not in args[:leading]:
        return args
    if _in_shell(ctx):
        _echo(f"{_NO_ADDONS_FLAG} only works when starting magnacoda, not inside the shell.")
    else:
        os.environ[plugins.ENV_OFF_SWITCH] = "off"
        plugins.reset()
    return [arg for index, arg in enumerate(args) if not (index < leading and arg == _NO_ADDONS_FLAG)]


def _not_a_command(ctx: click.Context, word: str, commands: Collection[str]) -> str:
    """What to type instead of a first word that isn't a command (an address, a file, a typo)."""
    program = _program(ctx)
    if word.startswith("-"):
        return (
            f"{word} is an option, so it goes after a command and its address: "
            f"{program}scan ADDRESS {word} ..."
        )
    if "://" not in word and Path(word).expanduser().is_file():
        return (
            f"{word} isn't a command. To read the file, type {program}view {word}; to scan a website by "
            f"that name, type {program}scan {word}."
        )
    if word.replace(".", "").isdigit():
        return (
            f"{word} isn't a command. To run a favorite, pick it at the start of the wizard, or type its "
            "command (fav lists them)."
        )
    if "." in word or ":" in word or word.lower().startswith("localhost"):
        stem = Path(word).stem  # LICENSE.md typed, LICENSE here
        nearby = (
            f" There's a file named {stem} here: to read it, type {program}view {stem}."
            if "/" not in word and stem != word and Path(stem).is_file()
            else ""
        )
        return f"{word} isn't a command. To scan it, type {program}scan {word}.{nearby}"
    close = difflib.get_close_matches(word.lower(), commands, n=1)
    guess = f"Did you mean {close[0]}? " if close else ""
    return (
        f"{word} isn't a magnacoda command. {guess}To see the commands, type {program}help; to scan a "
        f"site by that name, type {program}scan {word}."
    )


class _ScanCommand(click.Command):
    """The scan command, which keeps its words however it was started (typed, the wizard, a favorite),
    for history.md (see _record_history) and for running again with faster settings."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        ctx.meta[_ARGS_KEY] = ["scan", *args]
        return super().parse_args(ctx, args)


class _DefaultGroup(click.Group):
    """Commands ignore case; a first word that isn't a command gets a message saying what to type."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        args = _take_no_addons_flag(ctx, args)
        # Derived from self.params (not a hardcoded list) so any future top-level group option
        # is automatically exempt from the reroute too, not just --help/--version.
        plugins.add_commands(self)  # add-ons' commands, once (see plugins.py)
        own_opts = {"--help", "--version"}
        for param in self.params:
            own_opts.update(getattr(param, "opts", []))
        if args and args[0].lower() in self.commands:
            args = [args[0].lower(), *args[1:]]  # command words ignore case; URLs and flags keep theirs
        if args and args[0] not in self.commands and args[0] not in own_opts:
            raise _CleanUsageError(_not_a_command(ctx, args[0], self.commands))
        if args and args[0] in self.commands and "--help" in args[1:]:
            raise click.UsageError(
                f"Commands have no --help of their own. For help, type `{_program(ctx)}help`."
            )
        return super().parse_args(ctx, args)

    def invoke(self, ctx: click.Context) -> Any:
        """Usage errors as one clean line; unknown options point to where the options are listed."""
        try:
            return super().invoke(ctx)
        except (KeyboardInterrupt, click.Abort):
            if _in_shell(ctx):
                raise  # the shell says Cancelled and comes back to its prompt
            _echo("\nCancelled.", err=True)  # instead of Click's "Aborted!"
            sys.exit(130)  # the usual exit code for Ctrl+C
        except click.NoSuchOption as exc:
            command = exc.ctx.command.name if exc.ctx and exc.ctx.command.name else "magnacoda"
            where = f"{_program(ctx)}help"
            raise _CleanUsageError(
                f"{command} has no option {exc.option_name}. To see its options, type {where} "
                f"(the {command} section)."
            ) from None
        except click.UsageError as exc:
            raise _CleanUsageError(exc.format_message()) from None
        except _CleanError:
            raise
        except click.ClickException as exc:  # a command's own error, add-ons' included: wrapped too (exit 1)
            raise _CleanError(exc.format_message()) from None


class _CleanError(click.ClickException):
    """An error shown as "Error: ...", word-wrapped to the terminal (Click's own isn't wrapped)."""

    def show(self, file: IO[Any] | None = None) -> None:
        stream = file if file is not None else sys.stderr
        click.echo(wrap_for_stream(f"Error: {self.format_message()}", stream), file=stream)


class _CleanUsageError(_CleanError):
    """A usage error shown as "Error: ..." alone; exit code 2, as for Click's own usage errors."""

    exit_code = 2


# help_option_names=[]: no command gets Click's own --help (`scan --help` and so on); child contexts
# inherit it, add-on commands included. The one help is `help` / `magnacoda --help` (help_sections.py).
@click.group(
    cls=_DefaultGroup,
    invoke_without_command=True,
    add_help_option=False,
    context_settings={"help_option_names": []},
)
@click.version_option(__version__, prog_name="magnacoda", help="Show the version number.")
@click.option(
    "--help",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=_help_callback,
    help="Show the help, the same as the help command.",
)
@click.option(
    "--force-setup-notice",
    is_flag=True,
    default=False,
    help="When this launches the shell (no subcommand given), always show the Chromium setup notice.",
)
@click.pass_context
def main(ctx: click.Context, force_setup_notice: bool) -> None:
    """WCAG 2 accessibility scanner: axe-core + Playwright, with optional tiered Claude reasoning.

    Run with no arguments to start an interactive shell, or `magnacoda scan URL [OPTIONS]` directly.

    The AI tiers need your own Anthropic API key (`magnacoda setup` can save one for you), or Claude
    Code installed and logged in to your Claude subscription.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(shell, force_setup_notice=force_setup_notice)


# The about screen is longer than other typed text; it types in bigger chunks in the same time.
_ABOUT_TYPED_CHARS = 1500


@main.command(name="about")
@click.pass_context
def about_cmd(ctx: click.Context) -> None:
    """Show the author, links, version and license."""
    text = Text(wrap_for_stream(about_text(), sys.stdout))
    # The product name in italics, as in the banner: in the title, and where the disclaimer starts.
    text.stylize("italic", 1, 1 + len(plugins.edition().display_name))
    text.highlight_regex(r"(?m)^magnacoda(?= is an independent project)", "italic")
    if sections.new_page(ctx, "about"):
        text = text[1:]  # its opening blank line: the heading already ends with one
    teletype.say(Console(), text, max_chars=_ABOUT_TYPED_CHARS)  # typed like the banner above it


@main.command(name="help")
@click.argument("words", nargs=-1)
@click.pass_context
def help_cmd(ctx: click.Context, words: tuple[str, ...]) -> None:
    """Browse all of the help, one screen at a time."""
    if [word.lower() for word in words] in (["readme"], ["readme.md"]):
        ctx.invoke(readme_cmd)  # what people try first to read the README
        return
    if [word.lower() for word in words] == ["docs"]:
        ctx.invoke(docs_cmd)
        return
    show_help(ctx, " ".join(words) or None)


@main.command(name="view")
@click.argument("file")
@click.argument("section", nargs=-1)
@click.pass_context
def view_cmd(ctx: click.Context, file: str, section: tuple[str, ...] = ()) -> None:
    """Show a Markdown or text file in the same pager as help (see viewer.py), from the start or
    at the section named after it."""
    # A file's sections are new to the reader (a license may start on a one-line page): start on the
    # g list.
    try:
        show_file(ctx, file, Path(file).name, " ".join(section) or None, start="section_list")
    except viewer.CannotView as exc:
        raise click.ClickException(str(exc)) from None


@main.command(name="review")
@click.argument("folder", required=False)
@click.option(
    "--no-browser",
    "no_browser",
    is_flag=True,
    default=False,
    help="Show it in the help viewer, not in the browser.",
)
@click.pass_context
def review_cmd(ctx: click.Context, folder: str | None, no_browser: bool) -> None:
    """List the scans saved in the scans folder (or FOLDER), newest first, and review one: in the browser,
    with its pictures and boxes to tick (review_server.py), or in the help viewer when there's no
    browser, the scan was saved before items had IDs, or --no-browser is given. Then the list again, so
    another can be reviewed, until Enter (or q) cancels."""
    folder = folder or str(scans_folder())
    just_scanned = _just_scanned(ctx, folder)
    if just_scanned is not None:
        _review_one(ctx, just_scanned, no_browser)  # on the same page, under the scan; then the prompt
        return
    sections.new_page(ctx, "review")
    first = True
    while True:
        if not first:
            _echo()
        # The list once; after a review, only the question (the list is still just above).
        scan = _pick_saved_scan(folder, "review", enter="cancel", show_list=first)
        if scan is None:
            return  # nothing to review: it said so (q or Enter at the list cancels, as at any question)
        first = False
        _review_one(ctx, scan, no_browser)


def _just_scanned(ctx: click.Context, folder: str) -> saved_reports.SavedScan | None:
    """In the shell, the scan the previous command finished, if it's in `folder`."""
    scanned = ctx.obj.get("scanned_before") if isinstance(ctx.obj, dict) else None
    if scanned is None:
        return None
    wanted = Path(scanned).resolve()
    found = saved_reports.scans(Path(folder).expanduser())
    return next((s for s in found if s.folder is not None and s.folder.resolve() == wanted), None)


def _review_one(ctx: click.Context, scan: saved_reports.SavedScan, no_browser: bool) -> None:
    """One scan: in the browser, or in the help viewer (one variant, picked if there are several)."""
    if not no_browser and _review_in_browser(scan):
        return
    report = scan.reports[0]
    if len(scan.reports) > 1:
        for number, variant in enumerate(scan.reports, start=1):
            _echo(f"  {number}. {variant.label}")
        which = _pick_number("Which one? Type its number", len(scan.reports))
        if which is None:
            return
        report = scan.reports[which]
    ctx.invoke(view_cmd, file=str(report.path))


def _pick_saved_scan(
    folder: str, verb: str, enter: str = "back", show_list: bool = True
) -> saved_reports.SavedScan | None:
    """List the saved scans in `folder`, newest first, and let the person pick one (None: none, or
    Enter). Without `show_list`, only the question, for another one from the list already shown."""
    found = saved_reports.scans(Path(folder).expanduser())
    if not found:
        _echo(
            f"No saved scans in {short(Path(folder).expanduser())}. Every scan is saved there: run the "
            "wizard, or scan a page, to make your first one."
        )
        return None
    if show_list:
        with teletype.listing():
            # The question below says how to cancel.
            _echo(f"Saved scans in {short(Path(folder).expanduser())}, newest first.")
            for number, scan in enumerate(found, start=1):
                _echo(f"  {number:>2}. {scan.line()}")
    which = "that scan" if show_list else "another scan"
    index = _pick_number(f"Type a number to {verb} {which}", len(found), enter)
    return None if index is None else found[index]


def _variants_of(scan: saved_reports.SavedScan) -> list[review_page.Variant]:
    """Each variant's checklist and results file."""
    return [
        review_page.Variant(
            label=scan.variant_label(report),
            checklist=report.path,
            results=report.path.with_name(
                "results" + report.path.name[len("checklist") : -len(".md")] + ".json"
            ),
        )
        for report in scan.reports
    ]


@main.command(name="recheck")
@click.argument("folder", required=False)
@click.option("--cookie", "cookies", multiple=True, help="A login cookie, NAME=VALUE (never saved).")
@click.option(
    "--extra-http-header", "extra_http_headers", multiple=True, callback=_parse_kv_pairs,
    help="A header to send, NAME=VALUE (never saved).",
)  # fmt: skip
@click.option(
    "--storage-state",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="A saved login file. By default, the one the scan used, if it used one.",
)
@click.pass_context
def recheck_cmd(
    ctx: click.Context,
    folder: str | None,
    cookies: tuple[str, ...],
    extra_http_headers: dict[str, str],
    storage_state: Path | None,
) -> None:
    """Pick a saved scan and test its Fix items again, in seconds: confirmed fixes are ticked, failures
    still there unticked, in the saved checklist itself (recheck.py). Behind a login, it uses the saved
    login file the scan used, or the cookies, headers or login file given here."""
    parsed_cookies = []
    for item in cookies:
        if "=" not in item:
            raise click.BadParameter(f"expected NAME=VALUE, got {item!r}", param_hint="--cookie")
        name, value = item.split("=", 1)
        parsed_cookies.append((name, value))
    login = recheck.Login(parsed_cookies, dict(extra_http_headers or {}), storage_state)
    scan = _pick_saved_scan(folder or str(scans_folder()), "recheck", enter="cancel")
    if scan is None:
        return
    if scan.folder is None or not all(ticks.has_ids(r.path) for r in scan.reports):
        _echo("That scan was saved by an older magnacoda and can't be rechecked: scan the page again.")
        return
    variants = _variants_of(scan)
    with _scan_progress(scan.site, verb="Rechecking") as next_pass:
        result = recheck.recheck_scan(
            variants, on_variant=lambda n, total, label: next_pass(n, total, label or None), login=login
        )
    for variant in result.variants:
        name = f"{variant.label.replace('.', ', ')}: " if variant.label else ""
        if variant.error:
            _echo(f"{name}couldn't recheck: {variant.error}", err=True)
    _echo(f"\nRechecked {scan.site}: {result.summary()}.")
    _echo(
        "A recheck only tests the problems that were found; scan the page again before release, to catch "
        "anything new. Review and Check items still need a person."
    )
    if user_browser.browser_available() and _is_interactive():
        if _ask_yes_no("Open it in your browser now?", default=True):
            _review_in_browser(scan)
    else:
        command = "review" if isinstance(ctx.obj, dict) else "magnacoda review"
        bold = click.style(command, bold=True) if sys.stdout.isatty() else command
        _echo(f"Type {bold} to see it.")


def _review_in_browser(scan: saved_reports.SavedScan) -> bool:
    """Open the review page until Done or Ctrl+C. False if there's no browser, no item IDs, or no server."""
    if scan.folder is None or not all(ticks.has_ids(r.path) for r in scan.reports):
        return False
    if not user_browser.browser_available():
        return False
    variants = _variants_of(scan)
    try:
        server = review_server.ReviewServer(scan.folder, variants)
    except OSError:
        return False
    server.start()
    user_browser.open_in_browser(server.url, preferences.load().review_window)
    _echo("Showing the scan in your browser. Press its Done button when you've finished, or Ctrl+C here.")
    stopped_by_ctrl_c = server.wait()
    _echo(("\n" if stopped_by_ctrl_c else "") + "Stopped showing the scan.")  # off the line the ^C is on
    return True


@main.command(name="readme")
@click.argument("words", nargs=-1)
@click.pass_context
def readme_cmd(ctx: click.Context, words: tuple[str, ...] = ()) -> None:
    """Read the README, one section at a time, in the same pager as help, or from the section named
    after it. With a file name first, show that file instead (the same as view FILE)."""
    if words and Path(words[0]).expanduser().is_file():
        ctx.invoke(view_cmd, file=words[0], section=words[1:])
        return
    missing = f"no README. You can read it at {readme.REPOSITORY}"
    _show_document(ctx, readme.readme_text(), "README", missing, words, "README.md")


@main.command(name="docs")
@click.argument("words", nargs=-1)
@click.pass_context
def docs_cmd(ctx: click.Context, words: tuple[str, ...] = ()) -> None:
    """Read the manual, one section at a time, in the same pager as help, or from the section named
    after it."""
    missing = f"no manual. You can read it at {readme.REPOSITORY}/blob/main/docs/manual.md"
    _show_document(ctx, readme.manual_text(), "Manual", missing, words, "manual.md")


@main.command(name="manual", hidden=True)
@click.argument("words", nargs=-1)
@click.pass_context
def manual_cmd(ctx: click.Context, words: tuple[str, ...] = ()) -> None:
    """Another name for docs."""
    ctx.invoke(docs_cmd, words=words)


def _show_document(
    ctx: click.Context, text: str | None, title: str, missing: str, words: tuple[str, ...], packaged: str
) -> None:
    if text is None:
        raise click.ClickException(f"This copy of magnacoda has {missing}")
    options = pager_options(title, document_title="drop")  # the title bar names it already
    document = markdown.parse(text, options)
    show_pages(
        ctx,
        document.sections,
        options,
        format=formats.MARKDOWN,
        title=document.title,
        section=" ".join(words) or None,
        outline=document.outline,
        document=documents.locate(packaged),
    )


def _chromium_already_installed() -> bool:
    """Accurate but slow (~1-2 s, starts Playwright's driver), so only for `setup`."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).exists()
    except Exception:
        # Can't tell either way (e.g. the bundled driver failed to start) - fall through and
        # let the real installer figure it out; it's a no-op if already present.
        return False


def _playwright_browsers_dir() -> Path:
    """Playwright's browser cache folder, as computed in the driver's coreBundle.js
    (PLAYWRIGHT_BROWSERS_PATH, XDG_CACHE_HOME on Linux)."""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ms-playwright"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "ms-playwright"


def _chromium_probably_installed() -> bool:
    """Quick filesystem guess for the banner (~1 ms); `setup` and the launch error are authoritative."""
    try:
        return any(_playwright_browsers_dir().glob("chromium-*"))
    except OSError:
        return False


# Shown by both shell() and wizard().
_NOTICE_INDENT = 4


def _print_notice(console: Console, markup: str, max_width: int | None = None) -> None:
    """An indented notice under the banner: bold label, the rest in the terminal's own color."""
    text = Text.from_markup(markup)
    width = min(console.width, max_width) if max_width else console.width
    for line in text.wrap(console, max(width - _NOTICE_INDENT, 20)):
        line.rstrip()  # no trailing spaces, which would end up in anything copied from the terminal
        teletype.say(console, Text(" " * _NOTICE_INDENT) + line)
    console.print()


_CHROMIUM_NOTICE = (
    "[bold]Chromium isn't installed yet[/bold] - run setup first. magnacoda renders "
    "each page in a real Chromium browser (so it sees JS-rendered content, not just the initial "
    "HTML), and that browser isn't bundled with the install."
)


def _prompt_and_save_key(api_key_env: str) -> str | None:
    """Ask for a key (hidden input) and save it. Returns the key, or None."""
    key = _ask(
        f"Paste your Anthropic API key (for ${api_key_env})",
        hide_input=True,
        default="",
        show_default=False,
    ).strip()
    if not key:
        _echo("No key entered - nothing saved.")
        return None
    path = save_key(api_key_env, key)
    _echo(f"Saved to {path} (readable only by you).")
    return key


_ENGINE_ALIASES: dict[str, AIEngine] = {"api-key": "api", "claude-plan": "claude-code"}


def _ask_about_claude_plan(default: bool = True) -> bool:
    """Ask whether AI may use the Claude plan and save the answer. Returns it."""
    use_plan = _ask_yes_no(
        "Use your Claude plan for the AI tiers?",
        intro="Claude Code is installed, so the AI tiers can use your Claude plan (such as Pro or Max) "
        "instead of an Anthropic API key, which the API bills per use.",
        default=default,
    )
    try:
        preferences.set_ai_engine("claude-code" if use_plan else "api")
        _echo("Saved in preferences.ini. Run setup to change it.")
    except OSError as exc:
        _echo(
            f"Could not save the choice in preferences.ini ({exc.strerror or exc}); it applies to this scan."
        )
    return use_plan


def _report_anthropic_key_status(api_key_env: str = "ANTHROPIC_API_KEY") -> None:
    """setup's AI step: ask about the Claude plan if Claude Code is there, say how AI will run, and
    offer to save a key only if one would be used."""
    from magnacoda.credentials import credentials_path, load_stored_key

    claude_code = shutil.which("claude") is not None
    interactive = _is_interactive()
    has_key = bool(os.environ.get(api_key_env) or load_stored_key(api_key_env))
    _echo("AI tiers (optional; magnacoda works fine without them):")
    choice = preferences.load().ai_engine
    if claude_code and interactive:
        choice = "claude-code" if _ask_about_claude_plan(default=choice != "api") else "api"
    if claude_code and choice == "claude-code":
        _echo(
            "Ready, with your Claude plan, through Claude Code. You don't need an API key. If a scan "
            "says Claude Code isn't logged in: in a normal terminal window (not the magnacoda shell), "
            "type claude to start Claude Code, then type /login there and follow the steps."
        )
        if has_key:
            _echo("Your Anthropic API key isn't used while your Claude plan is chosen.")
        return
    if claude_code and choice == "ask":
        _echo(
            "Claude Code is installed, but you haven't chosen whether the AI tiers may use your Claude "
            "plan. Run setup in a terminal to choose; the first AI scan asks too."
        )
    if has_key:
        where = (
            f"from ${api_key_env}"
            if os.environ.get(api_key_env)
            else f"saved in {credentials_path()}; `setup --forget-key` removes it"
        )
        _echo(f"Ready, with your Anthropic API key ({where}). The API bills each use.")
        return
    if claude_code:
        explanation = "No Anthropic API key is saved yet. The API bills each use."
    else:
        explanation = (
            "Not set up yet. To use them, either:\n"
            "- use your Claude plan (such as Pro or Max): install Claude Code from "
            "https://claude.com/claude-code, then log in once: in a normal terminal window (not the "
            "magnacoda shell), type claude to start Claude Code, then type /login there; or\n"
            "- use an Anthropic API key, which the API bills per use."
        )
    # The explanation sits right above the question it explains (see questions.py).
    if interactive:
        if _ask_yes_no("Save an API key now?", intro=explanation, default=False):
            _prompt_and_save_key(api_key_env)
            return
    else:
        _echo(explanation)
        _echo()
    _echo("No key saved. To add one later, either:")
    _echo()
    _echo('  1. Run setup again and answer y to "Save an API key now?" - it saves the key for you.')
    _echo()
    if sys.platform == "win32":
        _echo(
            "  2. Set it yourself. Create a key at platform.claude.com/settings/keys, then run:\n"
            f"       setx {api_key_env} sk-ant-...\n"
            "     and open a new terminal window, where it is set from then on."
        )
    else:
        _echo(
            "  2. Set it yourself. Create a key at platform.claude.com/settings/keys, then run:\n"
            f"       export {api_key_env}=sk-ant-...\n"
            "     That only lasts for this terminal. To make it permanent, add that same line to your "
            "shell's startup file (e.g. ~/.bashrc for bash), then open a new terminal (or run: "
            "source ~/.bashrc)."
        )


@main.command()
@click.option("-y", "--yes", is_flag=True, default=False, help="Skip the download confirmation.")
@click.option(
    "--forget-key",
    "forget_key",
    is_flag=True,
    default=False,
    help="Delete the saved Anthropic API key, if any (skips the Chromium check).",
)
def setup(yes: bool, forget_key: bool) -> None:
    """Install the Playwright Chromium browser binary and show how the AI tiers will run."""
    if forget_key:
        if clear_key("ANTHROPIC_API_KEY"):
            _echo("Removed the saved Anthropic API key.")
        else:
            _echo("No saved Anthropic API key to remove.")
        return

    sections.new_page(click.get_current_context(), "setup")
    if _is_interactive() and not yes:
        _echo(questions.CANCEL_HINT)  # setup may ask: install Chromium, an API key, the Claude plan
    first_time = not _chromium_already_installed()
    if not first_time:
        _echo("Chromium is already installed.")
    else:
        missing = "Chromium is not installed yet - this is a one-time download of about 100 MB."
        if yes:
            _echo(missing)
        else:
            if not _is_interactive():
                _echo(missing)
                raise click.UsageError("Re-run with --yes to install non-interactively.")
            if not _ask_yes_no("Download and install it now?", intro=missing, default=True):
                _echo("Cancelled - Chromium was not installed.")
                sys.exit(1)

        status = _install_chromium()
        if status:
            sys.exit(status)

    if _is_interactive() and not yes:
        _ask_about_shortcuts()
    _echo()
    _report_anthropic_key_status()
    # The wizard then finds Chromium installed, so it doesn't offer setup back.
    if first_time and _is_interactive() and not yes:
        _echo()
        if _ask_yes_no("Scan your first page with the wizard now?", default=True):
            click.get_current_context().invoke(wizard, force_setup_notice=False)


def _offer_chromium() -> bool:
    """Only Chromium: all of setup would offer the wizard again."""
    if not _is_interactive():
        return False
    intro = (
        "Chromium, the browser magnacoda scans with, isn't installed yet. "
        "It's a one-time download of about 100 MB."
    )
    return _ask_yes_no("Download it now?", intro=intro, default=True) and _install_chromium() == 0


def _install_chromium() -> int:
    _echo("Installing Chromium for Playwright...")
    result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
    if result.returncode != 0:
        _echo("Installation failed - see the output above.", err=True)
        return result.returncode
    _echo("Chromium is installed.")
    return 0


_SHORTCUT_PLACES = {"menu": (True, False), "desktop": (False, True), "both": (True, True)}


def _ask_about_shortcuts() -> None:
    """Offer what's missing, or to remove what's there."""
    where = shortcuts.places()
    menu_name = shortcuts.menu_name()
    has = {"menu": where.menu.exists(), "desktop": where.desktop.exists()}
    if not any(has.values()):
        answer = _ask(
            "Add a magnacoda shortcut to",
            intro=f"A shortcut opens magnacoda in a terminal window, from your {menu_name} or desktop.",
            type=click.Choice([*_SHORTCUT_PLACES, "skip"], case_sensitive=False),
            default="skip",
        )
        if answer.lower() != "skip":
            _add_shortcut(answer.lower())
    elif all(has.values()):
        if _ask_yes_no(
            "Remove them?", intro=f"You have magnacoda shortcuts in your {menu_name} and on your desktop."
        ):
            _remove_shortcuts()
    else:
        missing = "desktop" if has["menu"] else "menu"
        here, other = ("in your " + menu_name, "desktop") if has["menu"] else ("on your desktop", menu_name)
        answer = _ask(
            f"Add one to your {other} too, or remove it?",
            intro=f"You have a magnacoda shortcut {here}.",
            type=click.Choice([missing, "remove", "keep"], case_sensitive=False),
            default="keep",
        )
        if answer.lower() == "remove":
            _remove_shortcuts()
        elif answer.lower() == missing:
            _add_shortcut(missing)


def _add_shortcut(where: str) -> None:
    menu, desktop = _SHORTCUT_PLACES[where]
    try:
        shortcuts.add(menu=menu, desktop=desktop)
    except shortcuts.ShortcutError as error:
        _echo(str(error), err=True)
        sys.exit(1)
    places = " and ".join(
        ([f"your {shortcuts.menu_name()}"] if menu else []) + (["your desktop"] if desktop else [])
    )
    them = "them" if len(shortcuts.existing()) > 1 else "it"
    _echo(f"Added magnacoda to {places}. To take {them} away, type `{_program()}shortcut remove`.")
    if sys.platform == "win32" and menu:
        _echo(f"{shortcuts.WINDOWS_KEY} opens it too.")
    elif sys.platform == "darwin" and menu:
        _echo('The first time, macOS asks whether magnacoda may control Terminal: choose "OK".')


def _remove_shortcuts() -> bool:
    gone = shortcuts.remove()
    if gone:
        _echo("Removed the shortcuts." if len(gone) > 1 else "Removed the shortcut.")
    return bool(gone)


@main.command(name="shortcut")
@click.argument(
    "what", required=False, type=click.Choice([*_SHORTCUT_PLACES, "remove"], case_sensitive=False)
)
def shortcut_cmd(what: str | None) -> None:
    """Add a shortcut that opens magnacoda in a terminal window, or take it away."""
    if what is None:
        if _is_interactive():
            _ask_about_shortcuts()
        else:
            _add_shortcut("menu")
    elif what.lower() == "remove":
        if not _remove_shortcuts():
            _echo("There's no shortcut to remove.")
    else:
        _add_shortcut(what.lower())


@main.command(name="screenreader")
@click.argument("mode", required=False, type=click.Choice(["on", "off"], case_sensitive=False))
def screenreader_cmd(mode: str | None) -> None:
    """Turn typed-out text, the spinner and paging off for a screen reader (on), or back on (off)."""
    if mode is None:
        on = screenreader.settings_on()
        if not on:
            _echo(
                "Screen reader settings are on: typing, the spinner and paging are off. "
                "To turn them back on, type screenreader off."
            )
        elif len(on) == 3:
            _echo(
                "Screen reader settings are off: typing, the spinner and paging are on. "
                "To turn them off, type screenreader on."
            )
        else:
            names = {"typing": "typing", "spinner": "the spinner", "paging": "paging"}
            _echo(f"Still on: {', '.join(names[key] for key in on)}. To turn them off, type screenreader on.")
        return
    reader = mode.lower() == "on"
    try:
        screenreader.set_mode(reader)
    except OSError as exc:
        raise click.ClickException(f"Couldn't change {preferences.preferences_path()}: {exc}.") from exc
    if reader:
        _echo("Typed-out text, the spinner and paging are off. To turn them back on, type screenreader off.")
    else:
        _echo("Typed-out text, the spinner and paging are on. To turn them off, type screenreader on.")


# Words are in the terminal's normal color (dim gray can be too faint to read, especially on Windows);
# only decoration, such as the dots between commands, is dim.
_SEPARATOR = " [dim]·[/dim] "  # narrow, so the banner's commands fit in 80 columns
_BANNER_ADDON_COMMANDS = 5  # more than this and the line points to `about` for the rest


def _command_words(names: list[str], current: str | None) -> str:
    """Commands for the banner, `·` between them; the current section's word bold and underlined."""
    return _SEPARATOR.join(
        f"[bold underline]{escape(name)}[/bold underline]" if name == current else escape(name)
        for name in names
    )


def _addon_commands_line(current: str | None = None) -> str:
    """The banner's third line, listing commands that add-ons added, or "" when there are none."""
    plugins.add_commands(main)  # normally done already while parsing; repeating it is harmless
    names = [name for added in plugins.added_commands().values() for name in added]
    if not names:
        return ""
    shown = _command_words(names[:_BANNER_ADDON_COMMANDS], current)
    if len(names) > _BANNER_ADDON_COMMANDS:
        shown += _SEPARATOR + "… (all in about)"
    return f"[bold]Add-on commands:[/bold] {shown}\n"


@main.command(name="news")
@click.pass_context
def news_cmd(ctx: click.Context) -> None:
    """Updates, what's new in this version, and news about magnacoda."""
    if news.allowed():
        news.refresh()  # at most once a day; quick, and silent when it can't connect
    sections = news.sections()
    news.mark_all_seen()
    if not sections:
        _echo("Nothing new to show.")
        return
    show_pages(ctx, sections, pager_options("News"))


def _leave_the_session(ctx: click.Context) -> None:
    """After an update the old code is still loaded, so the shell has to exit."""
    if isinstance(ctx.obj, dict):
        ctx.obj["leave"] = True


@main.command(name="update")
@click.option("-y", "--yes", is_flag=True, default=False, help="Update without asking.")
@click.option(
    "--use-saved",
    is_flag=True,
    hidden=True,
    help="Skip the fresh check and use the last saved one (news-state.json), for testing the update "
    "steps before a newer version exists on PyPI.",
)
@click.pass_context
def update_cmd(ctx: click.Context, yes: bool, use_saved: bool) -> None:
    """Update magnacoda, and add-ons published on PyPI, to their latest versions."""
    sections.new_page(ctx, "update")
    kind = updater.install_kind()
    if kind == updater.DEV:
        _echo(updater.plan(["magnacoda"], kind).note)
        return
    if not use_saved:
        _echo("Checking for updates...")
        news.refresh(force=True)  # asked for, so it checks even when the daily checks are off
    found = news.updates()
    if not found:
        if "magnacoda" in news.load_state().latest:
            _echo(f"You have the latest version ({__version__}).")
        else:
            _echo(
                "Couldn't check for updates just now (no connection, or PyPI didn't answer). "
                "Nothing was changed."
            )
        return
    for item in found:
        _echo(f"  {item.name} {item.installed} -> {item.latest}")
    steps = updater.plan([item.name for item in found], kind)
    if steps.kind == updater.SHOW:
        _echo("\n" + steps.note)
        for command in steps.commands:
            _echo("  " + updater.shown(command))
        return
    _echo("\nThis will run:")
    for command in steps.commands:
        _echo("  " + updater.shown(command))
    if not yes and not _ask_yes_no("Update now?", default=True):
        _echo("Nothing was changed.")
        return
    repair = updater.repair_command(steps.kind, steps.commands)
    if os.name == "nt":  # pragma: no cover - checked by hand on Windows
        others = updater.others_running()
        if others:
            where = "another window or tab" if others == 1 else f"{others} other windows or tabs"
            _echo(
                f"magnacoda is also running in {where}. Type exit at each magnacoda prompt: the update "
                "waits until magnacoda has stopped everywhere, because a copy still running keeps its "
                "files locked."
            )
        if not updater.start_in_new_window(steps.commands, repair):
            _echo(
                "Couldn't open a new window for the update. Quit magnacoda, then run the commands above.",
                err=True,
            )
            return
        _echo(
            "The update opens in a new window and starts once magnacoda has stopped everywhere. "
            "Closing magnacoda here now."
        )
        _leave_the_session(ctx)
        return
    log = updater.log_path()
    _echo("\nUpdating... (this can take a minute)")
    if updater.run(steps.commands, log):
        _echo("Updated. Start magnacoda again to use the new version.")
        _leave_the_session(ctx)
    else:
        last = "\n".join(f"  {line}" for line in updater.tail(log))
        _echo(
            f"The update didn't finish. The last lines of its log:\n{last}\nThe whole log is in {log}",
            err=True,
        )
        _echo(
            "\nIf magnacoda no longer starts, repair it with:\n"
            + "\n".join(f"  {line}" for line in repair.splitlines()),
            err=True,
        )
        sys.exit(1)


_SHELL_EXIT_WORDS = ("exit", "quit", "q")
_SHELL_CLEAR_WORDS = ("clear", "cls")
_SHELL_DETAILS_WORD = "details"
_PROGRAM_NAMES = ("magnacoda", "magnacode", "magnaconda")  # the command and its typo aliases
# Typing the program's name inside its own shell: these in turn, the last one for good, each followed
# by the same real paths.
_ALREADY_HERE = (
    "You are in a maze of twisty little prompts, all alike.",
    'A sign here reads: "You are here."',
    "You are carrying one {name} shell. It is already open.",
    "You hear the faint hum of a terminal. It is yours.",
    "Nothing happens.",
)
_OBVIOUS_PATHS = "Obvious paths: help, scan URL, wizard."
# Words from the old adventure games, answered in the shell (a command of the same name comes first).
_ADVENTURE_WORDS = {
    "xyzzy": "Nothing happens.",
    "plugh": "Nothing happens.",
    "look": _ALREADY_HERE[0],
    "inventory": "You are carrying one {name} shell.",
    "i": "You are carrying one {name} shell.",
    **dict.fromkeys(("north", "south", "east", "west", "n", "s", "e", "w"), "You can't go that way."),
}


def _leave_on_purpose(name: str) -> bool:
    """Ask before leaving the shell on q or Ctrl+C (exit, quit and Ctrl+D leave at once). Enter, n, q
    and Ctrl+C stay; without a person there (piped input), it leaves as before."""
    if not _is_interactive():
        return True
    try:
        return _ask_yes_no(f"Leave {name}?", default=False)
    except click.Abort:
        _echo()  # the blank line Enter or n would give
        return False


def _program_names() -> set[str]:
    """What people type to start magnacoda, an edition's commands included (its word added on)."""
    word = plugins.edition().word
    return {name + word for name in _PROGRAM_NAMES} | set(_PROGRAM_NAMES)


_DETAILS_HINT = "Type details to see more."


def _keep_details(state: object) -> bool:
    """In the shell, keep the error being handled for `details`. True if kept."""
    if not (isinstance(state, dict) and state.get("in_shell")):
        return False
    state["last_error"] = (state.get("line", ""), datetime.now(), traceback.format_exc())
    return True


def _show_details(console: Console, state: dict[str, Any]) -> None:
    kept = state.get("last_error")
    if not kept:
        teletype.say(console, "No error details: nothing unexpected has gone wrong in this session.")
        return
    line, when, details = kept
    console.print(
        f"The last error, at {when:%H:%M}, from: {line}\n\n{details.rstrip()}\n\n"
        f"magnacoda {__version__}, Python {platform.python_version()}, {platform.platform()}\n"
        "If it looks like a bug, please report it with these details (type about for where).",
        markup=False,
        highlight=False,
        soft_wrap=True,  # whole lines, so they copy cleanly into a report
    )


@main.command()
@click.option(
    "--force-setup-notice",
    is_flag=True,
    default=False,
    help="Always show the Chromium setup notice, regardless of whether it's actually installed "
    "(for checking how the notice looks, without uninstalling anything).",
)
# A shortcut's window closes when the shell ends, so the shortcut says so and the shell pauses first.
@click.option("--from-shortcut", is_flag=True, default=False, hidden=True)
def shell(force_setup_notice: bool, from_shortcut: bool) -> None:
    """Start an interactive session: run scan/wizard/setup repeatedly without retyping magnacoda."""
    console = Console()
    names = plugins.edition()
    # The prompt always says just magnacoda: an edition word run into it ("magnacodaexample") is hard to
    # read, and the banner names the edition anyway.
    name = name_color.style(console)
    prompt = f"[{name}]{plugins.PRODUCT}[/{name}] [dim]»[/dim] "

    def banner(current: str | None) -> str:
        return (
            f"[{name} italic]{escape(names.display_name)}[/{name} italic] accessibility scanner - "
            "type a command, or exit to leave.\n"
            "[bold]Commands:[/bold] "
            + _command_words(
                ["scan", "wizard", "help", "setup", "review", "update", "clear", "about"], current
            )
            + "\n"
            + _addon_commands_line(current)
        )

    news.note_first_run()
    news.refresh_in_background()  # once a day; the banner shows what the previous check found
    # Updates and news: only in the day's first shell, on up to three days (news.today_notice).
    today = news.today_notice()

    def show_banner(current: str | None = None) -> bool:
        """The banner and its notices, with the current section's command highlighted; whether any
        notice was shown."""
        # The news line is worked out each time, so it goes once the news has been read.
        teletype.say(console, banner(current))
        # Worked out each time, so the notice goes once setup has run.
        show_chromium_notice = force_setup_notice or not _chromium_probably_installed()
        if show_chromium_notice:
            _print_notice(console, _CHROMIUM_NOTICE)
        notice = news.notice_line(only=today) if today else ""
        if notice:
            label, _, rest = notice.partition(": ")
            _print_notice(console, f"[bold]{escape(label)}:[/bold] {escape(rest)}")
        return show_chromium_notice or bool(notice)

    # Teletype style (see teletype.py): nothing is erased. Earlier text scrolls up into the scrollback,
    # output keeps printing below; only start-up, `clear`, the sections (sections.new_page: scan, wizard,
    # review, setup, update, about, an add-on's own) and leaving help or news feed a page.
    teletype.page_feed(console)
    screenreader.offer()  # once, before anything is typed out
    if not show_banner():  # a tip only when there's no other notice
        _show_tip(console)
    pending: str | None = None
    if not force_setup_notice and not _chromium_probably_installed() and _is_interactive():
        try:
            if _ask_yes_no("Set it up now?", default=True):
                pending = "setup"
        except click.Abort:
            pass

    def banner_on_top(current: str | None = None) -> None:
        # The help pager restores the screen it found (a resize while paging can shift it); feed a
        # page so the banner is on top again. Nothing is erased.
        teletype.page_feed(console)
        show_banner(current)
        if current:  # a section's page: its name as a heading, which screen readers read out too
            teletype.say(console, f"[bold]{escape(current.capitalize())}[/bold]\n")
            questions.printed("\n")

    # "new_page": a section (sections.new_page) gets a page of its own, with the banner on top.
    shell_state: dict[str, Any] = {"in_shell": True, "after_pager": banner_on_top, "new_page": banner_on_top}
    goodbye = False  # leaving by choice (exit, Ctrl+D, Ctrl+C at the prompt), not because of `update`
    while True:
        try:
            line = pending or console.input(prompt).strip()
            pending = None
        except EOFError:  # Ctrl+D: leave
            console.print()
            goodbye = True
            break
        except KeyboardInterrupt:  # Ctrl+C: often pressed again and again, so ask first
            console.print()
            if _leave_on_purpose(names.display_name):
                goodbye = True
                break
            continue
        if not line:
            continue
        # A scan the previous command finished, for this command only (`review` opens it directly).
        shell_state["scanned_before"] = shell_state.pop("scanned", None)
        first, _, rest = line.partition(" ")
        if rest.strip() and first.lower() in _program_names():
            line = rest.strip()  # "magnacoda scan URL", as written outside the shell: run "scan URL"
        if line.lower() in _SHELL_EXIT_WORDS:
            if line.lower() == "q" and not _leave_on_purpose(names.display_name):
                continue  # q also cancels questions, so it's easy to press once too often
            goodbye = True
            break
        if line.lower() == "shell":
            teletype.say(console, f"Already in the {escape(names.display_name)} shell.")
            continue
        if line.lower() in _program_names():  # starting magnacoda again, from inside it
            turn = shell_state.get("already_here", 0)
            shell_state["already_here"] = turn + 1
            here = _ALREADY_HERE[min(turn, len(_ALREADY_HERE) - 1)]
            teletype.say(console, f"{here.format(name=escape(names.display_name))}\n{_OBVIOUS_PATHS}")
            continue
        if line.lower() in _ADVENTURE_WORDS and line.lower() not in main.commands:  # a real command wins
            here = _ADVENTURE_WORDS[line.lower()]
            teletype.say(console, f"{here.format(name=escape(names.display_name))}\n{_OBVIOUS_PATHS}")
            continue
        if line.lower() in _SHELL_CLEAR_WORDS:
            teletype.page_feed(console)
            show_banner()
            continue
        if line.lower() == _SHELL_DETAILS_WORD:
            _show_details(console, shell_state)
            continue
        try:
            args = shlex.split(line)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] unable to parse that line ({exc}).")
            continue
        shell_state["line"] = shlex.join(savedcommand.redact(args))  # for details: no cookie values
        try:
            main.main(args=args, prog_name="magnacoda", standalone_mode=False, obj=shell_state)
        except questions.Cleared:
            teletype.page_feed(console)
            show_banner()
        except (click.Abort, KeyboardInterrupt):
            teletype.say(console, "\nCancelled.")  # Ctrl+C in the middle of a command: back to the prompt
        except SystemExit:
            pass  # scan/setup/wizard exit with a status code by design; the shell itself stays up
        except click.ClickException as exc:
            exc.show()
        except click.exceptions.Exit:
            pass
        except Exception as exc:  # noqa: BLE001 - one bad command must not kill the session
            _keep_details(shell_state)
            console.print(f"[red]Error:[/red] {escape(str(exc))}\n{_DETAILS_HINT}")
        if shell_state.pop("leave", False):  # `update` ended the session (see _leave_the_session)
            break
    if goodbye and _interactive(console):
        for text in farewell.lines():
            teletype.say(console, text)
        console.print()  # a blank line before the terminal's own prompt
    if from_shortcut and _interactive(console):
        window.before_closing()


_TIP_WIDTH = 60  # a tip is short reading: its lines stop by column 60, even in a wide terminal


def _show_tip(console: Console) -> None:
    """A tip under the banner at shell start, unless tips are off."""
    if not _interactive(console) or not preferences.load().tips:
        return
    tip = tips.next_tip()
    if tip:
        _print_notice(console, f"[bold]Tip:[/bold] {tips.markup(tip)}", max_width=_TIP_WIDTH)


def _interactive(console: Console) -> bool:
    """A person at a terminal, not a script piping commands in (its output stays clean)."""
    try:
        return console.is_terminal and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


@main.command(name="scan", cls=_ScanCommand)
@click.argument("url", required=False)
@click.option("--ai", type=click.Choice(["off", "explain", "semantic"]), default="off", show_default=True)
@click.option("--wcag-version", type=click.Choice(["2.0", "2.1", "2.2"]), default="2.2", show_default=True)
@click.option("--level", type=click.Choice(["A", "AA", "AAA"]), default="AA", show_default=True)
@click.option(
    "--screen",
    type=click.Choice(["desktop", "mobile", "both"]),
    default=None,
    help="Scan as a desktop (the default) or a phone; 'both' scans desktop, then mobile, in one report.",
)
@click.option(
    "--quick/--thorough",
    default=None,
    help="Quick: leave out the slowest tests that use the page (moving content, hovering, clicking, "
    "single keys), about 10 seconds a scan. Default: the quick setting under [scan] in preferences.ini "
    "(off).",
)
@click.option(
    "--show-findings",
    is_flag=True,
    default=False,
    help="Also show the full findings here (otherwise a short summary).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Also write the full results as JSON to this file (for CI); -o - prints them instead.",
)
@click.option(
    "--fail-on",
    type=click.Choice(["none", "minor", "moderate", "serious", "critical"]),
    default="serious",
    show_default=True,
)
@click.option("-v", "--verbose", count=True)
@click.option("--extra-http-header", "extra_http_headers", multiple=True, callback=_parse_kv_pairs)
@click.option("--cookie", "cookies", multiple=True)
@click.option("--storage-state", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--ignore-https-errors", is_flag=True, default=False)
@click.option("--wait-for-selector", default=None)
@click.option("-y", "--yes", is_flag=True, default=False)
# Advanced options: hidden from --help, listed in help's "advanced" section.
@click.option("--ai-model", default="claude-sonnet-5", hidden=True)
@click.option(
    "--ai-engine",
    type=click.Choice(["auto", "api", "api-key", "claude-code", "claude-plan"]),
    default="auto",
    hidden=True,
)
@click.option("--include-best-practice", is_flag=True, default=False, hidden=True)
@click.option(
    "--browser",
    "browser_name",
    type=click.Choice(["chromium", "firefox", "webkit"]),
    default="chromium",
    hidden=True,
)
@click.option("--headful", is_flag=True, default=False, hidden=True)
@click.option("--viewport", callback=_parse_viewport, default=None, metavar="WIDTHxHEIGHT", hidden=True)
@click.option("--device", default=None, hidden=True)
@click.option("--user-agent", default=None, hidden=True)
@click.option("--color-scheme", type=click.Choice(["light", "dark", "both"]), default=None, hidden=True)
@click.option("--wait", "wait_seconds", type=click.FloatRange(min=0), default=0, hidden=True)
@click.option("--scans-dir", type=click.Path(path_type=Path), default=None, hidden=True)
def scan_cmd(
    url: str | None,
    ai: AITier,
    wcag_version: WcagVersion,
    level: WcagLevel,
    screen: str | None,
    quick: bool | None,
    show_findings: bool,
    output_path: Path | None,
    fail_on: FailOn,
    verbose: int,
    extra_http_headers: dict[str, str],
    cookies: tuple[str, ...],
    storage_state: Path | None,
    ignore_https_errors: bool,
    wait_for_selector: str | None,
    yes: bool,
    ai_model: str,
    ai_engine: AIEngine,
    include_best_practice: bool,
    browser_name: BrowserName,
    headful: bool,
    viewport: tuple[int, int] | None,
    device: str | None,
    user_agent: str | None,
    color_scheme: str | None,
    wait_seconds: float,
    scans_dir: Path | None,
) -> None:
    """Scan URL for WCAG accessibility issues."""
    scans_dir = scans_dir or scans_folder()
    _new_scan_page()
    if url is None:
        url = _ask_address()
    typed_url = url
    address = _address_for(url)
    url = address.url
    if screen == "both" and (device or viewport):
        raise click.UsageError(
            "--screen both can't be combined with --device or --viewport: they fix one specific screen. "
            "Use --screen mobile or --screen desktop with them, or drop them."
        )

    parsed_cookies = []
    for item in cookies:
        if "=" not in item:
            raise click.BadParameter(f"expected NAME=VALUE, got {item!r}", param_hint="--cookie")
        name, value = item.split("=", 1)
        parsed_cookies.append({"name": name, "value": value, "url": url})

    config = ScanConfig(
        url=url,
        ai=AIConfig(
            tier=ai,
            model=ai_model,
            assume_yes=yes,
            engine=_ENGINE_ALIASES.get(ai_engine, ai_engine),
        ),
        fixes_tier="ai" if ai != "off" else "template",
        wcag_version=wcag_version,
        level=level,
        include_best_practice=include_best_practice,
        quick=preferences.load().quick if quick is None else quick,
        output_path=output_path,
        fail_on=fail_on,
        verbosity=verbose,
        browser_name=browser_name,
        headless=not headful,
        viewport_width=viewport[0] if viewport else None,
        viewport_height=viewport[1] if viewport else None,
        device=device,
        user_agent=user_agent,
        extra_http_headers=extra_http_headers,
        cookies=parsed_cookies,
        storage_state=storage_state,
        ignore_https_errors=ignore_https_errors,
        # --wait gives a slow page that much longer to load and to settle.
        stability=StabilityConfig(
            wait_for_selector=wait_for_selector,
            nav_timeout_ms=30_000 + round(wait_seconds * 1000),
            stability_timeout_ms=30_000 + round(wait_seconds * 1000),
        ),
    )

    if not yes and _is_interactive() and preferences.load().confirm and _address_alone():
        quick_note = ", quick (set in preferences.ini)" if config.quick else ""
        defaults = f"WCAG {wcag_version} {level}, a desktop screen, light and dark mode, no AI{quick_note}"
        saved = _saved_scans_for(url)
        if saved:
            chosen = _choose_saved_scan(url, saved, defaults)
            if chosen is not None:
                for note in chosen.notes:
                    _echo(note)
                parent = click.get_current_context().find_root()
                _echo("Equivalent command:\n  " + savedcommand.display_command(chosen))
                if _ask_yes_no("Change anything?", default=False):
                    _finish_and_run(parent, _ask_settings(chosen, chosen.url, fresh=False))
                else:
                    _run_saved_scan(parent, chosen)
                return
        elif not _ask_yes_no(
            "Scan with these settings?", intro=f"The default settings: {defaults}.", default=True
        ):
            program = _program()
            _echo(
                f"Nothing was scanned. To choose the settings step by step, type {program}wizard; to see "
                f"the options, type {program}help (the scan section)."
            )
            return

    # How long it will take, with faster settings offered: here, so it's the same however the scan
    # was started (typed, the wizard, a favorite, a saved scan). Once a run; not with -y or in scripts.
    ctx = click.get_current_context()
    if not yes and _is_interactive() and preferences.load().estimate and not ctx.meta.get(_ESTIMATED):
        ctx.meta[_ESTIMATED] = True
        planned = savedcommand.parse(shlex.join(ctx.meta[_ARGS_KEY]), takes_value=_scan_option_takes_value)
        if planned is not None:
            faster = estimate.offer_faster(planned, echo=_echo)
            if faster is not planned:
                _echo("Equivalent command:\n  " + savedcommand.display_command(faster))
                _run_saved_scan(ctx.find_root(), faster)
                return

    # Ask before following a redirect to another site. Skipped with login options, which the quick
    # check doesn't send.
    requested = None
    if _is_interactive() and not (parsed_cookies or extra_http_headers or storage_state):
        landed = redirects.check_address(url, ignore_https_errors=ignore_https_errors)
        if landed is None and address.added == "https":
            # No answer over https: the scan will fall back to http, so check where that leads too.
            landed = redirects.check_address(addresses.as_http(url))
        if landed and not redirects.same_site(url, landed):
            here, there = redirects.host(url), redirects.host(landed)
            if not _ask_yes_no(
                f"Scan {there} instead?",
                intro=f"{here} redirects to another site: {landed}",
                default=True,
            ):
                _echo("Cancelled - nothing was scanned.")
                return
            requested, url = url, landed
            config = config.model_copy(update={"url": url})

    # Full light pass per screen, then a short dark pass; merged into one scan (findings/merge.py).
    both_themes = color_scheme in (None, "both")
    first_scheme = "light" if both_themes else color_scheme
    screens: list[str | None] = ["desktop", "mobile"] if screen == "both" else [screen]
    # -o - prints the JSON (for a pipe) instead of the summary; results.json is written too.
    print_json = output_path is not None and str(output_path) == "-"
    if print_json:
        output_path = None
    # The folder is named after the scan, from the page it landed on.
    started = datetime.now()
    config = config.model_copy(update={"capture_images": True})
    targets = [output_path] if output_path else []
    if output_path and output_path.is_dir():
        raise click.UsageError(f"{output_path} is a directory; give a file name.")
    reports_dir_existed = scans_dir.exists()
    for target in [scans_dir / "results.json", *targets]:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise click.UsageError(f"Cannot write to {target}: {exc.strerror or exc}") from exc
    if not reports_dir_existed and scans_dir.is_dir():
        # Only a folder we just created: never add a `*` rule to a directory the user already had
        # (e.g. --scans-dir .).
        make_self_ignoring(scans_dir)

    reports: list[ScanReport] = []
    passes: list[merge.Pass] = []
    try:
        if config.ai.tier != "off":
            if config.ai.claude_plan_undecided() and _is_interactive():
                # Once: the answer is saved for every scan after this, and applies to this one.
                config.ai.engine = "claude-code" if _ask_about_claude_plan() else "api"
            confirm_ai_usage(config.ai, passes=len(screens))
        _record_history(typed_url, url)
        # Fall back to http:// only when https:// was added automatically, and never with cookies or
        # headers, which would then go unencrypted.
        may_fall_back = address.added == "https" and not parsed_cookies and not extra_http_headers
        # The estimate, if one was made: the spinner shows it beside the time so far, and it's saved.
        expected = click.get_current_context().meta.pop("magnacoda.estimate", None)
        begun = time.monotonic()
        dark_seen: list[bool] = []

        def attempt(run: Callable[[ScanConfig], T]) -> T:
            nonlocal config, may_fall_back
            try:
                return run(config)
            except NavigationError as exc:
                if not (may_fall_back and exc.could_not_connect):
                    raise
                may_fall_back = False
                http_url = addresses.as_http(config.url)
                _echo(f"{config.url} didn't answer over https; trying {http_url}", err=True)
                config = config.model_copy(update={"url": http_url})
                return run(config)

        with _scan_progress(config.url, expected=expected) as next_pass:
            for number, pass_screen in enumerate(screens, start=1):
                next_pass(number, len(screens), pass_screen if len(screens) > 1 else None)
                on_phone = pass_screen == "mobile" or (pass_screen is None and bool(device))
                where = "mobile" if on_phone else "desktop"
                full = attempt(
                    lambda c, s=pass_screen: run_scan(  # type: ignore[misc]
                        c.model_copy(update={"color_scheme": first_scheme, "screen": s}),
                        consent_given=True,
                    )
                )
                passes.append(merge.Pass(merge.label(where, first_scheme), full))
                if both_themes:
                    dark = attempt(
                        lambda c, s=pass_screen, light=full.fingerprint: run_dark_pass(  # type: ignore[misc]
                            c.model_copy(update={"screen": s}), light
                        )
                    )
                    dark_seen.append(dark is not None)
                    if dark is not None:
                        passes.append(
                            merge.Pass(
                                merge.label(where, "dark"),
                                dark,
                                covered=theme.covered(level, include_best_practice),
                            )
                        )
        reports.append(merge.merge(passes, any(dark_seen) if both_themes else None))
        reports[-1].meta.scan_seconds = round(time.monotonic() - begun, 1)
        reports[-1].meta.estimated_seconds = round(expected, 1) if expected else None
    except AIAuthenticationError as exc:
        _echo(f"Error: {exc}", err=True)
        if config.ai.resolve_engine() == "claude-code":
            # The message already says what to do (run `claude`, then /login); no key to paste.
            _stopped()
        if _is_interactive() and _ask_yes_no("Enter a new Anthropic API key now?", default=False, err=True):
            if _prompt_and_save_key(config.ai.api_key_env):
                _echo("Saved. Re-run your scan to try again.", err=True)
        else:
            _echo(
                "Re-run `magnacoda setup` to enter a new one, or set it directly: "
                f"export {config.ai.api_key_env}=sk-ant-...",
                err=True,
            )
        _stopped()
    except MagnacodaError as exc:
        _echo(f"Error: {exc}", err=True)
        _stopped()
    except (click.ClickException, click.exceptions.Abort):
        raise  # Click's own messages (a wrong option, Ctrl+C at a question)
    except Exception as exc:  # noqa: BLE001 - anything unforeseen: a short message, not a traceback
        if verbose:
            traceback.print_exc()
        in_shell = _keep_details(click.get_current_context().obj)
        first = (str(exc).strip().splitlines() or [""])[0][:200]
        _echo(
            f"Error: magnacoda stopped unexpectedly ({type(exc).__name__}{': ' + first if first else ''}). "
            + (
                "The details are above."
                if verbose
                else f"This is likely a bug in magnacoda. {_DETAILS_HINT}"
                if in_shell
                else "This is likely a bug in magnacoda; run the scan again with -v to see the details."
            ),
            err=True,
        )
        _stopped()

    report = reports[0]
    if requested and not report.meta.requested_url:
        report.meta.requested_url = requested  # the redirect followed after asking, before the scan
    scan_dir = scans_dir / default_report_stem(report.url, started)
    scan_dir.mkdir(parents=True, exist_ok=True)
    # A repeat scan of the same page keeps what a person already checked (not automated results).
    carried: dict[str, str] = {}
    carried_from = None
    previous, when = saved_reports.previous_ticks(scans_dir, scan_dir, report.url, "", wcag_version, level)
    if when is not None:
        carried = {item: f"{when:%Y-%m-%d}" for item in previous}
        carried_from = when
    checklist_md, results_json = scan_dir / "checklist.md", scan_dir / "results.json"
    copies: list[Path] = []
    carried_total = write_markdown(report, checklist_md, scan_dir / "images", carried=carried)
    write_json(report, results_json)
    if carried_total:
        ticks.mirror(checklist_md, results_json)
    if output_path is not None:
        shutil.copyfile(results_json, output_path)
        copies.append(output_path)
    if print_json:
        click.echo(to_json(report))
    elif show_findings:
        render_report(report)  # no colors when NO_COLOR is set (Rich reads it)

    for target in copies:
        _echo(f"Wrote {target}", err=True)
    kept = (carried_total, carried_from) if carried_total and carried_from is not None else None
    _say_what_was_saved(scan_dir, report, kept)
    obj = click.get_current_context().obj
    if isinstance(obj, dict):
        obj["scanned"] = scan_dir  # `review` as the next command opens this scan (see review_cmd)

    for report in reports:
        plugins.call_all("after_scan", report)

    if fail_on == "none":
        sys.exit(0)
    threshold = SEVERITY_RANK[fail_on]
    at_or_above = sum(
        1 for report in reports for f in report.findings if SEVERITY_RANK[f.severity] <= threshold
    )
    if at_or_above and not sys.stderr.isatty():
        # Explain the exit code in CI logs; stderr keeps JSON on stdout clean.
        _echo(
            f"Exit code 1: {_plural(at_or_above, 'problem')} at or above {fail_on} (--fail-on {fail_on}). "
            "This is for scripts and CI; use --fail-on none to always exit 0.",
            err=True,
        )
    sys.exit(1 if at_or_above else 0)


def _minutes(seconds: float) -> str:
    """'45 s', '1 min', '2 min 10 s'."""
    minutes, rest = divmod(int(seconds), 60)
    return " ".join([f"{minutes} min"] * bool(minutes) + [f"{rest} s"] * bool(rest)) or "0 s"


class _ScanTime:
    """The spinner's time: the estimate as made before the scan, never recalculated, and the time so far
    beside it, in steps of 5 seconds from 5 seconds on."""

    STEP = 5

    def __init__(self, expected: float | None, clock: Callable[[], float] = time.monotonic) -> None:
        self.expected = expected
        self.clock = clock
        self.start = clock()

    def text(self) -> str:
        """'about 2 min estimated, 45 s so far', '45 s so far', or "" (no estimate, and too early)."""
        elapsed = (self.clock() - self.start) // self.STEP * self.STEP
        parts = [f"{estimate.duration(self.expected)} estimated"] if self.expected else []
        if elapsed:
            parts.append(f"{_minutes(elapsed)} so far")
        return ", ".join(parts)


@contextmanager
def _scan_progress(
    url: str, verb: str = "Scanning", expected: float | None = None
) -> Iterator[Callable[[int, int, str | None], None]]:
    """Spinner with the current pass, step and time (_ScanTime). With `spinner = off` (screen readers), one
    plain line per pass instead; nothing outside a terminal."""
    console = Console(stderr=True)
    if not console.is_terminal:
        yield lambda number, total, label: None
        return
    where = {"text": "", "what": "starting"}
    clock = _ScanTime(expected)

    def place(number: int, total: int, label: str | None) -> str:
        variant = (label or "").replace(".", ", ")
        if total == 1:
            return ""
        return f" ({variant}: {number} of {total})" if variant else f" ({number} of {total})"

    if not preferences.load().spinner:

        def plain(number: int, total: int, label: str | None) -> None:
            spent = clock.text()
            _echo(f"{verb} {url}{place(number, total, label)}{', ' + spent if spent else ''}...", err=True)

        yield plain
        return
    with console.status("", spinner="line") as status:

        def show(what: str) -> None:
            # The page and the time on the spinner's line, the step under it (it changes often).
            where["what"] = what
            spent = clock.text()
            status.update(
                f"{verb} {escape(url)}"
                + (f" - {escape(spent)}" if spent else "")
                + f"\n  {escape(what)}{escape(where['text'])}"
            )

        def next_pass(number: int, total: int, label: str | None) -> None:
            where["text"] = place(number, total, label)
            show("starting")

        # The time changes every 5 seconds even while one step runs on.
        stop = threading.Event()

        def tick() -> None:
            while not stop.wait(5):
                show(where["what"])

        ticker = threading.Thread(target=tick, daemon=True)
        ticker.start()
        try:
            with progress.listening(show):
                yield next_pass
        finally:
            stop.set()


def _stopped() -> NoReturn:
    """Exit with code 2 after an error, explaining the code when output isn't a terminal."""
    if not sys.stderr.isatty():
        _echo(
            "Exit code 2: the scan didn't finish, so nothing was checked or saved. (Exit code 1 would mean "
            "it ran and found problems.)",
            err=True,
        )
    sys.exit(2)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _summary(report: ScanReport, checklist_file: Path | None) -> str:
    """One line on what a saved scan found, in place of the full findings."""
    counts = [f"{n} {severity}" for severity, n in report.counts_by_severity.items() if n]
    elements = len({finding.selector for finding in report.findings})
    found = (
        f"Found {_plural(len(report.findings), 'problem')} on {_plural(elements, 'element')} "
        f"({', '.join(counts)})"
        if report.findings
        else "Found no problems the automated checks can see"
    )
    places: dict[str, int] = {}
    for finding in report.findings:
        where = merge.where_text(finding.seen_in, report.meta.variants)
        if where:
            places[where] = places.get(where, 0) + 1
    if places:
        found += "; " + ", ".join(f"{n} {where}" for where, n in places.items())
    if checklist_file is not None and checklist_file.exists():
        done = checklist.progress(checklist_file.read_text(encoding="utf-8"))
        left = done.total - done.checked
        if left:
            found += f", and {_plural(left, 'item')} to check"
    return found + "."


def _say_what_was_saved(
    folder: Path,
    report: ScanReport,
    carried: tuple[int, datetime] | None = None,
) -> None:
    """Short summary after a saved scan, on stderr so JSON on stdout stays clean."""
    _echo("", err=True)
    tested = merge.tested_text(report.meta.variants, report.meta.device, report.meta.dark_theme)
    if len(report.meta.variants) > 1 or report.meta.dark_theme is False:
        _echo(tested, err=True)
    elsewhere = redirects.from_elsewhere(report.url, report.meta.requested_url)
    if elsewhere:
        _echo(
            f"{elsewhere} redirected to {report.url}: this scan is of {redirects.host(report.url)}.", err=True
        )
    _echo(_summary(report, folder / "checklist.md"), err=True)
    if carried:
        count, when = carried
        _echo(f"Kept {_plural(count, 'tick')} from your scan of {when:%Y-%m-%d %H:%M}.", err=True)
    if report.meta.scan_seconds is not None:
        took = f"The scan took {_minutes(report.meta.scan_seconds)}"
        if report.meta.estimated_seconds:
            took += f"; the estimate was {estimate.duration(report.meta.estimated_seconds)}"
        _echo(took + ".", err=True)
    _echo(f"Saved in {short(folder)}.", err=True)
    review, recheck_word = f"{_program()}review", f"{_program()}recheck"
    bold = (lambda word: click.style(word, bold=True)) if sys.stderr.isatty() else (lambda word: word)
    fixes = f", and {bold(recheck_word)} once you've fixed some" if report.findings else ""
    _echo(f"\nType {bold(review)} to see them in your browser{fixes}.", err=True)


def _screen_default(saved: str, fresh: bool) -> str:
    """Default for "Screens to test": both for a new scan, else what the starting scan used."""
    if fresh and saved == "system":
        return "both"
    return "desktop" if saved == "system" else saved


def _scan_option_takes_value(flag: str) -> bool:
    """Whether a scan option takes a value (for options the wizard doesn't ask about)."""
    for param in scan_cmd.params:
        if isinstance(param, click.Option) and flag in (*param.opts, *param.secondary_opts):
            return not (param.is_flag or param.count)
    return False


def _pick_number(text: str, count: int, enter: str = "back") -> int | None:
    """Ask for one of 1..count, or Enter for none, which the brackets name ([back]). With enter="cancel",
    the question ends "or press Enter to cancel" (q cancels too). Re-asks on anything else."""
    if enter == "cancel":
        text += ", or press Enter to cancel"

    def check(value: str) -> int:
        value = value.strip()
        if not value and enter == "cancel":
            raise click.Abort
        if not value:
            return 0
        if value.isdigit() and 1 <= int(value) <= count:
            return int(value)
        if enter == "cancel":
            raise click.BadParameter(
                f"type one of the numbers above (1 to {count}), or press Enter to cancel."
            )
        raise click.BadParameter(f"type one of the numbers above (1 to {count}), or press Enter ({enter}).")

    brackets = "" if enter == "cancel" else f" [{enter}]"
    chosen = _ask(text + brackets, default="", show_default=False, value_proc=check)
    return int(chosen) - 1 if chosen else None


_NEW_SCAN_WORDS = ("new", "n", "fresh")


def _address_of(command: str) -> str:
    """The page a stored command scans, without https:// (http:// stays, as a warning)."""
    scan = savedcommand.parse(command, takes_value=_scan_option_takes_value)
    return (scan.url if scan else command).removeprefix("https://")


def _recent_label(when: str, command: str, width: int) -> str:
    """A recent scan on one line: its address, then when it ran (Oct 12, 02:00)."""
    return f"{_address_of(command):<{width}}  {_ran_on(when)}"


def _ran_on(when: str) -> str:
    """A history time as Oct 12, 02:00 (with the year when it isn't this one)."""
    try:
        ran = datetime.strptime(when, "%Y-%m-%d %H:%M")
    except ValueError:
        return when
    year = f" {ran.year}" if ran.year != datetime.now().year else ""
    return f"{ran:%b} {ran.day}{year}, {ran:%H:%M}"


def _same_page(url: str) -> str:
    """A form for comparing addresses: https:// and a trailing slash don't count."""
    return url.strip().lower().removeprefix("https://").rstrip("/")


def _saved_scans_for(url: str) -> list[tuple[str, savedcommand.SavedScan]]:
    """(label, scan) for each saved scan of this page with other than the default settings: add-ons'
    (favorites, if installed) first, then the latest from history.md."""
    page = _same_page(url)
    seen = {savedcommand.canonical(f"scan {url}")}  # the defaults are offered anyway
    found: list[tuple[str, savedcommand.SavedScan]] = []

    def add(label: str, command: str) -> bool:
        scan = savedcommand.parse(command, takes_value=_scan_option_takes_value)
        key = savedcommand.canonical(command)
        if scan is None or _same_page(scan.url) != page or key in seen:
            return False
        scan.origin = command
        seen.add(key)
        found.append((label, scan))
        return True

    for group in plugins.start_groups():
        for label, command in group.entries:
            add(f"{label} ({group.title})", command)
    for entry in history.read():
        scan = savedcommand.parse(entry.command, takes_value=_scan_option_takes_value)
        if scan is not None and _same_page(scan.url) == page:
            add(f"as on {_ran_on(entry.when)}", entry.command)
            break  # only the latest
    return found


def _settings_of(scan: savedcommand.SavedScan) -> str:
    """A saved scan's options, leaving out the address and the defaults."""
    tokens = savedcommand.redact(savedcommand.to_tokens(scan))[2:]
    for default in (["--level", "AA"], ["--ai", "off"]):
        at = next((i for i in range(len(tokens) - 1) if tokens[i : i + 2] == default), None)
        if at is not None:
            del tokens[at : at + 2]
    return shlex.join(tokens) or "the default settings"


def _choose_saved_scan(
    url: str, saved: list[tuple[str, savedcommand.SavedScan]], defaults: str
) -> savedcommand.SavedScan | None:
    """Offer the saved settings for this page, then the defaults; None means the defaults."""
    lines = [f"{label}: {_settings_of(scan)}" for label, scan in saved] + [
        f"the default settings: {defaults}"
    ]
    digits = len(str(len(lines)))
    _echo()
    with teletype.listing():
        _echo(f"{url.removeprefix('https://')} was scanned before. Scan it with:")
        for number, line in enumerate(lines, start=1):
            _echo(f"  {number:>{digits}}. {line}")
    questions.printed("\n")

    def check(value: str) -> int:
        value = value.strip() or "1"
        if value.isdigit() and 1 <= int(value) <= len(lines):
            return int(value)
        raise click.BadParameter(f"type one of the numbers above (1 to {len(lines)}), or q to cancel.")

    choice = _ask("Choose", default="1", value_proc=check)
    return saved[choice - 1][1] if choice <= len(saved) else None


def _group_words(groups: list[plugins.StartGroup]) -> dict[str, plugins.StartGroup | None]:
    """What may be typed to open each group (None: a new scan): its word with or without a final s (favs,
    as the shell's hidden command), its title, the title's first word with or without a final s, and the
    word's first letter when no other choice shares it."""
    words: dict[str, plugins.StartGroup | None] = dict.fromkeys(_NEW_SCAN_WORDS)
    for group in groups:
        first = group.title.split()[0].lower()
        for word in (group.key, group.key + "s", group.title.lower(), first, first.removesuffix("s")):
            words.setdefault(word, group)
    initials = [group.key[0] for group in groups] + ["n"]
    for group in groups:
        if initials.count(group.key[0]) == 1:
            words.setdefault(group.key[0], group)
    return words


def _choose_group(groups: list[plugins.StartGroup]) -> plugins.StartGroup | None:
    """Ask: a new scan, or start from one of the groups? None: a new scan."""
    words = _group_words(groups)
    counted = [f"{group.title.lower()} ({len(group.entries)})" for group in groups]
    sources = counted[0] if len(counted) == 1 else ", ".join(counted[:-1]) + " or " + counted[-1]
    typed = ", ".join(["new", *(group.key for group in groups)])

    def check(value: str) -> str:
        value = " ".join(value.strip().lower().split())
        if not value:
            raise click.Abort  # q cancels too, as at any question
        if value in words:
            return value
        raise click.BadParameter(f"type {typed}, or press Enter to cancel.")

    answer = _ask(
        f"Type {typed}, or press Enter to cancel",
        intro=f"Start a new scan, or from one of your {sources}?",
        default="",
        show_default=False,
        value_proc=check,
    )
    return words[answer]


def _choose_start_point() -> savedcommand.SavedScan | None:
    """The wizard's start: a new scan, or one from an add-on's group (see plugins.py) or the recent
    scans, each listed on its own and numbered from 1. None means a new scan."""
    groups = plugins.start_groups()
    seen = {savedcommand.canonical(command) for group in groups for _, command in group.entries}
    recent: list[tuple[str, str]] = []
    for entry in history.read():
        key = savedcommand.canonical(entry.command)
        if key not in seen:
            seen.add(key)
            recent.append((entry.when, entry.command))
        if len(recent) == _PICKER_RECENT:
            break
    if recent:
        width = max(len(_address_of(command)) for _, command in recent)
        entries = [(_recent_label(when, command, width), command) for when, command in recent]
        recent_group = plugins.StartGroup("Recent scans", entries, word="recent")
    groups = [g for g in groups if g.entries] + ([recent_group] if recent else [])
    if not groups:
        return None

    while True:
        group = _choose_group(groups)
        if group is None:
            return None
        digits = len(str(len(group.entries)))
        with teletype.listing():
            _echo(group.title)
            for number, (label, _) in enumerate(group.entries, start=1):
                _echo(f"  {number:>{digits}}. {label}")
        index = _pick_number("Type a number", len(group.entries))
        if index is None:
            continue  # back to the first question
        command = group.entries[index][1]
        scan = savedcommand.parse(command, takes_value=_scan_option_takes_value)
        if scan is None:
            _echo("That entry could not be read, so starting fresh.", err=True)
            return None
        scan.origin = command
        for note in scan.notes:
            _echo(note)
        return scan


@main.command()
@click.option(
    "--force-setup-notice",
    is_flag=True,
    default=False,
    help="Always show the Chromium setup notice, regardless of whether it's actually installed "
    "(for checking how the notice looks, without uninstalling anything).",
)
@click.pass_context
def wizard(ctx: click.Context, force_setup_notice: bool) -> None:
    """Answer a few questions, see the equivalent command, then run the scan."""
    sections.new_page(ctx, "wizard")
    screenreader.offer()
    if force_setup_notice:
        _print_notice(Console(), _CHROMIUM_NOTICE)
    elif not _chromium_probably_installed() and not _offer_chromium():
        _print_notice(Console(), _CHROMIUM_NOTICE)

    history.ensure_file()
    picked = _choose_start_point()
    start = picked or savedcommand.SavedScan()

    url = _prompt_nonempty(
        "Page to scan (an address such as example.com or localhost:3000)", default=start.url or None
    )

    scan = dataclasses.replace(start, url=url, extras=list(start.extras), notes=[])
    ask_everything = True
    if picked:
        # Starting from a saved scan: show the command with the new URL and only go through every
        # question if something besides the URL needs to change (each then defaults to the saved value).
        _echo("Equivalent command:\n  " + savedcommand.display_command(scan))
        ask_everything = _ask_yes_no("Change anything?", default=False)
    if ask_everything:
        scan = _ask_settings(start, url, fresh=picked is None)
    _finish_and_run(ctx, scan, already_shown=not ask_everything)


def _ask_settings(start: savedcommand.SavedScan, url: str, fresh: bool) -> savedcommand.SavedScan:
    """The wizard's questions, each defaulting to `start`'s value; the scan they make."""
    level = _ask(
        "WCAG level",
        intro="Which WCAG conformance level? AA is the most common legal/organizational requirement.",
        type=click.Choice(["A", "AA", "AAA"]),
        default=start.level,
    )
    ai = _ask(
        "AI reasoning",
        intro="AI reasoning uses your own Anthropic API key, or Claude Code, and sends some page data "
        "(the manual says what: docs ai tiers):\n"
        "  off       no AI: axe-core and magnacoda's own tests, fully offline\n"
        "  explain   + plain-language explanations for the top 10 findings\n"
        "  semantic  + a second AI pass for issues axe-core can't detect mechanically",
        type=click.Choice(["off", "explain", "semantic"]),
        default=start.ai,
    )

    # Desktop and a phone, by default: shown openly, as one of the things a scan does. Light and dark
    # mode aren't asked about: dark mode is checked quickly on its own (browser/theme.py).
    screen_choice = _ask(
        "Screens to test",
        intro="Test the page on a desktop screen and on a phone? 'both' is recommended: problems on one "
        f"screen only are pointed out. The phone is a {DEFAULT_MOBILE_DEVICE}.",
        type=click.Choice(["both", "desktop", "mobile"]),
        default=_screen_default(start.screen, fresh=fresh),
    )
    if screen_choice == "desktop":
        screen_choice = "system"  # desktop is what a scan does without --screen
    return dataclasses.replace(
        start, url=url, level=level, ai=ai, screen=screen_choice, extras=list(start.extras), notes=[]
    )


def _finish_and_run(ctx: click.Context, scan: savedcommand.SavedScan, already_shown: bool = False) -> None:
    """The wizard's last steps: the equivalent command, add-ons (such as saving it as a favorite), then
    run it if the person says so (the scan says how long it will take)."""
    if not already_shown:
        _echo("Equivalent command:\n  " + savedcommand.display_command(scan))

    plugins.call_all("wizard_before_run", scan)

    if not _ask_yes_no("Run this scan now?", default=True):
        _echo("Cancelled - nothing was scanned.")
        return
    _run_saved_scan(ctx, scan)


def _run_saved_scan(ctx: click.Context, scan: savedcommand.SavedScan) -> None:
    args = savedcommand.to_tokens(scan)
    ctx.meta[_ARGS_KEY] = args  # for history.md
    with scan_cmd.make_context("scan", args[1:], parent=ctx) as scan_ctx:
        scan_cmd.invoke(scan_ctx)


def run_as_magnacoda() -> None:
    """Entry point for aliases like `magnacode`; keeps the program name "magnacoda" in messages."""
    main(prog_name="magnacoda")
